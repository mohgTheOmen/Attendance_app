"""OCR import pipeline. Names are fictional; the noisy lines imitate real Tesseract output on
handwriting (swapped letters, split/merged words, garbled numbering and group codes)."""
import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ocr import engines
from app.ocr.matching import Candidate, match_lines, normalize_line, split_name
from tests.conftest import png_bytes
from tests.test_app import make_event

ROSTER = [
    "POPOVICI A. Matei-Andrei", "DRAGOMIR C. Ioana-Maria", "STANCIU V. Radu", "MARINESCU D.G. Elena",
    "VASILESCU I. Bogdan-Cristian", "ENACHE M. Sofia", "ENACHE M. Daria", "TOMESCU R. Vlad",
    "IORDACHE P. Andrei", "BARBU S. Teodora-Ioana", "HASSAN Omar", "AL FARSI Layla Noor",
]
CANDIDATES = [Candidate(i + 1, n) for i, n in enumerate(ROSTER)]
ID = {n.split()[0] + " " + n.split()[-1]: i + 1 for i, n in enumerate(ROSTER)}

OCR_LINES = [
    "26 Oct S1",                          # header -> ignored
    "1)POPOVlCI MATEI -ANDRE)",           # matched
    "2) DRAGOMLR lOANA MARlA",            # matched
    "3) STANClU RADV",                    # matched
    "4\\MARlNESCV ELEMA",                 # review-ish
    "5) ENACHE SOFlA 1241EA",             # group code stripped; must not pick Daria
    "6) ENACHE DARIA",
    "7) HASAN OMAR 124\\E8",
    "8) ALFARSI LAYLA NOOR",
    "9) Jonathan Pierce - ERASMUS",       # not on the roster -> unmatched
    "0,75",                               # grade -> ignored
]


def test_normalize_line():
    assert normalize_line("5) ENACHE Sofía 1241EA") == "ENACHE SOFIA"
    assert normalize_line("UM) Pierce - ERASMUS") == "PIERCE"
    assert normalize_line("0,75") == ""


def test_split_name():
    assert split_name("BARBU S. Teodora-Ioana") == ("BARBU", "TEODORA IOANA")
    assert split_name("AL FARSI Layla Noor") == ("AL FARSI", "LAYLA NOOR")
    assert split_name("Alice Johnson") == ("JOHNSON", "ALICE")


def test_match_noisy_list():
    results = match_lines([(0, line) for line in OCR_LINES], CANDIDATES)
    got = {r.raw: r for r in results}
    picked = {r.user_id for r in results if r.status in ("matched", "review")}
    assert picked == {ID["POPOVICI Matei-Andrei"], ID["DRAGOMIR Ioana-Maria"], ID["STANCIU Radu"],
                      ID["MARINESCU Elena"], ID["ENACHE Sofia"], ID["ENACHE Daria"], ID["HASSAN Omar"],
                      ID["AL Noor"]}
    assert got["5) ENACHE SOFlA 1241EA"].user_id == ID["ENACHE Sofia"]
    assert got["26 Oct S1"].status == "ignored" and got["0,75"].status == "ignored"
    assert got["9) Jonathan Pierce - ERASMUS"].status == "unmatched"
    assert got["9) Jonathan Pierce - ERASMUS"].suggestions  # admin still gets guesses


def test_one_to_one_and_duplicates():
    lines = [(0, "3) STANCIU RADU"), (1, "STANCIU RADU"), (1, "12) STANCIU  R4DU")]
    results = match_lines(lines, CANDIDATES)
    assert [r.status for r in results] == ["matched", "duplicate", "duplicate"]
    assert all(r.user_id == ID["STANCIU Radu"] for r in results)


def test_already_present():
    results = match_lines([(0, "TOMESCU VLAD")], CANDIDATES, already_present={ID["TOMESCU Vlad"]})
    assert results[0].status == "already_present"


