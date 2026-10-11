"""Two plans per problem; the coordinator sends one to the clinical lead, who approves and it runs."""
from conftest import login_as


def _problem(client, pid):
    return next(p for p in client.get("/api/problems").json()["problems"] if p["id"] == pid)


def test_problems_offer_two_plans(client):
    p = _problem(client, "c:CON-2105")
    assert [x["key"] for x in p["plans"]] == ["A", "B"]
    assert p["plans"][0]["kind"] == "split_shift" and p["plans"][0]["recommended"]
    assert p["plans"][1]["kind"] in ("assign", "escalate")
    assert all(x["approver"] == "Clinical lead" for x in p["plans"])


def test_send_plan_a_lead_approves_and_offer_is_sent(client):
    coord, lead = login_as(client, "coordinator"), login_as(client, "lead")
    r = client.post("/api/problems/c:CON-2105/plans", json={"plan": "A"}, headers=coord)
    assert r.status_code == 200
    assert client.post("/api/problems/c:CON-2105/plans", json={"plan": "B"}, headers=coord).status_code == 409
    assert _problem(client, "c:CON-2105")["status"]["state"] == "plan_pending"
    plid = r.json()["id"]
    assert client.post(f"/api/plans/{plid}/approve", json={}, headers=coord).status_code == 403
    done = client.post(f"/api/plans/{plid}/approve", json={}, headers=lead).json()
    assert done["status"] == "done"
    offers = client.get("/api/offers").json()["offers"]
    assert offers[0]["status"] == "sent" and offers[0]["approved_by"] == "Clinical Lead on Duty"


def test_plan_b_escalate_and_reject(client):
    coord, lead = login_as(client, "coordinator"), login_as(client, "lead")
    p = _problem(client, "c:CON-2110")
    b = p["plans"][1]
    plid = client.post("/api/problems/c:CON-2110/plans", json={"plan": "B"}, headers=coord).json()["id"]
    r = client.post(f"/api/plans/{plid}/reject", json={"note": "Try A"}, headers=lead).json()
    assert r["status"] == "rejected"
    st = _problem(client, "c:CON-2110")["status"]
    assert st["state"] == "plan_rejected" and "Try A" in st["label"]
    plid = client.post("/api/problems/c:CON-2110/plans", json={"plan": "A"}, headers=coord).json()["id"]
    assert client.post(f"/api/plans/{plid}/approve", json={}, headers=lead).json()["status"] in ("done", "failed")
