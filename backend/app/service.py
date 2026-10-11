"""Layer 3 (Act) plus state, caching, notifications, audit log and dataset management."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from . import storage
from .config import (ACTIVE_DIR, DEFAULT_ASSUMPTIONS, DEFAULT_PREFERENCES, DEMO_DIR, ROUTING, SPLIT_SHIFT,
                     STAGING_DIR, STANDARDS, STATE_DIR)
from .datasets import (SCHEMAS, build_dataset, cross_validate, guess_type, load_dir, parse_ts, read_table,
                       validate_table, KNOWN_EVENT_TYPES)
from .decide import evaluate_candidates, plan, rank
from .engine import OPEN_OFFER, compute, hm, iso
from .problems import build_problems
from .replay import default_now, prepare_events

EMPTY_WORKFLOW = {"offers": [], "escalations": [], "app_events": [], "seq": 0, "seen_detections": [], "alerts": []}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def wall_now() -> datetime:
    return datetime.now().astimezone()


class Service:
    def __init__(self):
        storage.ensure_dirs()
        self.lock = storage.LOCK
        self.version = 0
        self._cache: tuple[int, dict] | None = None
        self._snap_cache: tuple[int, Any] | None = None
        self.reload_dataset()

    # ------------------------------------------------------------------ state ---
    def reload_dataset(self):
        self.ds = load_dir(ACTIVE_DIR)
        mf = ACTIVE_DIR / "manifest.json"
        self.manifest = json.loads(mf.read_text()) if mf.exists() else {}
        self.bump()

    def bump(self):
        self.version += 1
        self._cache = None

    @property
    def wf(self) -> dict:
        return storage.read_json("workflow.json", EMPTY_WORKFLOW)

    def save_wf(self, wf: dict):
        storage.write_json("workflow.json", wf)
        self.bump()

    @property
    def assumptions(self) -> dict:
        return {**DEFAULT_ASSUMPTIONS, **storage.read_json("assumptions.json", {})}

    @property
    def prefs(self) -> dict:
        p = storage.read_json("preferences.json", DEFAULT_PREFERENCES)
        return {k: {**DEFAULT_PREFERENCES[k], **p.get(k, {})} for k in DEFAULT_PREFERENCES}

    def view(self) -> dict:
        with self.lock:
            self.expire_offers()
            if self._cache and self._cache[0] == self.version:
                return self._cache[1]
            wf = self.wf
            v = compute(self.ds, wf, self.assumptions, self.prefs)
            v["problems"] = build_problems(v, wf, self.prefs["coordinator"]["ranking"])
            self._auto_alerts(v)
            self._cache = (self.version, v)
            return v

    def public(self, v: dict) -> dict:
        return {k: val for k, val in v.items() if not k.startswith("_")}

    def snapshot_check(self):
        with self.lock:
            if self._snap_cache and self._snap_cache[0] == self.version:
                return self._snap_cache[1]
            ref = self.manifest.get("reference_as_of")
            res = None
            if self.ds.snapshot_consults or self.ds.snapshot_physicians:
                v = compute(self.ds, EMPTY_WORKFLOW, self.assumptions, self.prefs, now_override=ref)
                res = v["snapshot_check"]
                if res:
                    res["as_of"] = v["as_of"]
            self._snap_cache = (self.version, res)
            return res

    # ---------------------------------------------------------- notifications ---
    def notify(self, audience: str, title: str, body: str, *, physician_id=None, kind="info", link=None,
               offer_id=None, severity="info"):
        n = storage.read_json("notifications.json", [])
        n.insert(0, {"id": uuid.uuid4().hex[:10], "audience": audience, "physician_id": physician_id,
                     "title": title, "body": body, "kind": kind, "link": link, "offer_id": offer_id,
                     "severity": severity, "created": iso(wall_now()), "read": False})
        storage.write_json("notifications.json", n[:500])

    def notifications(self, audience: str | None, physician_id: str | None):
        n = storage.read_json("notifications.json", [])
        if audience:
            n = [x for x in n if x["audience"] == audience]
        if physician_id:
            n = [x for x in n if x.get("physician_id") == physician_id]
        return n

    def mark_read(self, nid: str | None, audience: str | None):
        n = storage.read_json("notifications.json", [])
        for x in n:
            if (nid and x["id"] == nid) or (not nid and (not audience or x["audience"] == audience)):
                x["read"] = True
        storage.write_json("notifications.json", n)

    def _auto_alerts(self, v: dict):
        """Automated low-risk action allowed by the brief: internal alert to the coordinator."""
        wf = self.wf
        seen = set(wf.get("seen_detections", []))
        new = [d for d in v["problems"] if d["severity"] == "critical" and d["id"] not in seen]
        if not new:
            return
        for d in new[:6]:
            self.notify("coordinator", f"Critical: {d['what']}", d["fix"]["label"], kind="alert",
                        link="/", severity="critical")
        wf["seen_detections"] = sorted(seen | {d["id"] for d in new})
        storage.write_json("workflow.json", wf)  # no bump: alerts don't change the computed state

    # ----------------------------------------------------------------- audit ---
    def log(self, actor: str, role: str, action: str, entity: str, entity_id: str, *, before=None, after=None,
            details: Any = None, scenario_time: str | None = None):
        a = storage.read_json("activity_log.json", [])
        a.insert(0, {"id": uuid.uuid4().hex[:10], "ts": iso(wall_now()), "scenario_time": scenario_time,
                     "actor": actor, "role": role, "action": action, "entity": entity, "entity_id": entity_id,
                     "from": before, "to": after, "details": details, "dataset": self.ds.label})
        storage.write_json("activity_log.json", a[:5000])

    # ------------------------------------------------------------------ plans ---
    def incident(self, v: dict, iid: str) -> dict:
        inc = next((i for i in v["incidents"] if i["id"] == iid), None)
        if not inc:
            raise ApiError(404, f"Incident {iid} is not currently open. It may have been resolved by new data.")
        return inc

    def split_plan(self, iid: str, mode: str | None = None, hours: float | None = None) -> dict:
        v = self.view()
        X = v["_ctx"]
        pmap = {p["physician_id"]: p for p in v["physicians"]}
        return plan(X, pmap, self.incident(v, iid), mode or self.prefs["coordinator"]["ranking"], hours)

    # ----------------------------------------------------------------- offers ---
    def _next_id(self, wf, prefix):
        wf["seq"] = wf.get("seq", 0) + 1
        return f"{prefix}-{wf['seq']:04d}"

    def propose_offer(self, iid: str, physician_id: str, actor: str, hours: float | None = None,
                      policy: str | None = None, role="coordinator", auto=False) -> dict:
        with self.lock:
            if any(o["physician_id"] == physician_id and o["status"] in OPEN_OFFER for o in self.wf["offers"]):
                raise ApiError(409, "This doctor already has an open offer.")
            p = self.split_plan(iid, None, hours)
            cand = next((c for c in p["candidates"] if c["physician_id"] == physician_id), None)
            if not cand:
                raise ApiError(404, "Physician is not on the off-shift roster.")
            if not cand["eligible"]:
                raise ApiError(409, f"{cand['name']} is not eligible: {', '.join(cand['failed_rules'])}.")
            pol = next((s for s in p["simulation"] if s["policy"] == (policy or p["recommended_policy"])), None)
            wf = self.wf
            oid = self._next_id(wf, "OFR")
            v = self.view()
            offer = {
                "id": oid, "incident_id": iid, "status": "proposed", "physician_id": physician_id,
                "physician_name": cand["name"], "hospitals": cand["scoped_hospitals"],
                "hospital_names": cand["scoped_hospital_names"], "start": p["offer"]["start"],
                "end": p["offer"]["end"], "hours": p["offer"]["hours"],
                "effective_start": cand["online_at"], "est_minutes_to_online": cand["est_minutes_to_online"],
                "policy": {"key": pol["policy"], "label": pol["label"], "scope": pol["scope"], "seed": pol["seed"]}
                if pol else {"key": "combined", "label": "Scoped", "scope": "gap", "seed": ROUTING["low_volume_day"] + 1},
                "why": f"Coverage below minimum at {', '.join(cand['scoped_hospital_names'])} "
                       f"({p['incident']['title'].lower()}).",
                "rationale": [o for o in p["options"]],
                "considered": [{"physician_id": c["physician_id"], "name": c["name"], "eligible": c["eligible"],
                                "failed_rules": c["failed_rules"], "rank": c["rank"]} for c in p["candidates"]],
                "proposed_by": actor, "proposed_role": role, "proposed_wall": iso(wall_now()),
                "scenario_time": v["as_of"], "auto_proposed": auto, "history": [],
            }
            offer["history"].append({"ts": iso(wall_now()), "status": "proposed", "by": actor})
            wf["offers"].append(offer)
            self.save_wf(wf)
            self.log(actor, role, "offer_proposed", "offer", oid, after="proposed",
                     details={"physician": cand["name"], "hospitals": offer["hospital_names"],
                              "window": f"{hm(parse_ts(offer['start']))}–{hm(parse_ts(offer['end']))}",
                              "excluded": {c["name"]: c["failed_rules"] for c in p["candidates"] if not c["eligible"]},
                              "policy": offer["policy"]["label"], "auto": auto},
                     scenario_time=v["as_of"])
            self.notify("clinical_lead", f"Approval needed: split shift for {cand['name']}",
                        f"{', '.join(offer['hospital_names'])} · {hm(parse_ts(offer['start']))}–"
                        f"{hm(parse_ts(offer['end']))} · proposed by {actor}", kind="approval",
                        link="/approvals", offer_id=oid, severity="warning")
            return offer

    def _get_offer(self, wf, oid):
        o = next((o for o in wf["offers"] if o["id"] == oid), None)
        if not o:
            raise ApiError(404, f"Offer {oid} not found.")
        return o

    def _transition(self, o, new, by, note=None):
        o["history"].append({"ts": iso(wall_now()), "status": new, "by": by, "note": note})
        old, o["status"] = o["status"], new
        return old

    def approve_offer(self, oid: str, actor: str, note: str | None = None) -> dict:
        with self.lock:
            wf = self.wf
            o = self._get_offer(wf, oid)
            if o["status"] != "proposed":
                raise ApiError(409, f"Offer is {o['status']}; only proposed offers can be approved.")
            v = self.view()
            # Re-check every rule at approval time (state may have changed since proposal)
            try:
                inc = self.incident(v, o["incident_id"])
            except ApiError:
                self._transition(o, "withdrawn", "system", "Gap no longer open")
                self.save_wf(wf)
                raise ApiError(409, "The gap this offer targets is no longer open; offer withdrawn.")
            X = v["_ctx"]
            X.offers = [x for x in X.offers if x["id"] != oid]
            rows = evaluate_candidates(X, inc, parse_ts(o["start"]), o["hours"], exclude_offer=oid)
            cand = next(c for c in rows if c["physician_id"] == o["physician_id"])
            if not cand["eligible"]:
                raise ApiError(409, f"No longer eligible: {', '.join(cand['failed_rules'])}.")
            old = self._transition(o, "sent", actor, note)
            o["approved_by"], o["approved_wall"] = actor, iso(wall_now())
            o["sent_wall"] = iso(wall_now())
            o["expires_wall"] = iso(wall_now() + timedelta(minutes=self.assumptions["offer_timeout_wall_min"]))
            self.save_wf(wf)
            self.log(actor, "clinical_lead", "offer_approved_and_sent", "offer", oid, before=old, after="sent",
                     details={"note": note, "channel": "in-app (simulated " +
                              str(next((r.get("preferred_channel") for r in self.ds.off_roster
                                        if r["physician_id"] == o["physician_id"]), "app")) + ")"},
                     scenario_time=v["as_of"])
            # Notification content: hospital names, hours and start time only. No patient information.
            self.notify("physician", "Split-shift offer",
                        f"{', '.join(o['hospital_names'])} · {hm(parse_ts(o['start']))}–{hm(parse_ts(o['end']))} ET "
                        f"({o['hours']:g}h). Reply within {self.assumptions['offer_timeout_wall_min']} min.",
                        physician_id=o["physician_id"], kind="offer", offer_id=oid, link=f"/m/{o['physician_id']}",
                        severity="warning")
            self.notify("coordinator", f"Offer {oid} approved and sent",
                        f"{o['physician_name']} · approved by {actor}", kind="offer", offer_id=oid, link="/offers")
            return o

    def reject_offer(self, oid: str, actor: str, note: str | None = None) -> dict:
        with self.lock:
            wf = self.wf
            o = self._get_offer(wf, oid)
            if o["status"] != "proposed":
                raise ApiError(409, f"Offer is {o['status']}; only proposed offers can be rejected.")
            old = self._transition(o, "rejected", actor, note)
            o["rejected_by"] = actor
            self.save_wf(wf)
            v = self.view()
            self.log(actor, "clinical_lead", "offer_rejected", "offer", oid, before=old, after="rejected",
                     details={"note": note}, scenario_time=v["as_of"])
            self.notify("coordinator", f"Offer {oid} rejected by clinical lead", note or "No note",
                        kind="offer", offer_id=oid, link="/offers", severity="warning")
            self._follow_up(o["incident_id"], reason=f"{o['physician_name']}'s offer was rejected")
            return o

    def respond_offer(self, oid: str, action: str, physician_id: str) -> dict:
        with self.lock:
            wf = self.wf
            o = self._get_offer(wf, oid)
            if o["physician_id"] != physician_id:
                raise ApiError(403, "This offer was sent to a different physician.")
            if o["status"] in ("accepted", "declined", "timed_out", "not_needed", "withdrawn"):
                raise ApiError(409, f"This offer is already {o['status'].replace('_', ' ')}.")
            if o["status"] != "sent":
                raise ApiError(409, "This offer has not been approved yet.")
            if parse_ts(o["expires_wall"]) < wall_now():
                self._transition(o, "timed_out", "system")
                self.save_wf(wf)
                raise ApiError(410, "This offer expired before a response was received.")
            v = self.view()
            if action == "decline":
                self._transition(o, "declined", physician_id)
                self.save_wf(wf)
                self.log(o["physician_name"], "physician", "offer_declined", "offer", oid, before="sent",
                         after="declined", scenario_time=v["as_of"])
                self.notify("coordinator", f"{o['physician_name']} declined {oid}", "Proposing next eligible "
                            "physician if any.", kind="offer", offer_id=oid, link="/offers", severity="warning")
                self._follow_up(o["incident_id"], reason=f"{o['physician_name']} declined")
                return o
            if action != "accept":
                raise ApiError(400, "action must be 'accept' or 'decline'.")
            # Double-acceptance guard: is the gap still short at any scoped hospital?
            rem = remaining_by_hospital(v)
            still = [h for h in o["hospitals"] if rem.get(h, 0) > 0]
            if not still:
                self._transition(o, "not_needed", "system", "Gap already filled by another acceptance")
                self.save_wf(wf)
                self.log("system", "system", "offer_acceptance_superseded", "offer", oid, before="sent",
                         after="not_needed", details={"reason": "gap already filled"}, scenario_time=v["as_of"])
                self.notify("physician", "Thank you — already covered",
                            "Another physician accepted first, so this shift is no longer needed. No action required.",
                            physician_id=physician_id, kind="offer", offer_id=oid)
                return o
            o["hospitals"] = still
            o["hospital_names"] = [v["_ctx"].hname(h) for h in still]
            self._transition(o, "accepted", physician_id)
            o["accepted_wall"] = iso(wall_now())
            self.save_wf(wf)
            self.log(o["physician_name"], "physician", "offer_accepted", "offer", oid, before="sent",
                     after="accepted", details={"hospitals": o["hospital_names"], "online_at": o["effective_start"],
                                                "routing_profile": o["policy"]}, scenario_time=v["as_of"])
            self.notify("coordinator", f"{o['physician_name']} accepted {oid}",
                        f"Online ≈{hm(parse_ts(o['effective_start']))} at {', '.join(o['hospital_names'])}. "
                        f"Routing profile: {o['policy']['label']}.", kind="offer", offer_id=oid, link="/coverage",
                        severity="success")
            self.notify("clinical_lead", f"Split shift accepted: {o['physician_name']}",
                        f"{', '.join(o['hospital_names'])} from {hm(parse_ts(o['effective_start']))}", kind="offer",
                        offer_id=oid, severity="success")
            self._stop_filled(o["incident_id"])
            self._follow_up(o["incident_id"], reason="Accepted; checking remaining gap")
            return o

    def expire_offer(self, oid: str, actor="system") -> dict:
        with self.lock:
            wf = self.wf
            o = self._get_offer(wf, oid)
            if o["status"] != "sent":
                raise ApiError(409, f"Offer is {o['status']}; only sent offers can time out.")
            self._transition(o, "timed_out", actor)
            self.save_wf(wf)
            self.log(actor, "system", "offer_timed_out", "offer", oid, before="sent", after="timed_out")
            self.notify("coordinator", f"{oid} to {o['physician_name']} timed out", "No reply within 10 minutes.",
                        kind="offer", offer_id=oid, link="/offers", severity="warning")
            self.notify("physician", "Offer expired", "The split-shift offer expired. No action needed.",
                        physician_id=o["physician_id"], kind="offer", offer_id=oid)
            self._follow_up(o["incident_id"], reason=f"{o['physician_name']} did not respond")
            return o

    def expire_offers(self):
        wf = storage.read_json("workflow.json", EMPTY_WORKFLOW)
        due = [o["id"] for o in wf["offers"] if o["status"] == "sent" and o.get("expires_wall")
               and parse_ts(o["expires_wall"]) < wall_now()]
        for oid in due:
            try:
                self.expire_offer(oid)
            except ApiError:
                pass

    def _stop_filled(self, iid: str):
        v = self.view()
        rem = remaining_by_hospital(v)
        wf = self.wf
        changed = False
        for o in wf["offers"]:
            if o["status"] not in OPEN_OFFER:
                continue
            if all(rem.get(h, 0) <= 0 for h in o["hospitals"]):
                old = self._transition(o, "withdrawn", "system", "Gap filled; further offers stopped")
                changed = True
                self.log("system", "system", "offer_withdrawn_gap_filled", "offer", o["id"], before=old,
                         after="withdrawn")
                if old == "sent":
                    self.notify("physician", "Offer withdrawn — shift covered", "No action needed. Thank you.",
                                physician_id=o["physician_id"], kind="offer", offer_id=o["id"])
        if changed:
            self.save_wf(wf)

    def _follow_up(self, iid: str, reason: str):
        """Loop back to Detect: if the gap persists and no offer is open, propose the next eligible physician."""
        v = self.view()
        inc = next((i for i in v["incidents"] if i["id"] == iid), None)
        if not inc or not inc["open"]:
            self.log("system", "system", "gap_closed", "incident", iid, details={"reason": reason})
            return
        if any(o["incident_id"] == iid and o["status"] in OPEN_OFFER for o in self.wf["offers"]):
            return
        p = self.split_plan(iid)
        nxt = next((c for c in p["candidates"] if c["eligible"] and not c["previously_declined_this_gap"]), None)
        if nxt:
            self.propose_offer(iid, nxt["physician_id"], "system", auto=True, role="system")
        else:
            wf = self.wf
            if any(e["incident_id"] == iid and e["kind"] == "no_eligible" and e["status"] == "pending"
                   for e in wf["escalations"]):
                return
            eid = self._next_id(wf, "ESC")
            wf["escalations"].append({
                "id": eid, "kind": "no_eligible", "incident_id": iid, "status": "pending",
                "title": "No eligible off-shift physician for " + ", ".join(
                    v["_ctx"].hname(h) for h, n in inc["remaining"].items() if n > 0),
                "detail": f"{reason}. Remaining shortfall: " + ", ".join(
                    f"{v['_ctx'].hname(h)} {n}" for h, n in inc["remaining"].items() if n > 0)
                          + ". Options: reassign work, ask on-shift physicians to hand off, or accept the risk.",
                "created_wall": iso(wall_now()), "created_by": "system", "scenario_time": v["as_of"]})
            self.save_wf(wf)
            self.log("system", "system", "escalation_created", "escalation", eid, after="pending",
                     details={"reason": "no eligible candidate"})
            self.notify("clinical_lead", "Escalation: no eligible off-shift physician",
                        wf["escalations"][-1]["title"], kind="escalation", link="/approvals", severity="critical")

    # ------------------------------------------------------- reassign / escalate ---
    def reassign(self, cid: str, physician_id: str, actor: str) -> dict:
        with self.lock:
            v = self.view()
            c = next((c for c in v["consults"] if c["consult_id"] == cid), None)
            if not c:
                raise ApiError(404, f"Open consult {cid} not found.")
            p = next((p for p in v["physicians"] if p["physician_id"] == physician_id and p["on_shift"]), None)
            if not p:
                raise ApiError(409, "Target physician is not on shift.")
            if c["hospital_id"] not in p["credentialed"]:
                raise ApiError(409, f"{p['name']} is not credentialed at {c['hospital_name']}.")
            if p["unavailable"]:
                raise ApiError(409, f"{p['name']} is Temporarily Unavailable.")
            if c["physician_id"] == physician_id:
                raise ApiError(409, "Consult is already assigned to this physician.")
            wf = self.wf
            eid = self._next_id(wf, "CC-EVT")
            t = v["as_of"]
            wf["app_events"].append({"event_id": eid, "event_time": t, "ingested_at": t, "consult_id": cid,
                                     "event_type": "physician_assigned", "physician_id": physician_id,
                                     "hospital_id": c["hospital_id"], "description": f"Reassigned by {actor}"})
            self.save_wf(wf)
            self.log(actor, "coordinator", "consult_reassigned", "consult", cid,
                     before=c["physician_name"] or "Unassigned", after=p["name"],
                     details={"stage": c["current_stage"], "hospital": c["hospital_name"]}, scenario_time=t)
            self.notify("coordinator", f"{cid} assigned to {p['name']}", f"{c['hospital_name']} · {c['consult_type']}",
                        kind="action", severity="success")
            return {"consult_id": cid, "physician_id": physician_id}

    def create_escalation(self, intervention_id: str, actor: str, note: str | None) -> dict:
        with self.lock:
            v = self.view()
            it = next((i for i in v["interventions"] if i["id"] == intervention_id), None)
            if not it:
                raise ApiError(404, "Intervention not found (it may have been resolved).")
            wf = self.wf
            if any(e.get("intervention_id") == intervention_id and e["status"] == "pending" for e in wf["escalations"]):
                raise ApiError(409, "An escalation for this item is already pending.")
            eid = self._next_id(wf, "ESC")
            e = {"id": eid, "kind": it["kind"], "intervention_id": intervention_id, "incident_id": it.get("incident_id"),
                 "consult_id": it.get("consult_id"), "status": "pending", "title": it["title"],
                 "detail": it["recommendation"] + (f" Note: {note}" if note else ""),
                 "created_wall": iso(wall_now()), "created_by": actor, "scenario_time": v["as_of"]}
            wf["escalations"].append(e)
            self.save_wf(wf)
            self.log(actor, "coordinator", "escalation_requested", "escalation", eid, after="pending",
                     details={"title": it["title"]}, scenario_time=v["as_of"])
            self.notify("clinical_lead", f"Escalation: {it['title']}", it["recommendation"], kind="escalation",
                        link="/approvals", severity="critical")
            return e

    def decide_escalation(self, eid: str, decision: str, actor: str, note: str | None):
        with self.lock:
            wf = self.wf
            e = next((e for e in wf["escalations"] if e["id"] == eid), None)
            if not e:
                raise ApiError(404, "Escalation not found.")
            if e["status"] != "pending":
                raise ApiError(409, f"Escalation already {e['status']}.")
            e["status"] = "authorized" if decision == "authorize" else "rejected"
            e["decided_by"], e["decided_wall"], e["note"] = actor, iso(wall_now()), note
            self.save_wf(wf)
            self.log(actor, "clinical_lead", f"escalation_{e['status']}", "escalation", eid, before="pending",
                     after=e["status"], details={"note": note})
            self.notify("coordinator", f"Escalation {e['status']}: {e['title']}", note or "", kind="escalation",
                        severity="success" if e["status"] == "authorized" else "warning")
            return e

    # ------------------------------------------------------------ problem actions ---
    def problem(self, pid: str) -> dict:
        v = self.view()
        pr = next((p for p in v["problems"] if p["id"] == pid), None)
        if not pr:
            raise ApiError(404, "That problem is no longer open. New data may have resolved it.")
        return pr

    def escalate_problem(self, pid: str, actor: str, note: str | None) -> dict:
        with self.lock:
            pr = self.problem(pid)
            wf = self.wf
            if any(e.get("problem_id") == pid and e["status"] == "pending" for e in wf["escalations"]):
                raise ApiError(409, "Already escalated and waiting for the clinical lead.")
            eid = self._next_id(wf, "ESC")
            where = " · ".join(x for x in (pr["where"].get("hospital"), pr["where"].get("consult"),
                                           pr["where"].get("doctor")) if x)
            e = {"id": eid, "kind": "problem", "problem_id": pid, "status": "pending",
                 "title": f"{pr['what']} ({where})", "detail": " ".join(pr["matters"][:3]) + (f" Note: {note}" if note else ""),
                 "stroke": pr["stroke"], "created_wall": iso(wall_now()), "created_by": actor,
                 "scenario_time": self.view()["as_of"]}
            wf["escalations"].append(e)
            self.save_wf(wf)
            self.log(actor, "coordinator", "escalation_requested", "escalation", eid, after="pending",
                     details={"problem": pr["what"], "where": where}, scenario_time=e["scenario_time"])
            self.notify("clinical_lead", f"Escalation: {pr['what']}", where, kind="escalation", link="/approvals",
                        severity="critical")
            return e

    def alert_problem(self, pid: str, actor: str) -> dict:
        """Low-risk automated step allowed by the brief: an internal alert to the coordinator/doctor."""
        with self.lock:
            pr = self.problem(pid)
            wf = self.wf
            v = self.view()
            wf.setdefault("alerts", []).append({"problem_id": pid, "time": v["as_of"], "by": actor})
            self.save_wf(wf)
            self.notify("coordinator", pr["fix"]["label"], pr["what"], kind="alert", severity="warning")
            self.log(actor, "system", "internal_alert_sent", "problem", pid,
                     details={"what": pr["what"], "action": pr["fix"]["label"], "automated": True},
                     scenario_time=v["as_of"])
            return {"ok": True}

    def upload_events(self, filename: str, raw: bytes, actor: str) -> dict:
        """The live test: add a file in event_stream.csv format to the day, rebuild, and report what changed."""
        with self.lock:
            try:
                df = read_table(raw, filename)
            except Exception as ex:  # noqa: BLE001
                raise ApiError(422, f"Couldn't read {filename}: {ex}")
            res = validate_table("event_stream", df)
            errors = [i for i in res["issues"] if i["level"] == "error"]
            if errors:
                raise ApiError(422, " ".join(i["message"] for i in errors))
            new = res["df"]
            before = self.view()
            before_ids = {p["id"]: p for p in before["problems"]}
            path = ACTIVE_DIR / "event_stream.csv"
            cur = pd.read_csv(path, dtype=str, keep_default_na=False)
            existing = set(cur["event_id"])
            in_file_dups = int(new["event_id"].duplicated().sum())
            fresh = new[~new["event_id"].isin(existing)].drop_duplicates(subset=["event_id"], keep="first")
            already = len(new) - in_file_dups - len(fresh)
            merged = pd.concat([cur, fresh], ignore_index=True)
            try:
                probe = build_dataset({**{t: validate_table(t, pd.read_csv(ACTIVE_DIR / f"{t}.csv", dtype=str,
                                                                           keep_default_na=False))["df"]
                                          for t in SCHEMAS if (ACTIVE_DIR / f"{t}.csv").exists() and t != "event_stream"},
                                       "event_stream": validate_table("event_stream", merged)["df"]}, "probe")
                compute(probe, self.wf, self.assumptions, self.prefs)
            except Exception as ex:  # noqa: BLE001
                raise ApiError(422, f"The new events couldn't be replayed, so nothing was changed: {ex}")
            storage.atomic_write_text(path, merged.to_csv(index=False))
            m = dict(self.manifest)
            m["label"] = (m.get("label", "Dataset").split(" + ")[0]) + " + live events"
            (ACTIVE_DIR / "manifest.json").write_text(json.dumps(m))
            self.reload_dataset()
            after = self.view()
            late = [l for l in prepare_events(fresh.to_dict("records"), 60)["late"]]
            new_p = [p for p in after["problems"] if p["id"] not in before_ids]
            worse = [p for p in after["problems"] if p["id"] in before_ids
                     and p["score"] > before_ids[p["id"]]["score"] + 4 and p not in new_p]
            gone = [p for pid, p in before_ids.items() if pid not in {x["id"] for x in after["problems"]}]
            summary = {
                "file": filename, "rows": len(new), "new_events": len(fresh), "already_known": already,
                "duplicates_in_file": in_file_dups, "late_events": len(late), "skipped_rows": res["dropped"],
                "warnings": [i["message"] for i in res["issues"] if i["level"] == "warning"],
                "clock_before": before["as_of"], "clock_after": after["as_of"],
                "new_problems": [_pbrief(p) for p in new_p], "worse_problems": [_pbrief(p) for p in worse],
                "resolved_problems": [_pbrief(p) for p in gone],
                "top_problem": _pbrief(after["problems"][0]) if after["problems"] else None,
            }
            self.log(actor, "coordinator", "events_uploaded", "dataset", filename,
                     details={k: summary[k] for k in ("new_events", "already_known", "late_events", "clock_before",
                                                      "clock_after")}, scenario_time=after["as_of"])
            self.notify("coordinator", f"{len(fresh)} new events added", f"Clock {before['as_of'][11:16]} → "
                        f"{after['as_of'][11:16]}; {len(new_p)} new problem(s)", kind="data", severity="success")
            return summary

    def verify_alert(self, intervention_id: str, actor: str):
        v = self.view()
        it = next((i for i in v["interventions"] if i["id"] == intervention_id), None)
        if not it:
            raise ApiError(404, "Item not found.")
        self.notify("coordinator", f"Verify: {it['title']}", it["recommendation"], kind="alert", severity="warning")
        self.log(actor, "system", "internal_alert_sent", "physician", it.get("physician_id") or "",
                 details={"title": it["title"], "automated": True}, scenario_time=v["as_of"])
        return {"ok": True}

    # ---------------------------------------------------------------- settings ---
    def set_prefs(self, role: str, data: dict):
        p = self.prefs
        if role not in p:
            raise ApiError(400, "Unknown role")
        p[role].update({k: v for k, v in data.items() if k in DEFAULT_PREFERENCES[role]})
        storage.write_json("preferences.json", p)
        self.bump()
        return p

    def set_assumptions(self, data: dict, actor: str):
        cur = storage.read_json("assumptions.json", {})
        for k, v in data.items():
            if k not in DEFAULT_ASSUMPTIONS:
                raise ApiError(400, f"Unknown or locked setting: {k}")
            if k == "horizon_min" and int(v) < 90:
                raise ApiError(400, "Horizon must be at least 90 minutes (brief requirement).")
            cur[k] = type(DEFAULT_ASSUMPTIONS[k])(v)
        storage.write_json("assumptions.json", cur)
        self.log(actor, "coordinator", "assumptions_changed", "config", "assumptions", after=cur)
        self.bump()
        return self.assumptions

    def rules(self):
        return {"standards": STANDARDS, "routing": ROUTING, "split_shift": SPLIT_SHIFT,
                "assumptions": self.assumptions, "defaults": DEFAULT_ASSUMPTIONS}

    # ---------------------------------------------------------------- datasets ---
    def dataset_types(self):
        cur = {t: self.ds.raw_counts.get(t, 0) for t in SCHEMAS}
        return [{"type": t, "label": s["label"], "required": s["required"], "columns": s["columns"],
                 "dynamic_hospital_columns": s.get("dynamic_hospital_columns", False),
                 "description": s["description"], "active_rows": cur.get(t, 0)} for t, s in SCHEMAS.items()]

    def staging(self):
        return storage.read_json("staging.json", {})

    def validate_upload(self, files: list[tuple[str, bytes]], dtype: str | None) -> dict:
        with self.lock:
            st = self.staging()
            reports = []
            for fname, raw in files:
                rep: dict[str, Any] = {"filename": fname, "type": None, "ok": False, "issues": []}
                try:
                    df = read_table(raw, fname)
                except Exception as ex:  # noqa: BLE001
                    rep["issues"].append({"level": "error", "message": f"Could not parse file: {ex}"})
                    reports.append(rep)
                    continue
                t = dtype if dtype and dtype != "auto" else guess_type(fname, list(df.columns))
                if t not in SCHEMAS:
                    rep["issues"].append({"level": "error", "message": "Could not determine the dataset type. "
                                                                       "Choose it from the dropdown."})
                    reports.append(rep)
                    continue
                res = validate_table(t, df)
                clean = res["df"]
                errors = [i for i in res["issues"] if i["level"] == "error"]
                rep.update({"type": t, "label": SCHEMAS[t]["label"], "rows_in_file": len(df),
                            "rows_valid": len(clean) if not errors else 0, "dropped": res["dropped"],
                            "issues": res["issues"], "ok": not errors, "columns": list(df.columns),
                            "preview": clean.head(8).to_dict("records") if not errors else df.head(8).fillna("").astype(str).to_dict("records")})
                if not errors:
                    STAGING_DIR.mkdir(parents=True, exist_ok=True)
                    path = STAGING_DIR / f"{t}.csv"
                    storage.atomic_write_text(path, clean.to_csv(index=False))
                    st[t] = {"filename": fname, "rows": len(clean), "issues": res["issues"],
                             "staged_wall": iso(wall_now())}
                reports.append(rep)
            storage.write_json("staging.json", st)
            return {"files": reports, "staging": st, "composed": self.composed_check()}

    def _staged_tables(self) -> dict[str, pd.DataFrame]:
        out = {}
        for t in self.staging():
            p = STAGING_DIR / f"{t}.csv"
            if p.exists():
                out[t] = pd.read_csv(p, dtype=str, keep_default_na=False)
        return out

    def _active_tables(self) -> dict[str, pd.DataFrame]:
        out = {}
        for t in SCHEMAS:
            p = ACTIVE_DIR / f"{t}.csv"
            if p.exists():
                out[t] = pd.read_csv(p, dtype=str, keep_default_na=False)
        return out

    def composed_check(self, mode: str = "replace") -> dict:
        staged = self._staged_tables()
        active = self._active_tables()
        if mode == "append_events":
            if "event_stream" not in staged:
                return {"ok": False, "issues": [{"level": "error", "message": "Stage an event stream file to append."}],
                        "sources": {}}
            merged = pd.concat([active["event_stream"], staged["event_stream"]], ignore_index=True)
            tables = {**active, "event_stream": merged}
            sources = {t: "active" for t in active} | {"event_stream": "active + staged (appended)"}
        else:
            tables = dict(active)
            sources = {t: "active (kept)" for t in active}
            if "event_stream" in staged:
                for snap in ("snapshot_open_consults", "snapshot_physicians"):
                    if snap not in staged:
                        tables.pop(snap, None)
                        sources[snap] = "dropped (stale for new events)"
            for t, df in staged.items():
                tables[t] = df
                sources[t] = "staged (new)"
        issues = cross_validate(tables)
        new_ev = 0
        if mode == "append_events" and "event_stream" in staged:
            new_ev = len(set(staged["event_stream"]["event_id"]) - set(active["event_stream"]["event_id"]))
        return {"ok": not any(i["level"] == "error" for i in issues), "issues": issues, "sources": sources,
                "counts": {t: len(df) for t, df in tables.items()}, "new_events": new_ev}

    def load_staged(self, mode: str, actor: str, label: str | None) -> dict:
        with self.lock:
            if not self.staging():
                raise ApiError(400, "Nothing staged. Upload and validate files first.")
            chk = self.composed_check(mode)
            if not chk["ok"]:
                raise ApiError(422, "Dataset is not valid: " + "; ".join(i["message"] for i in chk["issues"]
                                                                          if i["level"] == "error"))
            staged = self._staged_tables()
            active = self._active_tables()
            tmp = ACTIVE_DIR.parent / ".active_new"
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True)
            if mode == "append_events":
                merged = pd.concat([active["event_stream"], staged["event_stream"]], ignore_index=True)
                merged = merged.drop_duplicates(subset=["event_id"], keep="first")
                tables = {**active, "event_stream": merged}
            else:
                tables = {t: df for t, df in active.items()}
                if "event_stream" in staged:
                    for snap in ("snapshot_open_consults", "snapshot_physicians"):
                        if snap not in staged:
                            tables.pop(snap, None)
                tables.update(staged)
            # Final guard: the composed dataset must build and replay before it becomes active.
            try:
                ds = build_dataset({t: validate_table(t, df)["df"] for t, df in tables.items()}, "probe")
                compute(ds, EMPTY_WORKFLOW, self.assumptions, self.prefs)
            except Exception as ex:  # noqa: BLE001
                shutil.rmtree(tmp, ignore_errors=True)
                raise ApiError(422, f"Dataset failed the replay check and was not activated: {ex}")
            for t, df in tables.items():
                df.to_csv(tmp / f"{t}.csv", index=False)
            prepared = prepare_events(ds.events, 60)
            ref = default_now(prepared["events"])
            new_label = label or (self.manifest.get("label", "Dataset") + " + live events" if mode == "append_events"
                                  else f"Uploaded dataset ({datetime.now().strftime('%H:%M:%S')})")
            (tmp / "manifest.json").write_text(json.dumps({
                "label": new_label, "source": "upload", "mode": mode, "loaded_wall": iso(wall_now()),
                "reference_as_of": self.manifest.get("reference_as_of") if mode == "append_events" else iso(ref)}))
            storage.swap_active(tmp)
            for t in list(self.staging()):
                (STAGING_DIR / f"{t}.csv").unlink(missing_ok=True)
            storage.write_json("staging.json", {})
            if mode == "replace":
                self._reset_workflow()
            self.reload_dataset()
            self.log(actor, "coordinator", "dataset_loaded", "dataset", new_label,
                     details={"mode": mode, "counts": chk["counts"], "new_events": chk.get("new_events")})
            self.notify("coordinator", "Dataset loaded", f"{new_label} ({mode.replace('_', ' ')})", kind="data",
                        severity="success")
            return {"label": new_label, "counts": chk["counts"], "mode": mode, "new_events": chk.get("new_events")}

    def clear_staging(self):
        with self.lock:
            for t in list(self.staging()):
                (STAGING_DIR / f"{t}.csv").unlink(missing_ok=True)
            storage.write_json("staging.json", {})

    def _reset_workflow(self):
        storage.write_json("workflow.json", EMPTY_WORKFLOW)
        storage.write_json("notifications.json", [])

    def reset_demo(self, actor: str):
        with self.lock:
            storage.copy_demo_to_active()
            m = json.loads((ACTIVE_DIR / "manifest.json").read_text())
            ds = load_dir(ACTIVE_DIR)
            m["reference_as_of"] = iso(default_now(prepare_events(ds.events, 60)["events"]))
            (ACTIVE_DIR / "manifest.json").write_text(json.dumps(m))
            self._reset_workflow()
            self.clear_staging()
            self.reload_dataset()
            self.log(actor, "coordinator", "demo_reset", "dataset", "demo")
            return {"label": self.ds.label}

    def inject_event(self, ev: dict, actor: str) -> dict:
        with self.lock:
            cols = SCHEMAS["event_stream"]["columns"]
            row = {c: str(ev.get(c) or "").strip() for c in cols}
            if not row["event_type"] or row["event_type"] not in KNOWN_EVENT_TYPES:
                raise ApiError(422, f"event_type must be one of: {', '.join(sorted(KNOWN_EVENT_TYPES))}")
            if not parse_ts(row["event_time"]):
                raise ApiError(422, "event_time must be an ISO timestamp with offset, e.g. 2026-03-17T18:22:00-04:00")
            if not row["ingested_at"]:
                row["ingested_at"] = row["event_time"]
            elif not parse_ts(row["ingested_at"]):
                raise ApiError(422, "ingested_at must be an ISO timestamp.")
            if row["hospital_id"] and row["hospital_id"] not in self.ds.hospitals:
                raise ApiError(422, f"Unknown hospital_id {row['hospital_id']}.")
            path = ACTIVE_DIR / "event_stream.csv"
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
            if not row["event_id"]:
                n = len(df) + 1
                row["event_id"] = f"EVT-L{n:05d}"
                while row["event_id"] in set(df["event_id"]):
                    n += 1
                    row["event_id"] = f"EVT-L{n:05d}"
            elif row["event_id"] in set(df["event_id"]):
                raise ApiError(409, f"{row['event_id']} already exists (duplicates are ignored on replay).")
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            storage.atomic_write_text(path, df.to_csv(index=False))
            self.reload_dataset()
            self.log(actor, "coordinator", "event_injected", "event", row["event_id"], details=row)
            return row

    def sample_csv(self, dtype: str) -> str:
        p = DEMO_DIR / f"{dtype}.csv"
        if dtype not in SCHEMAS or not p.exists():
            raise ApiError(404, "Unknown dataset type")
        return p.read_text()


def _pbrief(p: dict) -> dict:
    return {"id": p["id"], "what": p["what"], "where": p["where"], "severity": p["severity"], "fix": p["fix"]["label"]}


def remaining_by_hospital(v: dict) -> dict:
    rem: dict[str, int] = {}
    for g in v["routing_gaps"] + v["roster_gaps"]:
        rem[g["hospital_id"]] = max(rem.get(g["hospital_id"], 0), g["remaining"])
    return rem


def init_reference():
    """Make sure the active manifest records the reference time used by the snapshot check."""
    mf = ACTIVE_DIR / "manifest.json"
    m = json.loads(mf.read_text()) if mf.exists() else {"label": "Dataset"}
    if "reference_as_of" not in m:
        ds = load_dir(ACTIVE_DIR)
        m["reference_as_of"] = iso(default_now(prepare_events(ds.events, 60)["events"]))
        mf.write_text(json.dumps(m))