# --- API --------------------------------------------------------------------------
@pytest.fixture()
def roster(client, admin):
    ids = {}
    for i, name in enumerate(ROSTER[:4]):
        r = client.post("/api/admin/users", headers=admin,
                        json={"email": f"s{i}@test.io", "full_name": name, "password": "password1"})
        ids[name.split()[0]] = r.json()["id"]
    return ids


def test_import_review_commit(client, admin, roster, monkeypatch):
    monkeypatch.setitem(engines.ENGINES, "tesseract",
                        lambda data: ["S1", "1) POPOVlCI MATEI", "2) DRAGOMLR IOANA", "3) Unknown Person"])
    ev = make_event(client, admin)

    r = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]},
                    files=[("files", ("list.png", png_bytes((400, 300)), "image/png"))])
    assert r.status_code == 201, r.text
    imp = r.json()
    status = {line["raw"]: (line["status"], line["user_id"]) for line in imp["lines"]}
    assert status["1) POPOVlCI MATEI"] == ("matched", roster["POPOVICI"])
    assert status["2) DRAGOMLR IOANA"][1] == roster["DRAGOMIR"]
    assert status["3) Unknown Person"][0] == "unmatched"
    assert client.get(f"/api/admin/ocr/imports/{imp['id']}/images/0", headers=admin).status_code == 200

    # admin adds STANCIU manually (no line) on top of the two matches
    entries = [{"user_id": roster["POPOVICI"], "line_index": 1},
               {"user_id": roster["DRAGOMIR"], "line_index": 2},
               {"user_id": roster["STANCIU"]}]
    r = client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin, json={"entries": entries})
    assert r.json() == {"created": 3, "skipped_existing": 0}
    again = client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin, json={"entries": entries})
    assert again.json() == {"created": 0, "skipped_existing": 3}

    atts = client.get("/api/admin/attendances", headers=admin, params={"event_id": ev["id"]}).json()["items"]
    assert len(atts) == 3 and {a["source"] for a in atts} == {"ocr"} and {a["status"] for a in atts} == {"approved"}
    assert client.get(f"/api/attendances/{atts[0]['id']}/photo", headers=admin).status_code == 200

    # a second import of the same list now reports them as already present
    r = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]},
                    files=[("files", ("list.png", png_bytes((400, 300)), "image/png"))])
    assert {line["status"] for line in r.json()["lines"] if line["user_id"]} == {"already_present"}
    briefs = client.get("/api/admin/ocr/imports", headers=admin, params={"event_id": ev["id"]}).json()
    assert [b["created_attendances"] for b in briefs] == [0, 3]


def test_import_without_event_detects_date_and_lets_admin_choose(client, admin, roster, monkeypatch):
    today = datetime.now(UTC).date()
    header = f"{today.day} {today.strftime('%b')}  S1"
    monkeypatch.setitem(engines.ENGINES, "tesseract", lambda data: [header, "1) POPOVICI MATEI", "2) STANCIU RADU"])
    files = [("files", ("list.png", png_bytes((400, 300)), "image/png"))]

    # no event on that date yet: date detected, nothing pre-selected, commit needs a choice
    r = client.post("/api/admin/ocr/imports", headers=admin, files=files, data={"tz": "UTC"})
    imp = r.json()
    assert imp["detected_date"] == today.isoformat() and imp["date_text"].startswith(str(today.day))
    assert imp["event_id"] is None and imp["suggested_events"] == []
    entries = [{"user_id": roster["POPOVICI"], "line_index": 1}]
    assert client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin,
                       json={"entries": entries}).status_code == 422

    # two events that day (two sessions): suggested, but the admin has to pick
    a = make_event(client, admin, start_offset_min=-5, title="Session 1")
    b = make_event(client, admin, start_offset_min=-4, title="Session 2")
    r = client.post("/api/admin/ocr/imports", headers=admin, files=files, data={"tz": "UTC"})
    imp = r.json()
    assert imp["event_id"] is None and {e["id"] for e in imp["suggested_events"]} >= {a["id"], b["id"]}

    # choosing an event re-matches with that event's context, then commit to it
    client.post("/api/attendances", headers=auth_headers_for(client, "s2@test.io"),
                data={"event_id": a["id"], "activity_summary": "here", "declaration": "true"},
                files={"photo": ("p.png", png_bytes(), "image/png")})
    imp = client.patch(f"/api/admin/ocr/imports/{imp['id']}", headers=admin, json={"event_id": a["id"]}).json()
    st = {line["raw"]: line["status"] for line in imp["lines"]}
    assert imp["event_id"] == a["id"] and st["2) STANCIU RADU"] == "already_present"
    r = client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin, json={"entries": entries})
    assert r.json()["created"] == 1

    # the same sheet's second session can go to the other event
    r = client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin,
                    json={"event_id": b["id"], "entries": [{"user_id": roster["STANCIU"], "line_index": 2}]})
    assert r.json()["created"] == 1


