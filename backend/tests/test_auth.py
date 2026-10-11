"""The three demo logins and what each one is allowed to do."""
from conftest import login_as


def test_login_required(client):
    assert client.get("/api/problems", headers={"Authorization": ""}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "lead", "password": "nope"}).status_code == 401
    acc = client.get("/api/auth/accounts", headers={"Authorization": ""}).json()
    assert {a["username"] for a in acc["staff"]} == {"coordinator", "lead"}
    assert acc["default_doctor"] == "okafor"


def test_roles_are_enforced(client):
    coord, lead, doc = login_as(client, "coordinator"), login_as(client, "lead"), login_as(client, "okafor")
    o = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"}, headers=lead)
    assert o.status_code == 403  # the lead approves, the coordinator proposes
    o = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"}, headers=coord).json()
    assert o["proposed_by"] == "Ops Coordinator"
    assert client.post(f"/api/offers/{o['id']}/approve", json={}, headers=coord).status_code == 403
    assert client.post(f"/api/offers/{o['id']}/approve", json={}, headers=doc).status_code == 403
    r = client.post(f"/api/offers/{o['id']}/approve", json={}, headers=lead).json()
    assert r["approved_by"] == "Clinical Lead on Duty"
    assert client.get("/api/problems", headers=doc).status_code == 403  # doctors see only their offers
    mine = client.get("/api/offers", headers=doc).json()
    assert [x["id"] for x in mine["offers"]] == [o["id"]] and mine["escalations"] == []
    other = login_as(client, "menon")
    assert client.get("/api/offers", headers=other).json()["offers"] == []
    assert client.post(f"/api/offers/{o['id']}/respond", json={"action": "accept"}, headers=other).status_code == 403
    assert client.post(f"/api/offers/{o['id']}/respond", json={"action": "accept"}, headers=coord).status_code == 403
    assert client.post(f"/api/offers/{o['id']}/respond", json={"action": "accept"}, headers=doc).json()["status"] == "accepted"
