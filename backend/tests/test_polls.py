"""Voting rules, aggregate-only responses, and PostgreSQL race regressions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.main import app
from app.models import PollVote
from tests.conftest import auth_headers


def student_id(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["id"]


def make_group(client, admin, members=(), name="Voting group"):
    r = client.post("/api/admin/groups", headers=admin,
                    json={"name": name, "member_ids": list(members)})
    assert r.status_code == 201, r.text
    return r.json()


def make_poll(client, admin, groups, **extra):
    r = client.post("/api/polls", headers=admin, json={
        "subject": "Next lab topic", "options": ["Cloud", "Web"],
        "group_ids": [g["id"] for g in groups], **extra,
    })
    assert r.status_code == 201, r.text
    return r.json()


def eligible_poll(client, admin, user):
    group = make_group(client, admin, [student_id(client, user)])
    return make_poll(client, admin, [group])


def vote(client, headers, poll, option=0):
    return client.post(f"/api/polls/{poll['id']}/votes", headers=headers,
                       json={"option_id": poll["options"][option]["id"]})


def assert_aggregate_only(poll):
    # Exact response keys prevent accidental leakage of participation rows,
    # identities, and per-student choices to either role.
    assert set(poll) == {
        "id", "subject", "is_open", "created_at", "groups", "options",
        "total_votes", "has_voted",
    }
    for group in poll["groups"]:
        assert set(group) == {"id", "name"}
    for option in poll["options"]:
        assert set(option) == {"id", "label", "vote_count"}
    assert poll["total_votes"] == sum(o["vote_count"] for o in poll["options"])


def test_poll_lifecycle_aggregate_results_and_immutable_vote(client, admin, user):
    poll = eligible_poll(client, admin, user)
    assert poll["is_open"] is True
    assert poll["total_votes"] == 0
    assert poll["has_voted"] is False
    assert_aggregate_only(poll)

    visible = client.get("/api/polls", headers=user).json()
    assert [p["id"] for p in visible] == [poll["id"]]
    assert_aggregate_only(visible[0])

    accepted = vote(client, user, poll)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["has_voted"] is True
    assert accepted.json()["total_votes"] == 1
    assert_aggregate_only(accepted.json())
    assert vote(client, user, poll).status_code == 409
    assert vote(client, user, poll, option=1).status_code == 409

    for headers in (admin, user):
        result = client.get("/api/polls", headers=headers).json()[0]
        assert_aggregate_only(result)
        assert result["total_votes"] == 1
        assert [o["vote_count"] for o in result["options"]] == [1, 0]
        assert result["has_voted"] is (headers == user)

    closed = client.post(f"/api/polls/{poll['id']}/close", headers=admin)
    assert closed.status_code == 200, closed.text
    assert closed.json()["is_open"] is False
    # Closing again is harmless and never reopens a poll.
    assert client.post(f"/api/polls/{poll['id']}/close", headers=admin).json()["is_open"] is False
    after_close = client.get("/api/polls", headers=user).json()[0]
    assert after_close["is_open"] is False
    assert after_close["total_votes"] == 1


def test_poll_permissions_and_group_membership_checked_on_vote(client, admin, user):
    uid = student_id(client, user)
    group = make_group(client, admin, [uid])
    poll = make_poll(client, admin, [group])
    body = {"subject": "Unauthorized", "options": ["A", "B"], "group_ids": [group["id"]]}
    assert client.get("/api/polls").status_code == 401
    assert client.post("/api/polls", json=body).status_code == 401
    assert client.post("/api/polls", headers=user, json=body).status_code == 403
    assert client.post(f"/api/polls/{poll['id']}/close", headers=user).status_code == 403
    assert vote(client, admin, poll).status_code == 403

    # Removing membership after the poll was loaded must block its submission.
    assert client.patch(f"/api/admin/groups/{group['id']}", headers=admin,
                        json={"member_ids": []}).status_code == 200
    assert client.get("/api/polls", headers=user).json() == []
    assert vote(client, user, poll).status_code == 404
    assert client.get("/api/polls", headers=admin).json()[0]["total_votes"] == 0


def test_group_audience_is_union_and_other_students_are_excluded(client, admin, user):
    empty = make_group(client, admin, name="Other group")
    member = make_group(client, admin, [student_id(client, user)])
    hidden = make_poll(client, admin, [empty], subject="Other audience")
    visible = make_poll(client, admin, [empty, member])
    assert [p["id"] for p in client.get("/api/polls", headers=user).json()] == [visible["id"]]
    assert vote(client, user, hidden).status_code == 404
    assert vote(client, user, visible).status_code == 201


@pytest.mark.parametrize("change", [
    {"subject": "   "},
    {"subject": ""},
    {"options": []},
    {"options": ["Only one"]},
    {"options": ["Yes", "   "]},
    {"options": [" Yes ", "yes"]},
    {"group_ids": []},
    {"group_ids": [987654321]},
])
def test_invalid_poll_is_not_created(client, admin, change):
    group = make_group(client, admin)
    body = {"subject": "Subject", "options": ["Yes", "No"], "group_ids": [group["id"]], **change}
    r = client.post("/api/polls", headers=admin, json=body)
    assert r.status_code == 422, r.text
    assert client.get("/api/polls", headers=admin).json() == []


def test_poll_text_is_trimmed(client, admin):
    group = make_group(client, admin)
    poll = make_poll(client, admin, [group], subject="  Subject  ", options=[" Yes ", " No "])
    assert poll["subject"] == "Subject"
    assert [o["label"] for o in poll["options"]] == ["Yes", "No"]


def test_wrong_poll_option_and_closed_poll_reject_votes(client, admin, user):
    group = make_group(client, admin, [student_id(client, user)])
    first = make_poll(client, admin, [group])
    second = make_poll(client, admin, [group])
    for invalid in (second["options"][0]["id"], 987654321):
        r = client.post(f"/api/polls/{first['id']}/votes", headers=user, json={"option_id": invalid})
        assert r.status_code == 422, r.text
    assert client.post(f"/api/polls/{first['id']}/close", headers=admin).status_code == 200
    assert vote(client, user, first).status_code == 409
    assert all(p["total_votes"] == 0 for p in client.get("/api/polls", headers=admin).json())
    assert client.post("/api/polls/987654321/close", headers=admin).status_code == 404
    assert client.post("/api/polls/987654321/votes", headers=user,
                       json={"option_id": first["options"][0]["id"]}).status_code == 404


def test_inactive_student_cannot_vote_or_read_results(client, admin, user):
    poll = eligible_poll(client, admin, user)
    uid = student_id(client, user)
    assert client.patch(f"/api/admin/users/{uid}", headers=admin,
                        json={"is_active": False}).status_code == 200
    assert vote(client, user, poll).status_code == 401
    assert client.get("/api/polls", headers=user).status_code == 401
    assert client.get("/api/polls", headers=admin).json()[0]["total_votes"] == 0


def test_deleting_last_eligible_group_does_not_make_poll_public(client, admin, user):
    group = make_group(client, admin, [student_id(client, user)])
    poll = make_poll(client, admin, [group])
    assert client.delete(f"/api/admin/groups/{group['id']}", headers=admin).status_code == 204
    assert client.get("/api/polls", headers=user).json() == []
    assert vote(client, user, poll).status_code == 404
    remaining = client.get("/api/polls", headers=admin).json()
    assert remaining[0]["id"] == poll["id"]
    assert remaining[0]["groups"] == []


def test_database_itself_rejects_a_second_vote(client, admin, user):
    poll = eligible_poll(client, admin, user)
    assert vote(client, user, poll).status_code == 201
    with SessionLocal() as db:
        db.add(PollVote(poll_id=poll["id"], user_id=student_id(client, user),
                        option_id=poll["options"][1]["id"]))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    assert client.get("/api/polls", headers=admin).json()[0]["total_votes"] == 1


def test_distinct_students_each_get_one_vote_in_each_poll(client, admin, user):
    enrolled = client.post("/api/admin/users", headers=admin, json={
        "email": "bob.vote@test.io", "full_name": "Bob Voter", "password": "bobpass123"})
    assert enrolled.status_code == 201
    bob = auth_headers(client, "bob.vote@test.io", "bobpass123")
    group = make_group(client, admin, [student_id(client, user), enrolled.json()["id"]])
    first = make_poll(client, admin, [group])
    second = make_poll(client, admin, [group])
    assert vote(client, user, first).status_code == 201
    assert vote(client, bob, first, option=1).status_code == 201
    assert vote(client, bob, first).status_code == 409
    assert vote(client, user, second).status_code == 201
    by_id = {p["id"]: p for p in client.get("/api/polls", headers=admin).json()}
    assert by_id[first["id"]]["total_votes"] == 2
    assert [o["vote_count"] for o in by_id[first["id"]]["options"]] == [1, 1]
    assert by_id[second["id"]]["total_votes"] == 1
    assert_aggregate_only(by_id[first["id"]])


def test_other_class_student_cannot_vote_by_known_id_or_spoofed_identity(client, admin, user):
    jane_id = student_id(client, user)
    enrolled = client.post("/api/admin/users", headers=admin, json={
        "email": "outsider@test.io", "full_name": "Other Class Student", "password": "outsider123"})
    assert enrolled.status_code == 201
    outsider_id = enrolled.json()["id"]
    outsider = auth_headers(client, "outsider@test.io", "outsider123")
    selected_class = make_group(client, admin, [jane_id], name="Selected class")
    make_group(client, admin, [outsider_id], name="Different class")
    poll = make_poll(client, admin, [selected_class])

    assert client.get("/api/polls", headers=outsider).json() == []
    assert vote(client, outsider, poll).status_code == 404
    # A request body cannot impersonate an eligible student. The server must
    # derive the voter exclusively from the authenticated account.
    spoofed = client.post(f"/api/polls/{poll['id']}/votes", headers=outsider, json={
        "option_id": poll["options"][0]["id"], "user_id": jane_id})
    assert spoofed.status_code == 404, spoofed.text
    result = client.get("/api/polls", headers=admin).json()[0]
    assert result["total_votes"] == 0
    assert result["has_voted"] is False
    assert client.get("/api/polls", headers=user).json()[0]["has_voted"] is False


def test_multiple_admin_polls_are_shared_by_all_eligible_students(client, admin, user):
    enrolled = client.post("/api/admin/users", headers=admin, json={
        "email": "classmate@test.io", "full_name": "Classmate", "password": "classmate123"})
    assert enrolled.status_code == 201
    classmate = auth_headers(client, "classmate@test.io", "classmate123")
    group = make_group(client, admin, [student_id(client, user), enrolled.json()["id"]])
    polls = [make_poll(client, admin, [group], subject=subject)
             for subject in ("Lab topic", "Meeting time", "Project choice")]
    expected_ids = {poll["id"] for poll in polls}
    for headers in (admin, user, classmate):
        visible = client.get("/api/polls", headers=headers).json()
        assert {poll["id"] for poll in visible} == expected_ids
        assert all(poll["total_votes"] == 0 for poll in visible)

    shared = polls[0]
    assert vote(client, user, shared).status_code == 201
    jane_view = {p["id"]: p for p in client.get("/api/polls", headers=user).json()}[shared["id"]]
    classmate_view = {p["id"]: p for p in client.get("/api/polls", headers=classmate).json()}[shared["id"]]
    admin_view = {p["id"]: p for p in client.get("/api/polls", headers=admin).json()}[shared["id"]]
    assert jane_view["has_voted"] is True
    assert classmate_view["has_voted"] is False
    for view in (jane_view, classmate_view, admin_view):
        assert view["id"] == shared["id"]
        assert view["total_votes"] == 1
        assert view["options"] == jane_view["options"]
        assert_aggregate_only(view)

    assert vote(client, classmate, shared, option=1).status_code == 201
    for headers in (admin, user, classmate):
        result = {p["id"]: p for p in client.get("/api/polls", headers=headers).json()}[shared["id"]]
        assert result["total_votes"] == 2
        assert [option["vote_count"] for option in result["options"]] == [1, 1]


def test_vote_cannot_be_repeated_after_logout_and_login_in_another_client(client, admin, user):
    poll = eligible_poll(client, admin, user)
    assert vote(client, user, poll).status_code == 201
    assert client.post("/api/auth/logout", headers=user).status_code == 204
    assert vote(client, user, poll).status_code == 401

    independent = TestClient(app)
    try:
        new_session = auth_headers(independent, "jane@test.io", "janepass123")
        assert new_session != user
        assert independent.get("/api/polls", headers=new_session).json()[0]["has_voted"] is True
        assert vote(independent, new_session, poll, option=1).status_code == 409
        assert vote(independent, new_session, poll).status_code == 409
    finally:
        independent.close()
    result = client.get("/api/polls", headers=admin).json()[0]
    assert result["total_votes"] == 1
    assert [option["vote_count"] for option in result["options"]] == [1, 0]


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL transaction race regression")
def test_simultaneous_submissions_count_exactly_one_vote(client, admin, user):
    poll = eligible_poll(client, admin, user)
    barrier = Barrier(2)

    def submit_independently(option):
        # Separate clients and request-scoped database sessions, sharing only
        # credentials, simulate two tabs submitting different choices at once.
        independent = TestClient(app)
        try:
            barrier.wait(timeout=10)
            return vote(independent, user, poll, option).status_code
        finally:
            independent.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit_independently, (0, 1)))
    assert sorted(results) == [201, 409]
    result = client.get("/api/polls", headers=user).json()[0]
    assert result["has_voted"] is True
    assert result["total_votes"] == 1
    assert sorted(o["vote_count"] for o in result["options"]) == [0, 1]


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL transaction race regression")
def test_simultaneous_close_and_vote_have_serialized_outcome(client, admin, user):
    poll = eligible_poll(client, admin, user)
    barrier = Barrier(2)

    def request_independently(action):
        independent = TestClient(app)
        try:
            barrier.wait(timeout=10)
            if action == "close":
                return independent.post(f"/api/polls/{poll['id']}/close", headers=admin).status_code
            return vote(independent, user, poll).status_code
        finally:
            independent.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        closed, submitted = list(pool.map(request_independently, ("close", "vote")))
    assert closed == 200
    assert submitted in (201, 409)
    result = client.get("/api/polls", headers=admin).json()[0]
    assert result["is_open"] is False
    assert result["total_votes"] == (1 if submitted == 201 else 0)
    assert vote(client, user, poll).status_code == 409
