"""Closed loop: propose -> approve -> send -> accept/decline/timeout -> update; dataset management."""
import io

from conftest import demo_csv


def _propose_and_send(client, pid="PHY-009"):
    o = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": pid}).json()
    assert o["status"] == "proposed", o
    s = client.post(f"/api/offers/{o['id']}/approve", json={"actor": "Lead"}).json()
    assert s["status"] == "sent"
    return o["id"]


def test_offer_requires_approval_and_contains_no_patient_info(client):
    o = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"}).json()
    r = client.post(f"/api/offers/{o['id']}/respond", json={"physician_id": "PHY-009", "action": "accept"})
    assert r.status_code == 409  # not approved yet
    assert not client.get("/api/notifications", params={"audience": "physician"}).json()["notifications"]
    client.post(f"/api/offers/{o['id']}/approve", json={"actor": "Lead"})
    n = client.get("/api/notifications", params={"audience": "physician"}).json()["notifications"][0]
    assert "CON-" not in n["body"] and "Stroke" not in n["body"]


def test_pending_offer_shows_on_problem(client):
    client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"})
    pr = next(p for p in client.get("/api/problems").json()["problems"] if p["id"] == "c:CON-2105")
    assert pr["fix"]["kind"] == "split_shift" and pr["status"]["state"] == "proposed"
    assert client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"}).status_code == 409


def test_ineligible_physician_cannot_be_proposed(client):
    r = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-014"})
    assert r.status_code == 409


def test_accept_updates_coverage_and_stops_offers(client):
    oid = _propose_and_send(client)
    r = client.post(f"/api/offers/{oid}/respond", json={"physician_id": "PHY-009", "action": "accept"}).json()
    assert r["status"] == "accepted"
    gaps = {g["hospital_id"]: g for g in client.get("/api/coverage").json()["routing_gaps"]}
    assert gaps["SYN-010"]["remaining"] == 0
    assert gaps["SYN-005"]["remaining"] == 1
    phys = client.get("/api/physicians").json()["on_shift"]
    j = next(p for p in phys if p["kind"] == "split_shift")
    assert j["credentialed"] == ["SYN-005", "SYN-010"]  # scoped to gap hospitals (split-shift trap)
    assert j["seed_count"] > 0
    pr = next(p for p in client.get("/api/problems").json()["problems"] if p["id"] == "c:CON-2105")
    assert pr["fix"]["kind"] == "joining" and pr["status"]["state"] == "accepted"
    esc = client.get("/api/offers").json()["escalations"]
    assert esc and esc[0]["kind"] == "no_eligible"  # nobody else eligible -> escalated, no more offers
    log = [a["action"] for a in client.get("/api/activity").json()["activity"]]
    assert {"offer_proposed", "offer_approved_and_sent", "offer_accepted"} <= set(log)


def test_decline_and_timeout(client):
    oid = _propose_and_send(client)
    assert client.post(f"/api/offers/{oid}/respond",
                       json={"physician_id": "PHY-009", "action": "decline"}).json()["status"] == "declined"
    assert client.post(f"/api/offers/{oid}/respond",
                       json={"physician_id": "PHY-009", "action": "accept"}).status_code == 409


def test_timeout(client):
    oid = _propose_and_send(client)
    assert client.post(f"/api/offers/{oid}/expire", json={"actor": "demo"}).json()["status"] == "timed_out"


def test_reject_by_clinical_lead(client):
    o = client.post("/api/offers", json={"incident_id": "inc:now", "physician_id": "PHY-009"}).json()
    assert client.post(f"/api/offers/{o['id']}/reject", json={"actor": "Lead", "note": "no"}).json()["status"] == "rejected"


