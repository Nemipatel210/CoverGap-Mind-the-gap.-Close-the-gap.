"""Replay, detection and decision tests against the challenge's reference data."""
from conftest import demo_csv


def test_replay_matches_reference_snapshot(client):
    r = client.get("/api/snapshot-check").json()
    assert r["all_ok"], r["mismatches"]
    assert r["matched"] == r["total"] > 100


def test_late_and_duplicate_events_are_handled(client):
    d = client.get("/api/dashboard").json()
    assert "EVT-00529" in d["stats"]["duplicates"]
    msgs = " ".join(c["message"] for c in d["corrections"])
    assert "EVT-01161" in msgs and "late" in msgs
    c = {x["consult_id"]: x for x in client.get("/api/consults").json()["consults"]}
    assert c["CON-2107"]["current_stage"] == "Video Consult In Progress"
    assert c["CON-2107"]["stage_entered_at"].startswith("2026-03-17T18:11:20")


def test_physician_and_consult_state_are_independent(client):
    phys = {p["physician_id"]: p for p in client.get("/api/physicians").json()["on_shift"]}
    assert phys["PHY-002"]["derived_state"] == "Video Consult In Progress"
    assert set(phys["PHY-002"]["open_consult_ids"]) == {"CON-2101", "CON-2106", "CON-2117"}
    assert phys["PHY-001"]["derived_state"] == "Camera Active - No Synapse Session"
    assert phys["PHY-001"]["busy"]
    assert phys["PHY-007"]["desktop_agent"] == "Offline" and not phys["PHY-007"]["verified"]


def test_detections_cover_hidden_situations(client):
    d = client.get("/api/dashboard").json()
    kinds = {x["kind"] for x in d["detections"]}
    assert {"breach", "routing_gap", "demand_spike", "end_of_shift", "assigned_unavailable",
            "external_platform", "agent_offline", "unverified_routing"} <= kinds
    ids = {x["id"] for x in d["detections"]}
    assert "conflict:CON-2110:unavailable" in ids
    assert "spike:SYN-005" in ids
    assert d["insights"] and d["insights"][0]["physician_id"] == "PHY-007"
    # ranked: critical first, each item explains why
    assert d["detections"][0]["severity"] == "critical"
    assert all(x["why"] for x in d["detections"])


def test_projection_covers_at_least_90_minutes(client):
    cov = client.get("/api/coverage").json()["coverage"]
    from datetime import datetime
    s = [datetime.fromisoformat(t) for t in cov["slots"]]
    assert (s[-1] - s[0]).total_seconds() >= 90 * 60


def test_exactly_one_eligible_split_shift_candidate(client):
    p = client.get("/api/incidents/inc:now/plan").json()
    elig = [c for c in p["candidates"] if c["eligible"]]
    assert [c["physician_id"] for c in elig] == ["PHY-009"]
    reasons = {c["physician_id"]: c["failed_rules"] for c in p["candidates"]}
    assert any("clash" in r.lower() for r in reasons["PHY-011"])
    assert any("60" in r for r in reasons["PHY-014"])
    assert any("Willing" in r for r in reasons["PHY-013"])
    assert any("Approved" in r for r in reasons["PHY-010"])
    assert len(p["simulation"]) == 4 and p["recommended_policy"]
    naive = next(s for s in p["simulation"] if s["policy"] == "naive")
    scoped = next(s for s in p["simulation"] if s["policy"] == "combined")
    assert scoped["joiner_other"] <= naive["joiner_other"]


def test_problems_answer_four_questions(client):
    r = client.get("/api/problems").json()
    top = r["problems"][0]
    assert top["what"] and top["where"]["hospital"] and top["matters"] and top["fix"]["label"] and top["fix"]["approver"]
    assert top["where"]["consult"] == "CON-2105"
    assert top["fix"]["kind"] == "split_shift" and "Okafor" in top["fix"]["label"]
    ids = [p["id"] for p in r["problems"]]
    assert len(ids) == len(set(ids))  # one entry per consult / hospital / doctor
    assert "c:CON-2110" in ids and "h:SYN-005" in ids and "d:PHY-003" in ids


def test_repeat_request_is_same_patient(client):
    before = {c["consult_id"]: c for c in client.get("/api/consults").json()["consults"]}["CON-2105"]
    rank_before = next(p["rank"] for p in client.get("/api/problems").json()["problems"] if p["id"] == "c:CON-2105")
    client.post("/api/events", json={"event_time": "2026-03-17T18:22:00-04:00", "consult_id": "CON-2105",
                                     "event_type": "consult_received", "hospital_id": "SYN-010",
                                     "description": "Stroke consult request received"})
    c = {c["consult_id"]: c for c in client.get("/api/consults").json()["consults"]}
    assert c["CON-2105"]["received_at"] == before["received_at"]  # clock not restarted
    assert c["CON-2105"]["repeat_calls"] == 1
    d = next(x for x in client.get("/api/coverage").json()["demand"] if x["hospital_id"] == "SYN-010")
    assert d["trailing_60"] == 1  # not counted as new demand
    p = next(p for p in client.get("/api/problems").json()["problems"] if p["id"] == "c:CON-2105")
    assert p["rank"] <= rank_before and p["repeat_calls"] == 1


def test_night_doctor_comes_on_shift_when_day_moves_on(client):
    client.post("/api/events", json={"event_time": "2026-03-17T19:00:00-04:00", "event_type": "shift_started",
                                     "physician_id": "PHY-011", "description": "Shift started"})
    client.post("/api/events", json={"event_time": "2026-03-17T19:05:00-04:00", "event_type": "physician_status_changed",
                                     "physician_id": "PHY-011", "description": "Self-reported status: Available"})
    phys = {p["physician_id"]: p for p in client.get("/api/physicians").json()["on_shift"]}
    assert phys["PHY-011"]["on_shift"] and phys["PHY-011"]["kind"] == "scheduled"
    assert not phys["PHY-003"]["on_shift"]  # 07:00-19:00 shift has ended
    cov = {r["hospital_id"]: r for r in client.get("/api/coverage").json()["coverage"]["rows"]}
    members = [m["physician_id"] for m in cov["SYN-005"]["cells"][0]["members"]]
    assert members.count("PHY-011") == 1  # counted once, not twice


def test_time_to_get_online_counts_against_offer(client):
    p = client.get("/api/incidents/inc:now/plan").json()
    menon = next(c for c in p["candidates"] if c["physician_id"] == "PHY-014")
    rule = next(r for r in menon["rules"] if r["rule"].startswith("Worth"))
    assert not rule["pass"]  # 40 min to get online on a 2.5h offer leaves under 2h