def auth_headers_for(client, email):
    from tests.conftest import auth_headers
    return auth_headers(client, email, "password1")


def test_summary_and_source_filter(client, admin, roster, monkeypatch):
    monkeypatch.setitem(engines.ENGINES, "tesseract", lambda data: ["POPOVICI MATEI"])
    ev = make_event(client, admin)
    client.post("/api/attendances", headers=auth_headers_for(client, "s1@test.io"),
                data={"event_id": ev["id"], "activity_summary": "here", "declaration": "true"},
                files={"photo": ("p.png", png_bytes(), "image/png")})
    imp = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]},
                      files=[("files", ("l.png", png_bytes(), "image/png"))]).json()
    client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin,
                json={"entries": [{"user_id": roster["POPOVICI"], "line_index": 0}]})

    assert client.get("/api/admin/attendances", headers=admin, params={"source": "ocr"}).json()["total"] == 1
    assert client.get("/api/admin/attendances", headers=admin, params={"source": "self"}).json()["total"] == 1
    s = client.get("/api/admin/attendances/summary", headers=admin).json()
    assert s["total"] == 2 and s["by_source"] == {"ocr": 1, "self": 1}
    assert s["by_status"] == {"approved": 1, "pending": 1}
    assert s["per_event"][0]["count"] == 2 and s["per_event"][0]["from_lists"] == 1
    assert s["per_event"][0]["expected"] == 4
    only_ocr = client.get("/api/admin/attendances/summary", headers=admin, params={"source": "ocr"}).json()
    assert only_ocr["total"] == 1 and only_ocr["top_users"][0]["user_id"] == roster["POPOVICI"]


def test_find_date():
    from datetime import date
    from app.ocr.dates import find_date
    today = date(2026, 10, 27)
    assert find_date(["26 Oct      S1"], today) == (date(2026, 10, 26), "26 Oct      S1")
    assert find_date(["3 martie 2025"], today)[0] == date(2025, 3, 3)
    assert find_date(["Lista 26.10.2026"], today)[0] == date(2026, 10, 26)
    assert find_date(["15 Dec"], today)[0] == date(2025, 12, 15)  # no year: most recent past one
    assert find_date(["0,75", "1) MARIA OCTAVIAN"], today) == (None, "")


def test_import_requires_admin_and_engine(client, admin, user, monkeypatch):
    ev = make_event(client, admin)
    files = [("files", ("list.png", png_bytes(), "image/png"))]
    assert client.post("/api/admin/ocr/imports", headers=user, data={"event_id": ev["id"]}, files=files).status_code == 403

    def unavailable(data):
        raise engines.EngineUnavailable("no tesseract")
    monkeypatch.setitem(engines.ENGINES, "tesseract", unavailable)
    r = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]}, files=files)
    assert r.status_code == 503 and "no tesseract" in r.json()["detail"]
    r = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]},
                    files=[("files", ("x.png", b"not an image", "image/png"))])
    assert r.status_code == 422


