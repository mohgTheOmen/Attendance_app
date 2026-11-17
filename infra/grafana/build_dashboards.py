"""Regenerate the Grafana dashboard JSON.  Usage: python infra/grafana/build_dashboards.py infra/grafana/dashboards"""
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
PROM = {"type": "prometheus", "uid": "prometheus"}
PG = {"type": "grafana-postgresql-datasource", "uid": "attendance-pg"}

_id = 0


def panel(title, ptype, targets, x, y, w, h, ds, unit=None, **extra):
    global _id
    _id += 1
    p = {
        "id": _id, "title": title, "type": ptype, "datasource": ds,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{**t, "refId": chr(65 + i), "datasource": ds} for i, t in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": unit} if unit else {}, "overrides": []},
        "options": {},
    }
    p.update(extra)
    return p


def prom(expr, legend=""):
    return {"expr": expr, "legendFormat": legend}


def sql(q, fmt="table"):
    return {"rawSql": q, "format": fmt, "rawQuery": True, "editorMode": "code"}


def dashboard(uid, title, panels, time_from="now-6h"):
    return {
        "uid": uid, "title": title, "schemaVersion": 39, "version": 1, "editable": True,
        "refresh": "30s", "time": {"from": time_from, "to": "now"}, "tags": ["attendance"],
        "panels": panels,
    }