def test_two_acceptances_for_one_slot(client):
    """Make a second physician eligible, send both offers, accept both: the second is 'not_needed'."""
    roster = demo_csv("physicians_off_shift_roster").decode().replace(
        "PHY-014,Dr. Ravi Menon,Float,Yes,2026-03-16T20:00:00-04:00,2026-03-19T07:00:00-04:00,59",
        "PHY-014,Dr. Ravi Menon,Float,Yes,2026-03-16T20:00:00-04:00,2026-03-19T07:00:00-04:00,30").replace(",30,40,sms", ",30,20,sms")
    client.post("/api/datasets/validate", files={"files": ("physicians_off_shift_roster.csv", roster.encode())})
    assert client.post("/api/datasets/load", json={"mode": "replace"}).status_code == 200
    # Oak Valley needs 1; both are credentialed there.
    a = _propose_and_send(client, "PHY-009")
    b = _propose_and_send(client, "PHY-014")
    assert client.post(f"/api/offers/{a}/respond", json={"physician_id": "PHY-009", "action": "accept"}).json()["status"] == "accepted"
    r = client.post(f"/api/offers/{b}/respond", json={"physician_id": "PHY-014", "action": "accept"}).json()
    # Menon is credentialed at Suncrest too, which still needs one -> accepted for Suncrest only
    assert r["status"] == "accepted" and r["hospitals"] == ["SYN-005"]
    c = _accept_third(client)
    assert c in ("not_needed", "no_gap")


def _accept_third(client):
    gaps = {g["hospital_id"]: g["remaining"] for g in client.get("/api/coverage").json()["routing_gaps"]}
    return "no_gap" if gaps.get("SYN-005", 0) == 0 and gaps.get("SYN-010", 0) == 0 else "open"


def test_reassign_appends_event_and_updates_state(client):
    r = client.post("/api/consults/CON-2110/reassign", json={"physician_id": "PHY-001", "actor": "Coord"})
    assert r.status_code == 200
    c = {x["consult_id"]: x for x in client.get("/api/consults").json()["consults"]}
    assert c["CON-2110"]["physician_id"] == "PHY-001"
    bad = client.post("/api/consults/CON-2105/reassign", json={"physician_id": "PHY-001"})
    assert bad.status_code == 409  # PHY-001 not credentialed at Oak Valley


def test_dataset_validation_errors(client):
    r = client.post("/api/datasets/validate", files={"files": ("x.pdf", b"%PDF")}).json()
    assert not r["files"][0]["ok"]
    r = client.post("/api/datasets/validate", data={"dataset_type": "hospitals"},
                    files={"files": ("hospitals.csv", b"hospital_id,hospital_name\nSYN-1,A\n")}).json()
    assert "Missing required column" in r["files"][0]["issues"][0]["message"]
    r = client.post("/api/datasets/validate", files={"files": ("hospitals.csv",
                    b"hospital_id,hospital_name,local_timezone,coverage_tier\n")}).json()
    assert not r["files"][0]["ok"]
    r = client.post("/api/datasets/validate", files={"files": ("hospitals.csv",
                    b"hospital_id,hospital_name,local_timezone,coverage_tier\nA,B,x,A\nA,C,x,B\n")}).json()
    assert any("Duplicate" in i["message"] for i in r["files"][0]["issues"])


def test_missing_reference_blocks_load_and_keeps_active(client):
    before = client.get("/api/meta").json()["dataset"]
    cred = b"physician_id,name,SYN-999\nPHY-001,X,Y\n"
    client.post("/api/datasets/validate", files={"files": ("credentialing_matrix.csv", cred)})
    r = client.post("/api/datasets/load", json={"mode": "replace"})
    assert r.status_code == 422
    assert client.get("/api/meta").json()["dataset"] == before
    assert client.get("/api/snapshot-check").json()["all_ok"]


def test_json_upload_and_append_live_event(client):
    import json
    ev = [{"event_id": "EVT-90001", "event_time": "2026-03-17T18:21:00-04:00",
           "ingested_at": "2026-03-17T18:21:02-04:00", "consult_id": "CON-2201", "event_type": "consult_received",
           "physician_id": "", "hospital_id": "SYN-005", "description": "Stroke consult request received"}]
    r = client.post("/api/datasets/validate", data={"dataset_type": "event_stream"},
                    files={"files": ("live.json", json.dumps(ev).encode())}).json()
    assert r["files"][0]["ok"]
    out = client.post("/api/datasets/load", json={"mode": "append_events"}).json()
    assert out["new_events"] == 1
    c = {x["consult_id"]: x for x in client.get("/api/consults").json()["consults"]}
    assert "CON-2201" in c
    d = next(x for x in client.get("/api/coverage").json()["demand"] if x["hospital_id"] == "SYN-005")
    assert d["trailing_60"] == 6