def test_azure_engine_parses_response(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "azure_openai_endpoint", "https://example.openai.azure.com")
    monkeypatch.setattr(s, "azure_openai_api_key", "k")
    monkeypatch.setattr(s, "azure_openai_deployment", "vision")

    class Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": '{"names": ["Radu Stanciu", " ", "Omar Hassan"]}'}}]}

    calls = {}
    def fake_post(url, json, headers, timeout):
        calls.update(url=url, headers=headers, body=json)
        return Resp()
    monkeypatch.setattr(engines.httpx, "post", fake_post)
    assert engines.azure_lines(b"img") == ["Radu Stanciu", "Omar Hassan"]
    assert "/openai/deployments/vision/chat/completions" in calls["url"] and calls["headers"]["api-key"] == "k"


@pytest.mark.skipif(engines.tesseract_cmd() is None, reason="Tesseract not installed")
def test_tesseract_reads_printed_list():
    img = Image.new("RGB", (1400, 700), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    for i, name in enumerate(["1) STANCIU RADU", "2) HASSAN OMAR", "3) BARBU TEODORA"]):
        draw.text((80, 80 + i * 150), name, fill=(20, 40, 160), font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    lines = engines.tesseract_lines(buf.getvalue())
    results = match_lines([(0, line) for line in lines], CANDIDATES)
    assert {r.user_id for r in results if r.status == "matched"} == {
        ID["STANCIU Radu"], ID["HASSAN Omar"], ID["BARBU Teodora-Ioana"]}


def test_summary_rates_trend_and_series(client, admin):
    """3 students: Ana & Bo in group A, Cy in group B. Past events: E1 (everyone), E2 (A only),
    and a 2-occurrence daily series E3a/E3b (everyone)."""
    from tests.conftest import auth_headers
    now = datetime.now(UTC)
    uid = {}
    for name in ("ANA X. Ana", "BO X. Bo", "CY X. Cy"):
        email = name.split()[0].lower() + "@test.io"
        uid[name.split()[0]] = client.post("/api/admin/users", headers=admin, json={
            "email": email, "full_name": name, "password": "password1"}).json()["id"]
    ga = client.post("/api/admin/groups", headers=admin, json={"name": "A", "member_ids": [uid["ANA"], uid["BO"]]}).json()
    client.post("/api/admin/groups", headers=admin, json={"name": "B", "member_ids": [uid["CY"]]})

    def past(title, days_ago, **extra):
        start = now - timedelta(days=days_ago, hours=1)
        return client.post("/api/events", headers=admin, json={
            "title": title, "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=2)).isoformat(),
            "check_in_closes_at": (now + timedelta(hours=1)).isoformat(), **extra}).json()
    e1 = past("E1", 3)[0]
    e2 = past("E2", 2, group_ids=[ga["id"]])[0]
    series = past("E3", 1, recurrence={"frequency": "daily", "interval": 2, "count": 2})  # 2nd is in the future
    e3a = series[0]

    def attend(user, ev):
        h = auth_headers(client, user.lower() + "@test.io", "password1")
        r = client.post("/api/attendances", headers=h, data={"event_id": ev["id"], "activity_summary": "here",
                                                              "declaration": "true"},
                        files={"photo": ("p.png", png_bytes(), "image/png")})
        assert r.status_code == 201, r.text
    for u, ev in [("ANA", e1), ("ANA", e2), ("ANA", e3a), ("BO", e1), ("CY", e3a)]:
        attend(u, ev)

    s = client.get("/api/admin/attendances/summary", headers=admin, params={"granularity": "day", "tz": "UTC"}).json()
    # past events in scope: E1 (3 expected, 2 here), E2 (2 expected, 1), E3a (3 expected, 2)
    assert s["events_in_scope"] == 3
    assert abs(s["avg_turnout"] - (2 / 3 + 1 / 2 + 2 / 3) / 3) < 1e-3
    rate = {r["full_name"]: (r["attended"], r["expected"]) for r in s["students_high"]}
    assert rate == {"ANA X. Ana": (3, 3), "BO X. Bo": (1, 3), "CY X. Cy": (1, 2)}
    assert s["students_low"][0]["full_name"] == "BO X. Bo" and s["at_risk"] == 1
    groups = {g["group"]: (g["attended"], g["expected"]) for g in s["group_rates"]}
    assert groups == {"A": (4, 6), "B": (1, 2)}
    assert sum(p["self"] for p in s["trend"]) == 5 and len(s["trend"]) == 3  # one bucket per day
    assert sum(s["by_weekday"]) == 5

    # series filter narrows both volumes and rates to that recurring event
    s = client.get("/api/admin/attendances/summary", headers=admin, params={"series_id": e3a["series_id"]}).json()
    assert s["total"] == 2 and s["events_in_scope"] == 1
    # group filter narrows the students considered
    s = client.get("/api/admin/attendances/summary", headers=admin, params={"group_id": ga["id"]}).json()
    assert {r["full_name"] for r in s["students_high"]} == {"ANA X. Ana", "BO X. Bo"}


def test_add_images_to_existing_import(client, admin, roster, monkeypatch):
    ev = make_event(client, admin)
    pages = iter([["1) POPOVICI MATEI", "2) Unknown Person"], ["3) POPOVICI MATEI", "4) DRAGOMIR IOANA"]])
    monkeypatch.setitem(engines.ENGINES, "tesseract", lambda data: next(pages))
    imp = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]},
                      files=[("files", ("p1.png", png_bytes(), "image/png"))]).json()
    r = client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin,
                    json={"entries": [{"user_id": roster["POPOVICI"], "line_index": 0}]})
    assert r.json()["created"] == 1

    # the second page arrives later: lines are appended, old indexes unchanged
    r = client.post(f"/api/admin/ocr/imports/{imp['id']}/images", headers=admin,
                    files=[("files", ("p2.png", png_bytes((300, 200)), "image/png"))])
    assert r.status_code == 200, r.text
    imp = r.json()
    assert imp["image_count"] == 2
    by_raw = {l["raw"]: l for l in imp["lines"]}
    assert [l["raw"] for l in imp["lines"]][:2] == ["1) POPOVICI MATEI", "2) Unknown Person"]
    assert by_raw["1) POPOVICI MATEI"]["status"] == "already_present"
    assert by_raw["3) POPOVICI MATEI"]["status"] == "duplicate"  # same person on page 2
    new = by_raw["4) DRAGOMIR IOANA"]
    assert new["status"] == "matched" and new["image_index"] == 1 and new["user_id"] == roster["DRAGOMIR"]

    r = client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin,
                    json={"entries": [{"user_id": new["user_id"], "line_index": new["index"]}]})
    assert r.json() == {"created": 1, "skipped_existing": 0}
    assert client.get(f"/api/admin/ocr/imports/{imp['id']}/images/1", headers=admin).status_code == 200
    # the new attendance's evidence is the second photo
    atts = client.get("/api/admin/attendances", headers=admin, params={"user_id": roster["DRAGOMIR"]}).json()["items"]
    assert "DRAGOMIR IOANA" in atts[0]["activity_summary"]


