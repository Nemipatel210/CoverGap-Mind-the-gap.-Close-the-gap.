"""No reply within a minute -> AI-assisted call to the doctor (simulated, same approved offer content)."""
from conftest import login_as


def _sent_offer(client):
    o = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"}).json()
    client.post(f"/api/offers/{o['id']}/approve", json={})
    return o["id"]


def test_call_starts_after_one_minute_on_demo_clock(client):
    oid = _sent_offer(client)
    o = next(x for x in client.get("/api/offers").json()["offers"] if x["id"] == oid)
    assert not o.get("call")
    client.post("/api/clock", json={"action": "advance", "minutes": 1})
    o = next(x for x in client.get("/api/offers").json()["offers"] if x["id"] == oid)
    assert o["call"]["status"] == "ringing"
    script = " ".join(o["call"]["script"]["intro"])
    assert "Suncrest" in script and "CON-" not in script and "stroke" not in script.lower()
    notes = client.get("/api/notifications", params={"audience": "coordinator"}).json()["notifications"]
    assert any(n["kind"] == "call" for n in notes)


def test_doctor_answers_and_accepts_on_the_call(client):
    oid = _sent_offer(client)
    client.put("/api/config/assumptions", json={"ai_call_after_sec": 0})
    doc = login_as(client, "okafor")
    o = next(x for x in client.get("/api/offers", headers=doc).json()["offers"] if x["id"] == oid)
    assert o["call"]["status"] == "ringing"
    assert client.post(f"/api/offers/{oid}/call", json={"action": "answer"}, headers=doc).json()["call"]["status"] == "in_progress"
    client.post(f"/api/offers/{oid}/call", json={"action": "say", "text": "yes"}, headers=doc)
    r = client.post(f"/api/offers/{oid}/respond", json={"action": "accept", "channel": "ai_call"}, headers=doc).json()
    assert r["status"] == "accepted" and r["call"]["status"] == "accepted"
    assert r["history"][-1]["note"] == "via AI call"
    assert client.post(f"/api/offers/{oid}/call", json={"action": "answer"},
                       headers=login_as(client, "coordinator")).status_code == 403


def test_missed_call_keeps_offer_open(client):
    oid = _sent_offer(client)
    client.put("/api/config/assumptions", json={"ai_call_after_sec": 0})
    doc = login_as(client, "okafor")
    client.get("/api/offers", headers=doc)
    r = client.post(f"/api/offers/{oid}/call", json={"action": "miss"}, headers=doc).json()
    assert r["call"]["status"] == "no_answer" and r["status"] == "sent"
