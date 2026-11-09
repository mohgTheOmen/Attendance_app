from tests.conftest import auth_headers


def create_user(client, admin, email, name):
    response = client.post(
        "/api/admin/users", headers=admin,
        json={"email": email, "full_name": name, "password": "studentpass123"},
    )
    assert response.status_code == 201, response.text
    return response.json(), auth_headers(client, email, "studentpass123")


def test_professor_publishes_to_everyone(client, admin, user):
    created = client.post("/api/newsletters", headers=admin, json={
        "subject": "Exam preparation",
        "body": "Please review chapters 4 and 5.",
        "audience_all": True,
    })
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["audience_all"] is True
    assert item["group"] is None
    assert item["creator"]["email"] == "admin@test.io"
    assert item["messages"][0]["body"] == "Please review chapters 4 and 5."
    assert [n["id"] for n in client.get("/api/newsletters", headers=user).json()] == [item["id"]]


def test_only_professors_can_publish_or_reply(client, admin, user):
    denied = client.post("/api/newsletters", headers=user, json={
        "subject": "Student announcement", "body": "Not allowed", "audience_all": True,
    })
    assert denied.status_code == 403
    item = client.post("/api/newsletters", headers=admin, json={
        "subject": "Read only", "body": "Official announcement", "audience_all": True,
    }).json()
    reply = client.post(
        f"/api/newsletters/{item['id']}/messages", headers=user, json={"body": "A reply"}
    )
    assert reply.status_code == 405


def test_group_newsletter_is_only_visible_to_members(client, admin, user):
    _, bob_headers = create_user(client, admin, "bob@test.io", "Bob")
    jane_id = client.get("/api/auth/me", headers=user).json()["id"]
    group = client.post("/api/admin/groups", headers=admin, json={
        "name": "Group A", "member_ids": [jane_id]
    }).json()
    created = client.post("/api/newsletters", headers=admin, json={
        "subject": "Room change", "body": "Tomorrow we meet in room 204.", "group_id": group["id"]
    })
    assert created.status_code == 201
    item = created.json()
    assert item["audience_all"] is False and item["group"]["name"] == "Group A"
    assert client.get(f"/api/newsletters/{item['id']}", headers=user).status_code == 200
    assert client.get(f"/api/newsletters/{item['id']}", headers=bob_headers).status_code == 404


def test_newsletter_requires_everyone_or_group(client, admin):
    response = client.post("/api/newsletters", headers=admin, json={
        "subject": "Missing audience", "body": "No audience selected"
    })
    assert response.status_code == 422