def test_delete_attendance(client, admin, roster, monkeypatch):
    from app.models import Attendance
    from app.db import SessionLocal
    from app.storage import photo_abspath
    ev = make_event(client, admin)

    # self check-in: record and its own photo are removed
    h = auth_headers_for(client, "s2@test.io")
    att = client.post("/api/attendances", headers=h, files={"photo": ("p.png", png_bytes(), "image/png")},
                      data={"event_id": ev["id"], "activity_summary": "here", "declaration": "true"}).json()
    with SessionLocal() as db:
        own_photo = photo_abspath(db.get(Attendance, att["id"]).photo_path)
    assert own_photo.exists()
    assert client.delete(f"/api/admin/attendances/{att['id']}", headers=h).status_code == 403
    assert client.delete(f"/api/admin/attendances/{att['id']}", headers=admin).status_code == 204
    assert not own_photo.exists()
    assert client.delete(f"/api/admin/attendances/{att['id']}", headers=admin).status_code == 404
    # the student can check in again afterwards
    again = client.post("/api/attendances", headers=h, files={"photo": ("p.png", png_bytes(), "image/png")},
                        data={"event_id": ev["id"], "activity_summary": "here", "declaration": "true"})
    assert again.status_code == 201

    # paper list: the shared list photo survives deleting one of its students
    monkeypatch.setitem(engines.ENGINES, "tesseract", lambda data: ["POPOVICI MATEI", "DRAGOMIR IOANA"])
    imp = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]},
                      files=[("files", ("l.png", png_bytes(), "image/png"))]).json()
    client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin, json={"entries": [
        {"user_id": roster["POPOVICI"], "line_index": 0}, {"user_id": roster["DRAGOMIR"], "line_index": 1}]})
    items = client.get("/api/admin/attendances", headers=admin, params={"source": "ocr"}).json()["items"]
    assert client.delete(f"/api/admin/attendances/{items[0]['id']}", headers=admin).status_code == 204
    assert client.get(f"/api/attendances/{items[1]['id']}/photo", headers=admin).status_code == 200
    assert client.get(f"/api/admin/ocr/imports/{imp['id']}/images/0", headers=admin).status_code == 200


