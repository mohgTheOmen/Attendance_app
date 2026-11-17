"""Check provisioned report dashboards against a running local Grafana deployment."""

import base64
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def request(path, payload=None):
    headers = {"Authorization": AUTH}
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Grafana API {path}: HTTP {exc.code}: {exc.read().decode()}") from exc


def query(sql):
    result = request("/api/ds/query", {
        "queries": [{"refId": "A", "datasource": {"uid": "attendance-pg"},
                     "rawSql": sql, "format": "table", "rawQuery": True,
                     "intervalMs": 60000, "maxDataPoints": 1000}],
        "from": "946684800000", "to": "4102444800000",
    })["results"]["A"]
    if result.get("error"):
        raise RuntimeError(result["error"])
    frames = result.get("frames", [])
    if not frames:
        return []
    values = frames[0]["data"]["values"]
    return list(zip(*values)) if values else []


if __name__ == "__main__":
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.deploy")
    env = dict(line.split("=", 1) for line in env_path.read_text().splitlines()
               if "=" in line and not line.lstrip().startswith("#"))
    port = env.get("GRAFANA_PORT", "3000")
    BASE = os.environ.get("GRAFANA_URL", f"http://localhost:{port}")
    AUTH = "Basic " + base64.b64encode(
        ("admin:" + env["GRAFANA_ADMIN_PASSWORD"]).encode()).decode()

    health = request("/api/datasources/uid/attendance-pg/health")
    if health.get("status") != "OK":
        raise RuntimeError(f"PostgreSQL data source unhealthy: {health}")
    try:
        query("SELECT password_hash FROM users LIMIT 1")
    except RuntimeError as exc:
        if "permission denied" not in str(exc):
            raise
    else:
        raise RuntimeError("Grafana can read password hashes")

    samples = query("SELECT (SELECT id FROM users WHERE role = 'user' AND is_active ORDER BY id LIMIT 1) AS student_id, "
                    "(SELECT id FROM events ORDER BY id LIMIT 1) AS event_id")
    if not samples or None in samples[0]:
        raise RuntimeError("Need an active student and event to verify reports")
    student_id, event_id = samples[0]

    for uid, var, value in [
        ("attendance-individual-record", "student_id", student_id),
        ("attendance-session-sheet", "event_id", event_id),
    ]:
        dashboard = request("/api/dashboards/uid/" + uid)["dashboard"]
        if not dashboard.get("templating", {}).get("list"):
            raise RuntimeError(f"{uid} has no selector")
        options_sql = dashboard["templating"]["list"][0]["query"]["query"]
        if not query(options_sql):
            raise RuntimeError(f"{uid} selector has no options")
        for panel in dashboard["panels"]:
            sql = panel["targets"][0]["rawSql"]
            sql = sql.replace("${" + var + ":sqlstring}", "'" + str(value) + "'")
            rows = query(sql)
            print(f"{uid}: {panel['title']}: {len(rows)} row(s)")

    overview = request("/api/dashboards/uid/attendance-overview")["dashboard"]
    turnout = next(p for p in overview["panels"] if p["title"] == "Turnout per event")
    print(f"attendance-overview: Turnout per event: {len(query(turnout['targets'][0]['rawSql']))} row(s)")

    print("Grafana report verification passed")
