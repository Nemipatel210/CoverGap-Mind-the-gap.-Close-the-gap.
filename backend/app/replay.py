"""Layer 0: rebuild current state from the event stream.

* De-duplicates on event_id.
* Orders by event_time (ties: ingested_at, event_id), never by arrival order.
* Keeps physician activity and consult lifecycle as two independent state machines.
* Reconciles contradictory physician signals into a derived state.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import ET
from .datasets import Dataset, parse_ts

CALL_STARTS = {"incoming_call_started": "Incoming", "outgoing_call_started": "Outgoing"}
CALL_ENDS = {"incoming_call_ended", "outgoing_call_ended"}
PRE_CONTACT = {"Received", "Triaged", "Assigned"}


@dataclass
class Consult:
    consult_id: str
    hospital_id: str = ""
    consult_type: str = "Unknown"
    physician_id: str | None = None
    stage: str = "Received"
    stage_entered_at: datetime | None = None
    received_at: datetime | None = None
    clinical_end_at: datetime | None = None
    last_call_end: datetime | None = None
    routing_failures: int = 0
    last_routing_failure: datetime | None = None
    ringing_to: str | None = None
    repeat_calls: int = 0          # hospital asked again about the same consult (same patient)
    last_repeat_at: datetime | None = None
    rings: int = 0
    request_seen: bool = False
    history: list = field(default_factory=list)       # [(stage, start)]
    assignments: list = field(default_factory=list)   # [(physician, time, source)]

    def set_stage(self, stage: str, t: datetime) -> None:
        if stage != self.stage or self.stage_entered_at is None:
            self.stage = stage
            self.stage_entered_at = t
            self.history.append((stage, t))


@dataclass
class Physician:
    physician_id: str
    status: str = "Available"
    camera: bool = False
    camera_since: datetime | None = None
    agent_online: bool = True
    agent_lost_at: datetime | None = None
    calls: dict = field(default_factory=dict)   # consult -> (direction, start)
    video: dict = field(default_factory=dict)   # consult -> start
    ringing: str | None = None
    last_call_end: datetime | None = None
    last_answer: datetime | None = None
    shift_started_at: datetime | None = None
    consults: set = field(default_factory=set)
    calls_count: int = 0
    status_since: datetime | None = None
    segments: list = field(default_factory=list)  # activity [kind, consult, start, end]
    open_seg: dict = field(default_factory=dict)


def _ceil_minute(d: datetime) -> datetime:
    if d.second or d.microsecond:
        d = d.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return d


def prepare_events(raw: list[dict], late_threshold: int) -> dict:
    seen: dict[str, dict] = {}
    duplicates: list[str] = []
    bad: list[str] = []
    for r in raw:
        eid = str(r.get("event_id", "")).strip()
        et, it = parse_ts(r.get("event_time")), parse_ts(r.get("ingested_at")) or parse_ts(r.get("event_time"))
        if not eid or et is None:
            bad.append(eid or "?")
            continue
        if eid in seen:
            duplicates.append(eid)
            continue
        seen[eid] = {**r, "event_id": eid, "_et": et, "_it": it,
                     "consult_id": (r.get("consult_id") or "").strip(),
                     "physician_id": (r.get("physician_id") or "").strip(),
                     "hospital_id": (r.get("hospital_id") or "").strip(),
                     "event_type": (r.get("event_type") or "").strip(),
                     "description": (r.get("description") or "").strip()}
    evs = sorted(seen.values(), key=lambda e: (e["_et"], e["_it"], e["event_id"]))
    by_arrival = sorted(seen.values(), key=lambda e: (e["_it"], e["event_id"]))
    late = []
    max_et_seen = None
    for e in by_arrival:
        lag = (e["_it"] - e["_et"]).total_seconds()
        out_of_order = max_et_seen is not None and e["_et"] < max_et_seen
        if lag > late_threshold or (out_of_order and lag > 5):
            late.append({"event_id": e["event_id"], "event_type": e["event_type"], "consult_id": e["consult_id"],
                         "physician_id": e["physician_id"], "event_time": e["_et"].isoformat(),
                         "ingested_at": e["_it"].isoformat(), "lag_sec": int(lag)})
        max_et_seen = e["_et"] if max_et_seen is None else max(max_et_seen, e["_et"])
    return {"events": evs, "duplicates": duplicates, "bad": bad, "late": late}


def default_now(events: list[dict]) -> datetime | None:
    if not events:
        return None
    return _ceil_minute(max(max(e["_it"], e["_et"]) for e in events))


def shift_window(start_hhmm: str, end_hhmm: str, now: datetime) -> tuple[datetime, datetime]:
    def at(day, hhmm):
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime(day.year, day.month, day.day, h, m, tzinfo=ET)
    for delta in (0, -1):
        day = (now + timedelta(days=delta)).date()
        s, e = at(day, start_hhmm), at(day, end_hhmm)
        if e <= s:
            e += timedelta(days=1)
        if s <= now < e:
            return s, e
    day = now.date()
    s, e = at(day, start_hhmm), at(day, end_hhmm)
    if e <= s:
        e += timedelta(days=1)
    return s, e


def replay(ds: Dataset, prepared: dict, now: datetime, extra_events: list[dict] | None = None) -> dict:
    events = [e for e in prepared["events"] if e["_et"] <= now]
    if extra_events:
        events = sorted(events + [e for e in extra_events if e["_et"] <= now],
                        key=lambda e: (e["_et"], e["_it"], e["event_id"]))
    consults: dict[str, Consult] = {}
    phys: dict[str, Physician] = {}

    def P(pid: str) -> Physician:
        if pid not in phys:
            phys[pid] = Physician(pid)
        return phys[pid]

    def seg_open(p: Physician, kind: str, cid: str, t: datetime):
        p.open_seg[(kind, cid)] = t

    def seg_close(p: Physician, kind: str, cid: str, t: datetime):
        st = p.open_seg.pop((kind, cid), None)
        if st is not None:
            p.segments.append([kind, cid, st, t])

    for e in events:
        t, typ, cid, pid = e["_et"], e["event_type"], e["consult_id"], e["physician_id"]
        c = None
        if cid:
            c = consults.get(cid)
            if c is None:
                c = consults[cid] = Consult(cid, hospital_id=e["hospital_id"])
                c.set_stage("Received", t)
                c.received_at = t
            if e["hospital_id"] and not c.hospital_id:
                c.hospital_id = e["hospital_id"]
        p = P(pid) if pid else None

        if typ == "consult_received" and c:
            m = re.match(r"^(.*?)\s+consult request", e["description"], re.I)
            if m and c.consult_type == "Unknown":
                c.consult_type = m.group(1).strip()
            if c.request_seen:
                # Same consult asked about again: one patient, clock keeps running from the first request.
                c.repeat_calls += 1
                c.last_repeat_at = t
            else:
                c.request_seen = True
                c.received_at = min(t, c.received_at or t)
        elif typ == "consult_triaged" and c:
            if c.stage in ("Received",):
                c.set_stage("Triaged", t)
        elif typ == "physician_assigned" and c:
            if c.physician_id and c.physician_id != pid and c.physician_id in phys:
                phys[c.physician_id].consults.discard(cid)
            c.physician_id = pid or c.physician_id
            c.assignments.append((pid, t, e.get("_source", "stream")))
            if c.stage in ("Received", "Triaged"):
                c.set_stage("Assigned", t)
            if p:
                p.consults.add(cid)
            c.ringing_to = None
        elif typ == "routing_attempt_failed" and c:
            c.routing_failures += 1
            c.last_routing_failure = t
        elif typ == "incoming_call_ringing":
            if p:
                p.ringing = cid or "call"
            if c:
                c.rings += 1
                if c.rings > 1 and c.stage in ("Received", "Triaged", "Assigned"):
                    c.repeat_calls += 1
                    c.last_repeat_at = t
                c.ringing_to = pid or c.ringing_to
        elif typ in CALL_STARTS and p:
            p.calls[cid or f"call-{e['event_id']}"] = (CALL_STARTS[typ], t)
            p.calls_count += 1
            p.last_answer = t
            if p.ringing and (not cid or p.ringing == cid):
                p.ringing = None
            seg_open(p, "call", cid, t)
            if c:
                c.ringing_to = None
                if c.physician_id is None:
                    c.physician_id = pid
                    p.consults.add(cid)
                if c.stage in PRE_CONTACT:
                    c.set_stage("Provider Contacted", t)
        elif typ in CALL_ENDS and p:
            p.calls.pop(cid or next(iter(p.calls), ""), None)
            p.last_call_end = t
            seg_close(p, "call", cid, t)
            if c:
                c.last_call_end = t
                if "phone-only" in e["description"].lower() and c.stage not in ("Documentation", "Signed Off"):
                    c.set_stage("Note Pending", t)
                    c.clinical_end_at = t
        elif typ == "imaging_requested" and c:
            if c.stage not in ("Video Consult In Progress", "Note Pending", "Documentation", "Signed Off"):
                c.set_stage("CT/CTA or Imaging Pending", t)
        elif typ == "imaging_returned" and c:
            if c.stage not in ("Video Consult In Progress", "Note Pending", "Documentation", "Signed Off"):
                c.set_stage("Imaging Review", t)
        elif typ == "video_started":
            if p:
                p.video[cid] = t
                seg_open(p, "video", cid, t)
            if c:
                c.set_stage("Video Consult In Progress", t)
        elif typ == "video_ended":
            if p:
                p.video.pop(cid, None)
                seg_close(p, "video", cid, t)
            if c:
                c.set_stage("Note Pending", t)
                c.clinical_end_at = t
        elif typ == "note_started" and c:
            if c.clinical_end_at is None:
                c.clinical_end_at = c.last_call_end or t
            c.set_stage("Documentation", t)
        elif typ == "note_signed" and c:
            c.set_stage("Signed Off", t)
        elif typ == "physician_status_changed" and p:
            m = re.search(r"status:\s*(.+)$", e["description"], re.I)
            if m:
                p.status = m.group(1).strip()
                p.status_since = t
        elif typ == "camera_active" and p:
            p.camera, p.camera_since = True, t
            p.agent_online = True
            seg_open(p, "camera", "", t)
        elif typ == "camera_inactive" and p:
            p.camera = False
            p.agent_online = True
            seg_close(p, "camera", "", t)
        elif typ == "agent_heartbeat_lost" and p:
            p.agent_online, p.agent_lost_at = False, t
        elif typ == "agent_heartbeat_restored" and p:
            p.agent_online = True
        elif typ == "shift_started" and p:
            p.shift_started_at = t

    for p in phys.values():
        for (kind, cid), st in list(p.open_seg.items()):
            p.segments.append([kind, cid, st, None])
    return {"consults": consults, "physicians": phys, "events_used": len(events)}


def derive_state(p: Physician | None, consults: dict[str, Consult], now: datetime) -> dict:
    """Reconcile signals (brief: 'Availability is inferred, not reported')."""
    flags = []
    if p is None:
        return {"derived_state": "Available", "busy": False, "unavailable": False, "flags": flags,
                "activity_consult": None}
    in_meeting = p.status.lower() == "in meeting"
    active = []
    for cid, (direction, st) in p.calls.items():
        active.append((st, f"{direction} Hospital Call", cid))
    for cid, st in p.video.items():
        active.append((st, "Video Consult In Progress", cid))
    busy, unavailable, state, act = False, False, "Available", None
    if active:
        st, state, act = max(active, key=lambda a: a[0])
        busy = True
        if p.status.lower().startswith("temporarily"):
            flags.append({"code": "status_conflict", "severity": "warning",
                          "message": "Self-reported Temporarily Unavailable but a Synapse session is active"})
    elif p.status.lower().startswith("temporarily"):
        state, unavailable = "Temporarily Unavailable", True
    elif p.camera and p.agent_online and not in_meeting:
        state, busy = "Camera Active - No Synapse Session", True
        flags.append({"code": "external_platform", "severity": "warning",
                      "message": "Camera active with no Synapse session and status not In Meeting: probably on an "
                                 "external video platform. Treated as busy."})
    elif p.camera and in_meeting:
        state = "In Meeting (interruptible)"
    else:
        docs = [c for c in consults.values() if c.physician_id == p.physician_id and c.stage == "Documentation"]
        if docs:
            state, act = "Documentation / Note", docs[0].consult_id
    if not p.agent_online:
        flags.append({"code": "agent_offline", "severity": "warning",
                      "message": "Desktop presence agent offline: camera state unknown. Routing assumes available, "
                                 "but this is unverified."})
    return {"derived_state": state, "busy": busy, "unavailable": unavailable, "flags": flags,
            "activity_consult": act, "in_meeting": in_meeting}


def minutes_between(a: datetime | None, b: datetime) -> int | None:
    if a is None:
        return None
    return int(math.floor((b - a).total_seconds() / 60))
