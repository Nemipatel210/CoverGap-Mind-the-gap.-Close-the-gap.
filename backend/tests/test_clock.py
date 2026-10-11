"""Demo time control: moving the scenario clock re-runs the engine and produces new alerts."""
from conftest import login_as


def test_advance_generates_alerts_and_shift_changes(client):
    r = client.post("/api/clock", json={"action": "advance", "minutes": 45}).json()
    assert r["clock"]["mode"] == "simulated" and r["to"].startswith("2026-03-17T19:05")
    assert r["new_problems"] or r["worse_problems"]
    phys = {p["physician_id"]: p for p in client.get("/api/physicians").json()["on_shift"]}
    assert not phys["PHY-003"]["on_shift"]          # 07:00-19:00 shift has ended
    assert phys["PHY-011"]["on_shift"]              # night doctor started at 19:00
    c = {x["consult_id"]: x for x in client.get("/api/consults").json()["consults"]}
    assert c["CON-2105"]["minutes_since_received"] == 57  # timers keep running
    notes = client.get("/api/notifications", params={"audience": "coordinator"}).json()["notifications"]
    assert any(n["kind"] == "alert" for n in notes)


def test_rewind_replays_only_earlier_events(client):
    client.post("/api/clock", json={"action": "set", "value": "17:30"})
    ids = {x["consult_id"] for x in client.get("/api/consults").json()["consults"]}
    assert "CON-2114" not in ids  # received at 18:15
    back = client.post("/api/clock", json={"action": "live"}).json()
    assert back["clock"]["mode"] == "data" and back["to"].startswith("2026-03-17T18:20")


def test_offer_expires_on_simulated_time(client):
    o = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"}).json()
    client.post(f"/api/offers/{o['id']}/approve", json={})
    client.post("/api/clock", json={"action": "advance", "minutes": 11})
    st = next(x for x in client.get("/api/offers").json()["offers"] if x["id"] == o["id"])["status"]
    assert st == "timed_out"


def test_only_coordinator_moves_clock(client):
    lead = login_as(client, "lead")
    assert client.post("/api/clock", json={"action": "advance", "minutes": 5}, headers=lead).status_code == 403
    assert client.post("/api/clock", json={"action": "advance", "minutes": 5},
                       headers=login_as(client, "coordinator")).status_code == 200