def _saved_import(client, admin, roster, monkeypatch, ev):
    monkeypatch.setitem(engines.ENGINES, "tesseract", lambda data: ["POPOVICI MATEI", "DRAGOMIR IOANA"])
    imp = client.post("/api/admin/ocr/imports", headers=admin, data={"event_id": ev["id"]},
                      files=[("files", ("l.png", png_bytes(), "image/png"))]).json()
    client.post(f"/api/admin/ocr/imports/{imp['id']}/commit", headers=admin, json={"entries": [
        {"user_id": roster["POPOVICI"], "line_index": 0}, {"user_id": roster["DRAGOMIR"], "line_index": 1}]})
    return client.get(f"/api/admin/ocr/imports/{imp['id']}", headers=admin).json()


def test_delete_import_keeping_or_deleting_attendances(client, admin, roster, monkeypatch):
    ev = make_event(client, admin)
    imp = _saved_import(client, admin, roster, monkeypatch, ev)
    assert imp["created_attendances"] == 2

    # keep: the records stay, still showing the list photo
    assert client.delete(f"/api/admin/ocr/imports/{imp['id']}", headers=admin).status_code == 204
    assert client.get(f"/api/admin/ocr/imports/{imp['id']}", headers=admin).status_code == 404
    items = client.get("/api/admin/attendances", headers=admin, params={"source": "ocr"}).json()["items"]
    assert len(items) == 2
    assert client.get(f"/api/attendances/{items[0]['id']}/photo", headers=admin).status_code == 200

    # delete: a second list for another event takes its records and its photo with it
    ev2 = make_event(client, admin)
    imp2 = _saved_import(client, admin, roster, monkeypatch, ev2)
    from app.db import SessionLocal
    from app.models import OcrImport
    from app.storage import photo_abspath
    import json as _json
    with SessionLocal() as db:
        photo = photo_abspath(_json.loads(db.get(OcrImport, imp2["id"]).image_paths)[0])
    r = client.delete(f"/api/admin/ocr/imports/{imp2['id']}", headers=admin, params={"delete_attendances": "true"})
    assert r.status_code == 204
    assert client.get("/api/admin/attendances", headers=admin, params={"event_id": ev2["id"]}).json()["total"] == 0
    assert not photo.exists()


def test_delete_event_keeps_list_import(client, admin, roster, monkeypatch):
    ev = make_event(client, admin)
    imp = _saved_import(client, admin, roster, monkeypatch, ev)
    assert client.delete(f"/api/events/{ev['id']}", headers=admin).status_code == 204
    assert client.get("/api/admin/attendances", headers=admin).json()["total"] == 0
    kept = client.get(f"/api/admin/ocr/imports/{imp['id']}", headers=admin).json()
    assert kept["event_id"] is None and kept["created_attendances"] == 0
    # the list photo survived even though every attendance using it was deleted
    assert client.get(f"/api/admin/ocr/imports/{imp['id']}/images/0", headers=admin).status_code == 200