api = dashboard("attendance-api", "Attendance API Health", [
    panel("API up", "stat", [prom('max(up{job="attendance-api"})')], 0, 0, 4, 4, PROM,
          fieldConfig={"defaults": {"mappings": [{"type": "value", "options": {
              "0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}]}, "overrides": []}),
    panel("Requests / s", "stat", [prom("sum(rate(http_requests_total[5m]))")], 4, 0, 5, 4, PROM, "reqps"),
    panel("5xx error ratio", "stat", [prom(
        'sum(rate(http_requests_total{status="5xx"}[5m])) / clamp_min(sum(rate(http_requests_total[5m])), 1e-9)')],
        9, 0, 5, 4, PROM, "percentunit"),
    panel("p95 latency", "stat", [prom(
        "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))")],
        14, 0, 5, 4, PROM, "s"),
    panel("Submissions (1h)", "stat", [prom("sum(increase(attendance_submissions_total[1h]))")],
          19, 0, 5, 4, PROM),
    panel("Request rate by endpoint", "timeseries",
          [prom("sum(rate(http_requests_total[5m])) by (method, handler)", "{{method}} {{handler}}")],
          0, 4, 12, 8, PROM, "reqps"),
    panel("Responses by status class", "timeseries",
          [prom("sum(rate(http_requests_total[5m])) by (status)", "{{status}}")], 12, 4, 12, 8, PROM, "reqps"),
    panel("Latency p50 / p95 / p99", "timeseries", [
        prom("histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))", "p50"),
        prom("histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))", "p95"),
        prom("histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))", "p99"),
    ], 0, 12, 12, 8, PROM, "s"),
    panel("Slowest endpoints (p95)", "timeseries", [prom(
        "topk(5, histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, handler)))",
        "{{handler}}")], 12, 12, 12, 8, PROM, "s"),
    panel("Attendance submissions", "timeseries",
          [prom("sum(increase(attendance_submissions_total[5m])) by (late)", "late={{late}}")],
          0, 20, 8, 8, PROM),
    panel("Reviews", "timeseries",
          [prom("sum(increase(attendance_reviews_total[5m])) by (status)", "{{status}}")], 8, 20, 8, 8, PROM),
    panel("Login attempts", "timeseries",
          [prom("sum(increase(login_attempts_total[5m])) by (result)", "{{result}}")], 16, 20, 8, 8, PROM),
])

ACTIVE = "(SELECT count(*) FROM users WHERE is_active AND role = 'user')"
# Expected attendees of event `e`: members of its groups, or every active user when it has none.
EXPECTED = (
    "(CASE WHEN EXISTS (SELECT 1 FROM event_groups eg WHERE eg.event_id = e.id) THEN "
    "(SELECT count(DISTINCT u.id) FROM users u JOIN group_members gm ON gm.user_id = u.id "
    "JOIN event_groups eg ON eg.group_id = gm.group_id "
    "WHERE eg.event_id = e.id AND u.is_active AND u.role = 'user') "
    f"ELSE {ACTIVE} END)"
)
PRESENT_ON_ROSTER = (
    "count(a.id) FILTER (WHERE a.status <> 'rejected' AND ("
    "NOT EXISTS (SELECT 1 FROM event_groups eg WHERE eg.event_id = e.id) OR "
    "EXISTS (SELECT 1 FROM event_groups eg JOIN group_members gm ON gm.group_id = eg.group_id "
    "WHERE eg.event_id = e.id AND gm.user_id = a.user_id)))"
)
biz = dashboard("attendance-overview", "Attendance Overview", [
    panel("Active users", "stat", [sql(f"SELECT {ACTIVE} AS value")], 0, 0, 4, 4, PG),
    panel("Events in range", "stat", [sql(
        "SELECT count(*) AS value FROM events WHERE $__timeFilter(starts_at)")], 4, 0, 4, 4, PG),
    panel("Submissions in range", "stat", [sql(
        "SELECT count(*) AS value FROM attendances WHERE $__timeFilter(submitted_at)")], 8, 0, 4, 4, PG),
    panel("Pending review", "stat", [sql(
        "SELECT count(*) AS value FROM attendances WHERE status = 'pending'")], 12, 0, 4, 4, PG),
    panel("Late ratio (range)", "stat", [sql(
        "SELECT coalesce(avg(CASE WHEN is_late THEN 1.0 ELSE 0 END), 0) AS value "
        "FROM attendances WHERE $__timeFilter(submitted_at)")], 16, 0, 4, 4, PG, "percentunit"),
    panel("Approval ratio (reviewed)", "stat", [sql(
        "SELECT coalesce(avg(CASE WHEN status = 'approved' THEN 1.0 ELSE 0 END), 0) AS value "
        "FROM attendances WHERE status <> 'pending' AND $__timeFilter(submitted_at)")],
        20, 0, 4, 4, PG, "percentunit"),
    panel("Submissions over time", "timeseries", [sql(
        "SELECT $__timeGroupAlias(submitted_at, '1h'), count(*) AS submissions, "
        "sum(CASE WHEN is_late THEN 1 ELSE 0 END) AS late "
        "FROM attendances WHERE $__timeFilter(submitted_at) GROUP BY 1 ORDER BY 1", "time_series")],
        0, 4, 16, 9, PG),
    panel("Status distribution", "piechart", [sql(
        "SELECT status::text AS metric, count(*) AS value FROM attendances "
        "WHERE $__timeFilter(submitted_at) GROUP BY 1")], 16, 4, 8, 9, PG,
        options={"reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": ""},
                 "legend": {"displayMode": "table", "placement": "right", "values": ["value"]}}),
    panel("Turnout per event", "table", [sql(
        "SELECT e.title AS event, e.starts_at AS starts, count(a.id) AS submissions, "
        "coalesce((SELECT string_agg(g.name, ', ') FROM event_groups eg JOIN groups g ON g.id = eg.group_id "
        "WHERE eg.event_id = e.id), 'Everyone') AS audience, "
        f"{EXPECTED} AS expected, "
        f"{PRESENT_ON_ROSTER} AS present, "
        f"round(100.0 * {PRESENT_ON_ROSTER} / nullif({EXPECTED}, 0), 1) AS turnout_pct, "
        "sum(CASE WHEN a.status = 'approved' THEN 1 ELSE 0 END) AS approved, "
        "sum(CASE WHEN a.status = 'pending' THEN 1 ELSE 0 END) AS pending, "
        "sum(CASE WHEN a.status = 'rejected' THEN 1 ELSE 0 END) AS rejected, "
        "sum(CASE WHEN a.is_late THEN 1 ELSE 0 END) AS late "
        "FROM events e LEFT JOIN attendances a ON a.event_id = e.id "
        "WHERE $__timeFilter(e.starts_at) GROUP BY e.id ORDER BY e.starts_at DESC")], 0, 13, 24, 9, PG),
    panel("Most frequent attendees (range)", "table", [sql(
        "SELECT u.full_name AS user, u.email, count(*) AS submissions, "
        "sum(CASE WHEN a.is_late THEN 1 ELSE 0 END) AS late "
        "FROM attendances a JOIN users u ON u.id = a.user_id "
        "WHERE $__timeFilter(a.submitted_at) GROUP BY u.id ORDER BY submissions DESC LIMIT 20")],
        0, 22, 24, 8, PG),
], time_from="now-30d")

def variable(name, label, query):
    return {
        "name": name, "label": label, "type": "query", "datasource": PG,
        "query": query, "definition": query,
        "current": {}, "options": [],
        "refresh": 1, "sort": 0, "multi": False, "includeAll": False,
    }


def report_dashboard(uid, title, panels, variables):
    d = dashboard(uid, title, panels, "now-180d")
    d["refresh"] = ""
    d["templating"] = {"list": variables}
    return d


student_events = """
WITH expected AS (
  SELECT e.id, e.title, e.starts_at, e.ends_at
  FROM events e
  WHERE e.starts_at <= now() AND $__timeFilter(e.starts_at)
    AND (
      NOT EXISTS (SELECT 1 FROM event_groups eg WHERE eg.event_id = e.id)
      OR EXISTS (
        SELECT 1 FROM event_groups eg
        JOIN group_members gm ON gm.group_id = eg.group_id
        WHERE eg.event_id = e.id AND gm.user_id = ${student_id:sqlstring}::bigint
      )
    )
), record AS (
  SELECT e.*, a.status, a.is_late, a.submitted_at, a.source
  FROM expected e
  LEFT JOIN attendances a ON a.event_id = e.id
    AND a.user_id = ${student_id:sqlstring}::bigint
)
"""

individual = report_dashboard("attendance-individual-record", "Report 1 - Individual Attendance Record", [
    panel("Selected student and current groups", "table", [sql("""
SELECT u.id AS student_id, u.full_name AS student, u.email,
       coalesce((SELECT string_agg(g.name, ', ' ORDER BY g.name)
                 FROM group_members gm JOIN groups g ON g.id = gm.group_id
                 WHERE gm.user_id = u.id), 'No groups') AS current_groups
FROM users u WHERE u.id = ${student_id:sqlstring}::bigint
""")], 0, 0, 24, 4, PG),
    panel("Expected sessions", "stat", [sql(student_events +
          "SELECT count(*) AS value FROM record")], 0, 4, 6, 4, PG),
    panel("Present sessions", "stat", [sql(student_events +
          "SELECT count(*) AS value FROM record WHERE status <> 'rejected'")], 6, 4, 6, 4, PG),
    panel("Missed sessions", "stat", [sql(student_events +
          "SELECT count(*) AS value FROM record WHERE status IS NULL OR status = 'rejected'")], 12, 4, 6, 4, PG),
    panel("Attendance rate", "stat", [sql(student_events +
          "SELECT coalesce(round(100.0 * count(*) FILTER (WHERE status <> 'rejected') / nullif(count(*), 0), 1), 0) AS value FROM record")],
          18, 4, 6, 4, PG, "percent"),
    panel("Attendance record - export this table as CSV", "table", [sql(student_events + """
SELECT id AS event_id, title AS event, starts_at AS starts, ends_at AS ends,
       CASE WHEN status = 'approved' THEN 'Present (approved)'
            WHEN status = 'pending' THEN 'Present (pending review)'
            WHEN status = 'rejected' THEN 'Rejected'
            ELSE 'Absent' END AS attendance,
       coalesce(is_late, false) AS late, submitted_at AS checked_in_at,
       source::text AS check_in_source
FROM record ORDER BY starts_at DESC, id DESC
""")], 0, 8, 24, 16, PG),
], [variable("student_id", "Student", "SELECT id::text AS __value, full_name || ' (' || email || ')' AS __text FROM users WHERE role = 'user' AND is_active ORDER BY full_name, id")])


session_cte = """
WITH chosen AS (
  SELECT e.id FROM events e WHERE e.id = ${event_id:sqlstring}::bigint
), roster AS (
  SELECT u.id FROM users u CROSS JOIN chosen e
  WHERE u.role = 'user' AND u.is_active
    AND (
      NOT EXISTS (SELECT 1 FROM event_groups eg WHERE eg.event_id = e.id)
      OR EXISTS (
        SELECT 1 FROM event_groups eg
        JOIN group_members gm ON gm.group_id = eg.group_id
        WHERE eg.event_id = e.id AND gm.user_id = u.id
      )
    )
), participants AS (
  SELECT id FROM roster
  UNION
  SELECT a.user_id AS id FROM attendances a JOIN chosen e ON e.id = a.event_id
), sheet AS (
  SELECT u.id, u.full_name, u.email, r.id IS NOT NULL AS on_roster,
         a.status, a.is_late, a.submitted_at, a.source
  FROM participants p JOIN users u ON u.id = p.id
  LEFT JOIN roster r ON r.id = u.id
  CROSS JOIN chosen e
  LEFT JOIN attendances a ON a.event_id = e.id AND a.user_id = u.id
)
"""

session = report_dashboard("attendance-session-sheet", "Report 5 - Class Session Attendance Sheet", [
    panel("Selected session and assigned groups", "table", [sql(session_cte + """
SELECT e.id AS event_id, e.title AS event, e.starts_at AS starts,
       coalesce((SELECT string_agg(g.name, ', ' ORDER BY g.name)
                 FROM event_groups eg JOIN groups g ON g.id = eg.group_id
                 WHERE eg.event_id = e.id), 'Everyone') AS assigned_groups,
       (SELECT count(*) FROM roster) AS active_students_in_groups
FROM events e WHERE e.id = ${event_id:sqlstring}::bigint
""")], 0, 0, 24, 4, PG),
    panel("Expected students", "stat", [sql(session_cte +
          "SELECT count(*) AS value FROM sheet WHERE on_roster")], 0, 4, 6, 4, PG),
    panel("Present students", "stat", [sql(session_cte +
          "SELECT count(*) AS value FROM sheet WHERE on_roster AND status <> 'rejected'")], 6, 4, 6, 4, PG),
    panel("Absent or rejected", "stat", [sql(session_cte +
          "SELECT count(*) AS value FROM sheet WHERE on_roster AND (status IS NULL OR status = 'rejected')")],
          12, 4, 6, 4, PG),
    panel("Turnout", "stat", [sql(session_cte +
          "SELECT coalesce(round(100.0 * count(*) FILTER (WHERE on_roster AND status <> 'rejected') / nullif(count(*) FILTER (WHERE on_roster), 0), 1), 0) AS value FROM sheet")],
          18, 4, 6, 4, PG, "percent"),
    panel("Session sheet - export this table as CSV", "table", [sql(session_cte + """
SELECT id AS student_id, full_name AS student, email,
       CASE WHEN on_roster THEN 'Yes' ELSE 'No (extra attendee)' END AS expected,
       CASE WHEN status = 'approved' THEN 'Present (approved)'
            WHEN status = 'pending' THEN 'Present (pending review)'
            WHEN status = 'rejected' THEN 'Rejected'
            ELSE 'Absent' END AS attendance,
       coalesce(is_late, false) AS late, submitted_at AS checked_in_at,
       source::text AS check_in_source
FROM sheet ORDER BY on_roster DESC, full_name, id
""")], 0, 8, 24, 18, PG),
], [variable("event_id", "Session", "SELECT id::text AS __value, title || ' - ' || to_char(starts_at AT TIME ZONE 'Europe/Bucharest', 'YYYY-MM-DD HH24:MI') || ' (#' || id || ')' AS __text FROM events ORDER BY starts_at DESC, id DESC")])

for name, d in [("api-health.json", api), ("attendance-overview.json", biz),
                ("individual-record.json", individual), ("session-sheet.json", session)]:
    (out / name).write_text(json.dumps(d, indent=2))
print("ok")