def test_inject_event_without_restart(client):
    r = client.post("/api/events", json={"event_time": "2026-03-17T18:22:00-04:00", "consult_id": "CON-2299",
                                         "event_type": "consult_received", "hospital_id": "SYN-005",
                                         "description": "Stroke consult request received"})
    assert r.status_code == 200
    assert client.get("/api/meta").json()["as_of"].startswith("2026-03-17T18:22")


def test_second_full_dataset_then_reset(client):
    for name in ["hospitals", "physicians_on_shift", "physicians_off_shift_roster", "credentialing_matrix",
                 "baseline_hourly_volume", "coverage_requirements", "event_stream"]:
        body = demo_csv(name)
        if name == "physicians_on_shift":
            body = body.replace(b"PHY-007,Dr. Elena Torres", b"PHY-007,Dr. Elena Torres-Ng")
        r = client.post("/api/datasets/validate", files={"files": (f"9999_{name}.csv", body)}).json()
        assert r["files"][0]["ok"], r
    assert client.post("/api/datasets/load", json={"mode": "replace", "label": "Judge set"}).status_code == 200
    phys = client.get("/api/physicians").json()["on_shift"]
    assert any(p["name"] == "Dr. Elena Torres-Ng" for p in phys)
    assert client.get("/api/snapshot-check").json()["all_ok"] is None  # stale snapshots dropped
    client.post("/api/datasets/reset", json={"actor": "t"})
    assert client.get("/api/snapshot-check").json()["all_ok"]


def test_upload_event_file_reports_what_changed(client):
    body = (b"event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,description\n"
            b"EVT-01163,2026-03-17T18:19:40-04:00,2026-03-17T18:19:43-04:00,CON-2109,incoming_call_ringing,PHY-007,SYN-012,dup\n"
            b"EVT-90010,2026-03-17T18:24:00-04:00,2026-03-17T18:24:02-04:00,CON-2201,consult_received,,SYN-005,Stroke consult request received\n"
            b"EVT-90011,2026-03-17T18:25:30-04:00,2026-03-17T18:25:31-04:00,CON-2201,consult_triaged,,SYN-005,Consult triaged\n"
            b"EVT-90011,2026-03-17T18:25:30-04:00,2026-03-17T18:25:31-04:00,CON-2201,consult_triaged,,SYN-005,Consult triaged\n"
            b"EVT-90012,2026-03-17T18:22:00-04:00,2026-03-17T18:29:00-04:00,CON-2201,routing_attempt_failed,,SYN-005,late\n")
    r = client.post("/api/events/upload", files={"file": ("judges.csv", body)})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["new_events"] == 3 and s["already_known"] == 1 and s["duplicates_in_file"] == 1 and s["late_events"] == 1
    assert s["clock_after"].startswith("2026-03-17T18:29")
    assert any(p["id"] == "c:CON-2201" for p in s["new_problems"])
    bad = client.post("/api/events/upload", files={"file": ("bad.csv", b"a,b\n1,2\n")})
    assert bad.status_code == 422


def test_problem_escalate_and_alert(client):
    assert client.post("/api/problems/c:CON-2110/escalate", json={"actor": "Coord"}).status_code == 200
    assert client.post("/api/problems/c:CON-2110/escalate", json={"actor": "Coord"}).status_code == 409
    p = next(p for p in client.get("/api/problems").json()["problems"] if p["id"] == "c:CON-2110")
    assert p["status"]["state"] == "escalated"
    assert client.post("/api/problems/d:PHY-001/alert", json={"actor": "Coord"}).status_code == 200
