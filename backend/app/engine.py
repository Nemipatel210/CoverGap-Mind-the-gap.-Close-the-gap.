"""Layers 1-2: Detect and Decide.

`compute()` is a pure function of (dataset, workflow state, assumptions, now). It returns a
JSON-serialisable view model consumed by the API. Results are cached by a version key.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta
from typing import Any

from .config import (END_OF_SHIFT_WINDOW_MIN, ROUTING, SPIKE_WINDOW_MIN, SPLIT_SHIFT, STANDARDS)
from .datasets import Dataset, parse_ts
from .replay import (Consult, derive_state, default_now, minutes_between, prepare_events, replay,
                     shift_window)

OPEN_OFFER = ("proposed", "sent")


def iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def hm(d: datetime | None) -> str:
    return d.strftime("%H:%M") if d else "—"


def _round_up(d: datetime, minutes: int) -> datetime:
    d = d.replace(second=0, microsecond=0)
    r = d.minute % minutes
    return d if r == 0 else d + timedelta(minutes=minutes - r)


class Ctx:
    """Holds everything derived once per compute so helpers stay small."""

    def __init__(self, ds: Dataset, state: dict, A: dict, now_override: str | None):
        self.ds, self.state, self.A = ds, state, A
        self.prepared = prepare_events(ds.events, A["late_event_threshold_sec"])
        extra = []
        for e in state.get("app_events", []):
            et = parse_ts(e["event_time"])
            extra.append({**e, "_et": et, "_it": parse_ts(e.get("ingested_at")) or et, "_source": "command-center"})
        self.extra = extra
        base_now = default_now(self.prepared["events"] + extra) or datetime.now().astimezone()
        self.now = parse_ts(now_override) if now_override else base_now
        self.r = replay(ds, self.prepared, self.now, extra)
        self.consults: dict[str, Consult] = self.r["consults"]
        self.dow = "weekday" if self.now.weekday() < 5 else "weekend"
        self.offers = state.get("offers", [])
        self.joiners = [o for o in self.offers if o["status"] == "accepted"]

    # ---- reference data helpers -------------------------------------------------
    def name(self, pid: str | None) -> str:
        return self.ds.names.get(pid or "", pid or "Unassigned")

    def hname(self, hid: str) -> str:
        return self.ds.hospitals.get(hid, {}).get("hospital_name", hid)

    def baseline(self, hid: str, t: datetime) -> tuple[float, float]:
        for dow in (self.dow, "weekday"):
            v = self.ds.baseline.get((hid, dow, t.hour))
            if v:
                return v
        return (0.0, 0.0)

    def requirement(self, hid: str, t: datetime) -> tuple[int, str]:
        m = t.hour * 60 + t.minute
        for a, b, n, label in self.ds.requirements.get(hid, []):
            inside = a <= m < b if a < b else (m >= a or m < b)
            if inside:
                return n, label
        return 0, "none"

    def received_times(self, hid: str) -> list[datetime]:
        return [c.received_at for c in self.consults.values() if c.hospital_id == hid and c.received_at]

    def trailing(self, hid: str, t: datetime) -> float:
        """Trailing-60 consult count at t. Known arrivals roll off; the unknown future portion uses the
        baseline mean (no invented surge model)."""
        lo = t - timedelta(minutes=SPIKE_WINDOW_MIN)
        known = sum(1 for x in self.received_times(hid) if lo < x <= min(t, self.now))
        future_min = max(0.0, (t - max(self.now, lo)).total_seconds() / 60)
        return known + self.baseline(hid, t)[0] * future_min / 60


def compute(ds: Dataset, state: dict, A: dict, prefs: dict, now_override: str | None = None) -> dict:
    X = Ctx(ds, state, A, now_override)
    now = X.now
    physicians = build_physicians(X)
    pmap = {p["physician_id"]: p for p in physicians}
    consults = build_consults(X, pmap)
    demand = build_demand(X)
    slots = [now] + [_round_up(now + timedelta(minutes=1), A["step_min"]) + timedelta(minutes=A["step_min"] * i)
                     for i in range((A["horizon_min"] // A["step_min"]) + 1)]
    slots = sorted({s for s in slots if s <= now + timedelta(minutes=A["horizon_min"])})
    coverage = build_coverage(X, pmap, slots, X.joiners)
    routing_gaps = build_routing_gaps(X, pmap, consults, coverage)
    roster_gaps = build_roster_gaps(X, coverage)
    incidents = build_incidents(X, routing_gaps, roster_gaps)
    detections = build_detections(X, pmap, consults, demand, coverage, routing_gaps, roster_gaps, physicians)
    interventions = build_interventions(X, pmap, consults, detections, incidents)
    for d in detections:
        d["intervention_ids"] = [i["id"] for i in interventions if d["id"] in i["detection_ids"]]
    detections.sort(key=lambda d: -d["score"])
    for i, d in enumerate(detections, 1):
        d["rank"] = i
    corrections = build_corrections(X)
    kpis = build_kpis(X, consults, detections, routing_gaps, roster_gaps, incidents)
    return {
        "as_of": iso(now), "as_of_label": now.strftime("%a %d %b %Y · %H:%M ET"), "dataset": ds.label,
        "physicians": physicians, "off_shift": build_off_shift(X),
        "consults": consults, "demand": demand, "coverage": {"slots": [iso(s) for s in slots], "rows": coverage},
        "routing_gaps": routing_gaps, "roster_gaps": roster_gaps, "incidents": incidents,
        "detections": detections, "interventions": interventions, "corrections": corrections, "kpis": kpis,
        "insights": build_insights(physicians),
        "timeline": build_timeline(X),
        "stats": {"events_in_file": len(ds.events), "events_unique": len(X.prepared["events"]),
                  "events_replayed": X.r["events_used"], "app_events": len(X.extra),
                  "duplicates": X.prepared["duplicates"], "late_events": len(X.prepared["late"]),
                  "malformed_events": X.prepared["bad"]},
        "snapshot_check": snapshot_check(X, physicians, consults),
        "_ctx": X,  # stripped before serialising
    }


# ---------------------------------------------------------------------------------
# Physicians
# ---------------------------------------------------------------------------------
def build_physicians(X: Ctx) -> list[dict]:
    out = []
    now = X.now
    for row in X.ds.on_shift:
        pid = row["physician_id"]
        p = X.r["physicians"].get(pid)
        s, e = shift_window(row["shift_start_et"], row["shift_end_et"], now)
        d = derive_state(p, X.consults, now)
        open_c = [c for c in X.consults.values() if c.physician_id == pid and c.stage != "Signed Off"]
        out.append(_phys_row(X, pid, "scheduled", s, e, p, d, open_c, sorted(X.ds.cred.get(pid, set()))))
    # Off-shift roster doctors whose scheduled shift has started (the day can move past 19:00 in new data).
    listed = {r["physician_id"] for r in X.ds.on_shift}
    for r in X.ds.off_roster:
        pid = r["physician_id"]
        ns = parse_ts(r.get("next_shift_start"))
        pr = X.r["physicians"].get(pid)
        started = pr.shift_started_at if pr else None
        if pid in listed or not (ns or started):
            continue
        s = ns if ns else started
        if started and ns and abs((started - ns).total_seconds()) > 3 * 3600:
            s = started
        e = s + timedelta(hours=X.A["scheduled_shift_hours"])
        if not (s <= now < e):
            continue
        d = derive_state(pr, X.consults, now)
        open_c = [c for c in X.consults.values() if c.physician_id == pid and c.stage != "Signed Off"]
        row = _phys_row(X, pid, "scheduled", s, e, pr, d, open_c, sorted(X.ds.cred.get(pid, set())))
        row["from_roster"] = True
        out.append(row)
    for o in X.joiners:
        pid = o["physician_id"]
        s, e = parse_ts(o["effective_start"]), parse_ts(o["end"])
        p = X.r["physicians"].get(pid)
        d = derive_state(p, X.consults, now)
        open_c = [c for c in X.consults.values() if c.physician_id == pid and c.stage != "Signed Off"]
        row = _phys_row(X, pid, "split_shift", s, e, p, d, open_c, o["hospitals"])
        row["offer_id"] = o["id"]
        row["seed_count"] = o.get("policy", {}).get("seed", 0)
        row["consults_this_shift"] += row["seed_count"]
        if now < s:
            row["derived_state"] = f"Joining · online {hm(s)}"
        out.append(row)
    return out


def _phys_row(X, pid, kind, s, e, p, d, open_c, hospitals):
    now = X.now
    on = s <= now < e
    notes = [c for c in open_c if c.stage in ("Note Pending", "Documentation")]
    recent_call = p.last_call_end if p else None
    return {
        "physician_id": pid, "name": X.name(pid), "kind": kind,
        "shift_start": iso(s), "shift_end": iso(e), "shift_label": f"{hm(s)}–{hm(e)}", "on_shift": on,
        "minutes_to_shift_end": minutes_between(now, e) if on else None,
        "self_reported_status": p.status if p else "Available",
        "desktop_agent": "Online" if (p is None or p.agent_online) else "Offline",
        "camera": bool(p and p.camera), "synapse_session": bool(p and (p.calls or p.video)),
        "derived_state": d["derived_state"] if on else ("Off shift" if now >= e else d["derived_state"]),
        "busy": d["busy"], "unavailable": d["unavailable"], "flags": d["flags"],
        "activity_consult": d["activity_consult"],
        "ringing": p.ringing if p else None,
        "recent_call_end": iso(recent_call),
        "consults_this_shift": len(p.consults) if p else 0, "calls_this_shift": p.calls_count if p else 0,
        "open_consults": len(open_c), "open_consult_ids": [c.consult_id for c in open_c],
        "open_notes": len(notes), "credentialed": sorted(hospitals),
        "last_answer": iso(p.last_answer) if p and p.last_answer else None,
        "routable_now": on and not d["busy"] and not d["unavailable"] and not (p and p.ringing)
        and not (recent_call and (now - recent_call).total_seconds() < ROUTING["recent_call_block_min"] * 60),
        "verified": p is None or p.agent_online,
    }


def build_off_shift(X: Ctx) -> list[dict]:
    joined = {o["physician_id"] for o in X.joiners}
    out = []
    for r in X.ds.off_roster:
        out.append({**{k: v for k, v in r.items()}, "credentialed": sorted(X.ds.cred.get(r["physician_id"], set())),
                    "joined_split_shift": r["physician_id"] in joined})
    return out


# ---------------------------------------------------------------------------------
# Consults and timers
# ---------------------------------------------------------------------------------
def evaluate_timers(c: Consult, now: datetime) -> list[dict]:
    res = []
    for s in STANDARDS:
        if c.stage not in s["stages"]:
            continue
        if s["applies"] != "All" and s["applies"].lower() != c.consult_type.lower():
            continue
        start = c.stage_entered_at if s["clock"] == "stage" else (c.clinical_end_at or c.stage_entered_at)
        mins = minutes_between(start, now) or 0
        level = "critical" if mins >= s["critical"] else "warning" if mins >= s["warning"] else "ok"
        res.append({"standard": s["key"], "label": s["label"], "minutes": mins, "warning": s["warning"],
                    "critical": s["critical"], "level": level, "clock_start": iso(start),
                    "minutes_to_next": (s["warning"] - mins) if level == "ok" else
                    (s["critical"] - mins) if level == "warning" else 0})
    return res


def build_consults(X: Ctx, pmap: dict) -> list[dict]:
    out = []
    for c in X.consults.values():
        if c.stage == "Signed Off":
            continue
        timers = evaluate_timers(c, X.now)
        level = "critical" if any(t["level"] == "critical" for t in timers) else \
            "warning" if any(t["level"] == "warning" for t in timers) else "ok"
        ph = pmap.get(c.physician_id or "")
        out.append({
            "consult_id": c.consult_id, "hospital_id": c.hospital_id, "hospital_name": X.hname(c.hospital_id),
            "physician_id": c.physician_id, "physician_name": X.name(c.physician_id) if c.physician_id else None,
            "consult_type": c.consult_type, "current_stage": c.stage, "stage_entered_at": iso(c.stage_entered_at),
            "minutes_in_stage": minutes_between(c.stage_entered_at, X.now),
            "minutes_since_received": minutes_between(c.received_at, X.now), "received_at": iso(c.received_at),
            "clinical_end_at": iso(c.clinical_end_at), "timers": timers, "level": level,
            "routing_failures": c.routing_failures, "ringing_to": c.ringing_to,
            "repeat_calls": c.repeat_calls, "last_repeat_at": iso(c.last_repeat_at),
            "physician_state": ph["derived_state"] if ph else None,
            "physician_unavailable": bool(ph and ph["unavailable"]),
            "physician_off_shift": bool(c.physician_id and (not ph or not ph["on_shift"]) and c.stage != "Signed Off"),
            "physician_shift_end": ph["shift_end"] if ph else None,
            "history": [[s, iso(t)] for s, t in c.history],
            "reassigned_by_command_center": any(a[2] == "command-center" for a in c.assignments),
        })
    out.sort(key=lambda c: ({"critical": 0, "warning": 1, "ok": 2}[c["level"]], c["consult_id"]))
    return out


def build_demand(X: Ctx) -> list[dict]:
    out = []
    for hid in X.ds.hospitals:
        n = X.trailing(hid, X.now)
        mean, p90 = X.baseline(hid, X.now)
        lo = X.now - timedelta(minutes=SPIKE_WINDOW_MIN)
        ids = [c.consult_id for c in X.consults.values() if c.hospital_id == hid and c.received_at
               and lo < c.received_at <= X.now]
        out.append({"hospital_id": hid, "hospital_name": X.hname(hid), "trailing_60": int(round(n)),
                    "mean": mean, "p90": p90, "spike": n > p90, "consult_ids": sorted(ids),
                    "hour": X.now.strftime("%H:00")})
    return out


# ---------------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------------
def capacity_members(X: Ctx, pmap: dict, hid: str, t: datetime, joiners: list[dict]) -> list[dict]:
    A = X.A
    members = []
    for p in pmap.values():
        pid = p["physician_id"]
        if p["kind"] != "scheduled" or hid not in X.ds.cred.get(pid, set()):
            continue
        s, e = parse_ts(p["shift_start"]), parse_ts(p["shift_end"])
        if not (s <= t < e):
            continue
        if p["unavailable"] and (A["unavailable_persists"] or t == X.now):
            continue
        members.append({"physician_id": pid, "kind": "on_shift", "verified": p["verified"]})
    if A["count_scheduled_starts"]:
        for r in X.ds.off_roster:
            pid = r["physician_id"]
            ns = parse_ts(r.get("next_shift_start"))
            if pid in pmap or not ns or hid not in X.ds.cred.get(pid, set()):
                continue
            on = ns + timedelta(minutes=int(float(r.get("est_minutes_to_online") or 0)))
            if on <= t < ns + timedelta(hours=A["scheduled_shift_hours"]):
                members.append({"physician_id": pid, "kind": "scheduled_start", "verified": True})
    for o in joiners:
        if hid in o["hospitals"] and parse_ts(o["effective_start"]) <= t < parse_ts(o["end"]):
            members.append({"physician_id": o["physician_id"], "kind": "split_shift", "verified": True})
    return members


def is_spike(trailing: float, p90: float, actual: bool) -> bool:
    """Actual counts compare directly with p90. Projected counts (known arrivals + expected baseline) must
    round above p90, so a fractional expectation alone never manufactures a surge."""
    return trailing > p90 if actual else math.floor(trailing + 0.5) > p90


def build_coverage(X: Ctx, pmap: dict, slots: list[datetime], joiners: list[dict]) -> list[dict]:
    rows = []
    for hid in X.ds.hospitals:
        cells = []
        for t in slots:
            base, block = X.requirement(hid, t)
            trailing = X.trailing(hid, t)
            p90 = X.baseline(hid, t)[1]
            spike = is_spike(trailing, p90, t == X.now)
            required = base + (1 if spike else 0)
            mem = capacity_members(X, pmap, hid, t, joiners)
            avail = len(mem)
            cells.append({"t": iso(t), "required": required, "base_required": base, "block": block,
                          "spike": spike, "trailing_60": round(trailing, 2), "p90": p90, "available": avail,
                          "unverified": sum(1 for m in mem if not m["verified"]),
                          "members": mem, "margin": avail - required,
                          "status": "gap" if avail < required else "at_min" if avail == required else "ok"})
        rows.append({"hospital_id": hid, "hospital_name": X.hname(hid),
                     "tier": X.ds.hospitals[hid].get("coverage_tier", ""), "cells": cells})
    return rows


def build_routing_gaps(X: Ctx, pmap: dict, consults: list[dict], coverage: list[dict]) -> list[dict]:
    """A gap that exists right now at the routing level: demand is waiting and no credentialed on-shift
    physician is routable under the brief's routing rules."""
    gaps = []
    covnow = {r["hospital_id"]: r["cells"][0] for r in coverage}
    for hid in X.ds.hospitals:
        waiting = [c for c in consults if c["hospital_id"] == hid and (
            (c["physician_id"] is None and c["current_stage"] in ("Received", "Triaged") and not c["ringing_to"])
            or (c["physician_unavailable"] and c["current_stage"] in ("Assigned",)))]
        if not waiting:
            continue
        cands = [p for p in pmap.values() if hid in p["credentialed"] and p["on_shift"]]
        routable = [p for p in cands if p["routable_now"]]
        verified_routable = [p for p in routable if p["verified"]]
        if verified_routable:
            continue
        required = covnow[hid]["required"]
        pending = [o for o in X.joiners if hid in o["hospitals"] and parse_ts(o["effective_start"]) > X.now]
        deficit = max(0, required - len(verified_routable))
        remaining = max(0, deficit - len(pending))
        why = []
        for p in cands:
            if p["unavailable"]:
                why.append(f"{p['name']}: Temporarily Unavailable")
            elif p["busy"]:
                why.append(f"{p['name']}: busy ({p['derived_state']})")
            elif p["ringing"]:
                why.append(f"{p['name']}: phone already ringing")
            elif not p["verified"]:
                why.append(f"{p['name']}: looks available but presence agent offline (unverified)")
            else:
                why.append(f"{p['name']}: ended a call < {ROUTING['recent_call_block_min']} min ago")
        gaps.append({
            "id": f"gap:{hid}:routing", "type": "routing", "hospital_id": hid, "hospital_name": X.hname(hid),
            "start": iso(X.now), "end": None, "required": required, "available": len(verified_routable),
            "unverified": len(routable) - len(verified_routable), "deficit": deficit, "remaining": remaining,
            "pending_joiners": [{"physician_id": o["physician_id"], "name": X.name(o["physician_id"]),
                                 "online_at": o["effective_start"]} for o in pending],
            "waiting_consults": [c["consult_id"] for c in waiting], "credentialed_on_shift": why,
            "spike": covnow[hid]["spike"],
        })
    return gaps


def build_roster_gaps(X: Ctx, coverage: list[dict]) -> list[dict]:
    gaps = []
    step = timedelta(minutes=X.A["step_min"])
    for row in coverage:
        run = []
        for cell in row["cells"] + [None]:
            if cell and cell["status"] == "gap":
                run.append(cell)
                continue
            if run:
                start, last = parse_ts(run[0]["t"]), parse_ts(run[-1]["t"])
                deficit = max(c["required"] - c["available"] for c in run)
                end = last + step
                pending = [o for o in X.joiners if row["hospital_id"] in o["hospitals"]
                           and start <= parse_ts(o["effective_start"]) <= end]
                gaps.append({
                    "id": f"gap:{row['hospital_id']}:roster:{start.strftime('%H%M')}", "type": "roster",
                    "hospital_id": row["hospital_id"], "hospital_name": row["hospital_name"],
                    "start": iso(start), "end": iso(end), "required": max(c["required"] for c in run),
                    "available": min(c["available"] for c in run), "deficit": deficit,
                    "remaining": max(0, deficit - len(pending)),
                    "spike": any(c["spike"] for c in run), "now": start <= X.now,
                    "pending_joiners": [{"physician_id": o["physician_id"], "name": X.name(o["physician_id"]),
                                         "online_at": o["effective_start"]} for o in pending], "waiting_consults": [],
                    "credentialed_on_shift": [],
                })
                run = []
    return gaps


def build_incidents(X: Ctx, routing: list[dict], roster: list[dict]) -> list[dict]:
    incidents = []
    if routing:
        incidents.append(_incident(X, "inc:now", "Routing gap now", routing, X.now, None))
    by_start: dict[str, list] = {}
    for g in roster:
        if any(r["hospital_id"] == g["hospital_id"] for r in routing) and g["now"]:
            continue
        by_start.setdefault(g["start"], []).append(g)
    for start, gs in sorted(by_start.items()):
        st = parse_ts(start)
        end = max(parse_ts(g["end"]) for g in gs)
        incidents.append(_incident(X, f"inc:{st.strftime('%H%M')}",
                                   "Coverage gap now" if st <= X.now else f"Projected gap from {hm(st)}",
                                   gs, st, end))
    return incidents


def _incident(X, iid, title, gaps, start, end):
    remaining = {g["hospital_id"]: g["remaining"] for g in gaps}
    offers = [o for o in X.offers if o.get("incident_id") == iid]
    return {"id": iid, "title": title, "start": iso(start), "end": iso(end),
            "hospitals": [g["hospital_id"] for g in gaps], "hospital_names": [g["hospital_name"] for g in gaps],
            "gaps": [g["id"] for g in gaps], "deficit": {g["hospital_id"]: g["deficit"] for g in gaps},
            "remaining": remaining, "open": any(v > 0 for v in remaining.values()),
            "offers": [o["id"] for o in offers]}


# ---------------------------------------------------------------------------------
# Detect: ranked attention items with reasons
# ---------------------------------------------------------------------------------
SEV = {"critical": 100, "warning": 60, "info": 25}


def _det(id, kind, sev, title, why, *, hospital=None, consult=None, physician=None, horizon="now",
         stroke=False, bonus=0, category="consult"):
    score = SEV[sev] + (20 if stroke else 0) + (10 if horizon == "now" else 0) + bonus
    return {"id": id, "kind": kind, "severity": sev, "title": title, "why": why, "hospital_id": hospital,
            "consult_id": consult, "physician_id": physician, "horizon": horizon, "stroke": stroke,
            "score": round(score, 1), "category": category}


def build_detections(X, pmap, consults, demand, coverage, routing_gaps, roster_gaps, physicians):
    D = []
    now = X.now
    for c in consults:
        stroke = c["consult_type"].lower() == "stroke"
        for t in c["timers"]:
            if t["level"] == "ok":
                if t["minutes_to_next"] <= 5:
                    D.append(_det(f"soon:{c['consult_id']}:{t['standard']}", "breach_soon", "info",
                                  f"{c['consult_id']} reaches warning in {t['minutes_to_next']} min",
                                  [f"{t['label']}: {t['minutes']} min (warning at {t['warning']}).",
                                   f"{c['consult_type']} at {c['hospital_name']}."],
                                  hospital=c["hospital_id"], consult=c["consult_id"], physician=c["physician_id"],
                                  horizon=f"+{t['minutes_to_next']}m", stroke=stroke))
                continue
            over = t["minutes"] - (t["critical"] if t["level"] == "critical" else t["warning"])
            why = [f"{t['label']}: {t['minutes']} min vs {t['warning']}/{t['critical']} min standard "
                   f"({'critical' if t['level'] == 'critical' else 'warning'}).",
                   f"{c['consult_type']} consult at {c['hospital_name']}, stage '{c['current_stage']}'."]
            if c["physician_id"]:
                why.append(f"Assigned to {c['physician_name']} ({c['physician_state']}).")
            else:
                why.append("No physician assigned.")
            if c["routing_failures"]:
                why.append(f"Routing failed {c['routing_failures']}× (no available credentialed provider).")
            D.append(_det(f"breach:{c['consult_id']}:{t['standard']}", "breach", t["level"],
                          f"{c['consult_id']} · {t['label']}", why, hospital=c["hospital_id"],
                          consult=c["consult_id"], physician=c["physician_id"], stroke=stroke,
                          bonus=min(15, over / 2) + (8 if not c["physician_id"] else 0)))
        if c["physician_unavailable"] and c["current_stage"] in ("Assigned", "Provider Contacted"):
            ph = pmap[c["physician_id"]]
            D.append(_det(f"conflict:{c['consult_id']}:unavailable", "assigned_unavailable",
                          "critical" if stroke else "warning",
                          f"{c['consult_id']} assigned to a Temporarily Unavailable physician",
                          [f"{c['physician_name']} self-reported Temporarily Unavailable while this "
                           f"{c['consult_type']} consult is still '{c['current_stage']}'.",
                           "Two system signals contradict each other: routing assigned it, the physician is away."],
                          hospital=c["hospital_id"], consult=c["consult_id"], physician=ph["physician_id"],
                          stroke=stroke, bonus=12, category="signal"))
        if c["ringing_to"]:
            ph = pmap.get(c["ringing_to"])
            if ph and not ph["verified"]:
                D.append(_det(f"conflict:{c['consult_id']}:ring_unverified", "unverified_routing", "warning",
                              f"{c['consult_id']} ringing to a physician whose presence is unverified",
                              [f"Call is ringing to {ph['name']}, whose desktop presence agent is offline.",
                               "Routing assumes available, but camera/activity state is unknown."],
                              hospital=c["hospital_id"], consult=c["consult_id"], physician=ph["physician_id"],
                              category="signal"))
    # end-of-shift open notes
    for p in physicians:
        if not p["on_shift"] or p["minutes_to_shift_end"] is None:
            continue
        if p["minutes_to_shift_end"] <= END_OF_SHIFT_WINDOW_MIN and p["open_notes"] >= 1:
            sev = "critical" if p["open_notes"] >= 2 else "warning"
            D.append(_det(f"eos:{p['physician_id']}", "end_of_shift", sev,
                          f"{p['name']} ends shift in {p['minutes_to_shift_end']} min with "
                          f"{p['open_notes']} open note(s)",
                          [f"Shift ends {hm(parse_ts(p['shift_end']))}; {p['open_consults']} open consults "
                           f"({', '.join(p['open_consult_ids'])}).",
                           f"Standard: any open note within {END_OF_SHIFT_WINDOW_MIN} min of shift end = warning,"
                           f" 2 or more = critical."],
                          physician=p["physician_id"], horizon=f"+{p['minutes_to_shift_end']}m",
                          bonus=p["open_consults"] * 3, category="physician"))
        for f in p["flags"]:
            if f["code"] in ("external_platform", "agent_offline", "status_conflict"):
                D.append(_det(f"signal:{p['physician_id']}:{f['code']}", f["code"], "warning",
                              f"{p['name']}: " + {"external_platform": "camera active, no Synapse session",
                                                   "agent_offline": "looks available, presence agent offline",
                                                   "status_conflict": "status contradicts activity"}[f["code"]],
                              [f["message"], f"Self-reported: {p['self_reported_status']}; agent "
                                             f"{p['desktop_agent']}; derived: {p['derived_state']}."],
                              physician=p["physician_id"], category="signal", bonus=-10))
    for d in demand:
        if d["spike"]:
            D.append(_det(f"spike:{d['hospital_id']}", "demand_spike", "warning",
                          f"Demand surge at {d['hospital_name']}: {d['trailing_60']} consults in 60 min",
                          [f"Trailing 60-min consults {d['trailing_60']} vs p90 baseline {d['p90']:g} "
                           f"(mean {d['mean']:g}) for the {d['hour']} hour.",
                           "Brief: a demand spike raises the coverage requirement by one.",
                           f"Consults: {', '.join(d['consult_ids'])}."],
                          hospital=d["hospital_id"], bonus=min(20, (d["trailing_60"] - d["p90"]) * 3),
                          category="demand"))
    for g in routing_gaps:
        D.append(_det(g["id"], "routing_gap", "critical",
                      f"No routable physician at {g['hospital_name']} with demand waiting",
                      [f"Waiting: {', '.join(g['waiting_consults'])}.",
                       f"Requirement now {g['required']} (incl. surge +1)" if g["spike"] else
                       f"Requirement now {g['required']}.", *g["credentialed_on_shift"]]
                      + ([f"Pending: {j['name']} online {hm(parse_ts(j['online_at']))}" for j in g["pending_joiners"]]),
                      hospital=g["hospital_id"], stroke=True, bonus=10 if g["remaining"] else -40,
                      category="coverage"))
    for g in roster_gaps:
        st = parse_ts(g["start"])
        mins = max(0, minutes_between(now, st) or 0)
        D.append(_det(g["id"], "roster_gap", "critical" if mins <= 60 else "warning",
                      f"{g['hospital_name']}: {g['available']} of {g['required']} credentialed physicians "
                      f"{'now' if mins == 0 else 'from ' + hm(st)}",
                      [f"Projected available {g['available']} vs required {g['required']} from {hm(st)} to "
                       f"{hm(parse_ts(g['end']))}" + (" (surge raises requirement +1)." if g["spike"] else "."),
                       "Counts on-shift credentialed physicians who are not Temporarily Unavailable"
                       + (", plus scheduled shift starts" if X.A["count_scheduled_starts"] else "")
                       + ", plus accepted split shifts."],
                      hospital=g["hospital_id"], horizon="now" if mins == 0 else f"+{mins}m",
                      bonus=g["deficit"] * 8, category="coverage"))
    # zero-margin watch items (coverage exactly at the minimum within the horizon)
    for row in coverage:
        cells = [c for c in row["cells"][1:] if c["status"] == "at_min" and c["spike"]]
        if cells and not any(g["hospital_id"] == row["hospital_id"] for g in roster_gaps):
            c0 = cells[0]
            relies = [m for m in c0["members"] if m["kind"] != "on_shift"]
            D.append(_det(f"watch:{row['hospital_id']}", "zero_margin", "info",
                          f"{row['hospital_name']} at exact minimum during surge from {hm(parse_ts(c0['t']))}",
                          [f"Available {c0['available']} = required {c0['required']} (surge +1); no margin.",
                           *(f"Relies on {X.name(m['physician_id'])} ({m['kind'].replace('_', ' ')})"
                             for m in relies)],
                          hospital=row["hospital_id"], horizon=f"+{minutes_between(now, parse_ts(c0['t']))}m",
                          category="coverage"))
    return D


# ---------------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------------
def reassignment_candidates(X: Ctx, pmap: dict, c: dict) -> list[dict]:
    out = []
    for p in pmap.values():
        if not p["on_shift"] or p["physician_id"] == c["physician_id"]:
            continue
        checks = [
            {"rule": "Credentialed at hospital", "pass": c["hospital_id"] in p["credentialed"]},
            {"rule": "Not Temporarily Unavailable", "pass": not p["unavailable"]},
            {"rule": "Not in a Synapse/external session now", "pass": not p["busy"], "soft": True},
            {"rule": "Presence verified", "pass": p["verified"], "soft": True},
        ]
        hard_ok = all(ch["pass"] for ch in checks if not ch.get("soft"))
        soft_ok = all(ch["pass"] for ch in checks if ch.get("soft"))
        out.append({"physician_id": p["physician_id"], "name": p["name"], "derived_state": p["derived_state"],
                    "open_consults": p["open_consults"], "consults_this_shift": p["consults_this_shift"],
                    "minutes_to_shift_end": p["minutes_to_shift_end"], "checks": checks,
                    "eligible": hard_ok, "ready_now": hard_ok and soft_ok,
                    "summary": "Ready now" if hard_ok and soft_ok else
                    ("Eligible but " + "; ".join(ch["rule"].lower().replace("not ", "currently ")
                                                for ch in checks if not ch["pass"]) if hard_ok else
                     "Not eligible: " + next(ch["rule"] for ch in checks if not ch["pass"] and not ch.get("soft")))})
    out.sort(key=lambda r: (not r["eligible"], not r["ready_now"], -(r["minutes_to_shift_end"] or 0) >= -45,
                            r["open_consults"], r["consults_this_shift"]))
    return out


def build_interventions(X: Ctx, pmap: dict, consults: list[dict], detections: list[dict], incidents):
    cmap = {c["consult_id"]: c for c in consults}
    out: list[dict] = []
    done_consults = set()
    for d in detections:
        cid = d.get("consult_id")
        if d["kind"] in ("breach", "assigned_unavailable") and cid and cid not in done_consults:
            c = cmap[cid]
            unassigned = c["physician_id"] is None
            if unassigned or d["kind"] == "assigned_unavailable" or c["current_stage"] in ("Triaged", "Assigned"):
                done_consults.add(cid)
                cands = reassignment_candidates(X, pmap, c)
                best = next((r for r in cands if r["ready_now"]), next((r for r in cands if r["eligible"]), None))
                stroke = c["consult_type"].lower() == "stroke"
                out.append({
                    "id": f"int:reassign:{cid}", "kind": "reassign", "consult_id": cid,
                    "hospital_id": c["hospital_id"], "approver": "Operations coordinator",
                    "title": f"{'Assign' if unassigned else 'Reassign'} {cid} ({c['consult_type']}, {c['hospital_name']})",
                    "recommendation": (f"Assign to {best['name']} ({best['summary'].lower()})" if best else
                                       "No credentialed on-shift physician is eligible — escalate and cover with a "
                                       "split shift"),
                    "target_physician_id": best["physician_id"] if best else None,
                    "candidates": cands, "detection_ids": [x["id"] for x in detections if x.get("consult_id") == cid],
                    "if_approved": (f"{cid} routed to {best['name']}; timer continues against standard."
                                    if best else "—"),
                    "if_rejected": "Routing keeps retrying every 5 minutes; breach grows.",
                    "severity": d["severity"], "stroke": stroke,
                })
                if stroke and d["severity"] == "critical":
                    out.append({
                        "id": f"int:escalate:{cid}", "kind": "escalate", "consult_id": cid,
                        "hospital_id": c["hospital_id"], "approver": "Clinical lead on duty",
                        "title": f"Escalate {cid} to clinical lead",
                        "recommendation": "Authorize escalation: stroke consult past critical standard.",
                        "detection_ids": [x["id"] for x in detections if x.get("consult_id") == cid],
                        "if_approved": "Clinical lead takes ownership of the delay and directs coverage.",
                        "if_rejected": "Delay remains with the coordinator queue.",
                        "severity": "critical", "stroke": True,
                    })
        elif d["kind"] in ("breach",) and cid and cid not in done_consults:
            c = cmap[cid]
            done_consults.add(cid)
            out.append({
                "id": f"int:escalate:{cid}", "kind": "escalate", "consult_id": cid, "hospital_id": c["hospital_id"],
                "approver": "Clinical lead on duty", "title": f"Escalate delay on {cid} ({c['current_stage']})",
                "recommendation": ("Contact the hospital about the imaging delay and confirm the assigned "
                                   "physician can complete before shift end." if "Imaging" in c["current_stage"]
                                   else "Prompt documentation; hand off if the physician cannot finish."),
                "detection_ids": [d["id"]], "if_approved": "Escalation logged and owner notified.",
                "if_rejected": "No change; breach continues.", "severity": d["severity"],
                "stroke": c["consult_type"].lower() == "stroke",
            })
    for d in detections:
        if d["kind"] == "end_of_shift":
            p = pmap[d["physician_id"]]
            items = []
            for cid in p["open_consult_ids"]:
                c = cmap[cid]
                stay = [r for r in reassignment_candidates(X, pmap, c)
                        if r["eligible"] and (r["minutes_to_shift_end"] or 0) > p["minutes_to_shift_end"] + 30]
                items.append({"consult_id": cid, "stage": c["current_stage"], "hospital_name": c["hospital_name"],
                              "suggested": stay[0]["name"] if stay else None,
                              "suggested_id": stay[0]["physician_id"] if stay else None})
            out.append({
                "id": f"int:handoff:{p['physician_id']}", "kind": "handoff", "physician_id": p["physician_id"],
                "approver": "Operations coordinator",
                "title": f"Plan handoff for {p['name']} before {hm(parse_ts(p['shift_end']))}",
                "recommendation": "Finish or hand off open consults to physicians staying on shift.",
                "items": items, "detection_ids": [d["id"]], "severity": d["severity"], "stroke": False,
                "if_approved": "Open work moves before log-off; notes don't strand.",
                "if_rejected": "Open notes may strand past shift end.",
            })
        if d["kind"] in ("external_platform", "agent_offline", "unverified_routing"):
            out.append({
                "id": f"int:verify:{d['id']}", "kind": "verify_signal", "physician_id": d["physician_id"],
                "approver": "Operations coordinator (automated alert)",
                "title": f"Verify presence: {X.name(d['physician_id'])}",
                "recommendation": "Send an internal alert to the coordinator to confirm the physician's real state "
                                  "(low-risk, automated).",
                "detection_ids": [d["id"]], "severity": "warning", "stroke": False,
                "if_approved": "Coordinator confirms; routing assumptions corrected.",
                "if_rejected": "Unverified availability stays in routing.",
            })
    for inc in incidents:
        out.append({
            "id": f"int:split:{inc['id']}", "kind": "split_shift", "incident_id": inc["id"],
            "approver": "Clinical lead on duty", "title": f"Split-shift cover · {inc['title']}",
            "recommendation": "Open the decision card: ranked off-shift physicians with rule-by-rule eligibility.",
            "hospitals": inc["hospitals"], "detection_ids": inc["gaps"], "severity": "critical" if inc["open"] else "info",
            "stroke": True, "open": inc["open"],
            "if_approved": "Approved offer is sent; acceptance updates projected coverage.",
            "if_rejected": "Next eligible candidate proposed, or the gap stays open.",
        })
    return out


def build_corrections(X: Ctx) -> list[dict]:
    out = []
    for d in X.prepared["duplicates"]:
        out.append({"kind": "duplicate", "event_id": d,
                    "message": f"{d} appeared more than once; the extra copy was ignored (de-duplicated on event_id)."})
    for l in X.prepared["late"]:
        lag = l["lag_sec"]
        et, it = parse_ts(l["event_time"]), parse_ts(l["ingested_at"])
        out.append({"kind": "late", "event_id": l["event_id"],
                    "message": f"{l['event_id']} {l['event_type']} for {l['consult_id'] or l['physician_id']} "
                               f"happened {hm(et)}:{et.strftime('%S')} but arrived {hm(it)}:{it.strftime('%S')} "
                               f"({lag // 60}m{lag % 60:02d}s late). Applied at event time; state between those "
                               f"times was corrected retroactively."})
    return out


def build_kpis(X, consults, detections, routing_gaps, roster_gaps, incidents):
    offers = X.offers
    return {
        "open_consults": len(consults),
        "critical_breaches": sum(1 for c in consults if c["level"] == "critical"),
        "warning_breaches": sum(1 for c in consults if c["level"] == "warning"),
        "unassigned": sum(1 for c in consults if not c["physician_id"]),
        "stroke_at_risk": sum(1 for c in consults if c["level"] != "ok" and c["consult_type"].lower() == "stroke"),
        "routing_gaps": sum(1 for g in routing_gaps if g["remaining"] > 0),
        "projected_gaps": len(roster_gaps),
        "open_incidents": sum(1 for i in incidents if i["open"]),
        "awaiting_approval": sum(1 for o in offers if o["status"] == "proposed"),
        "offers_out": sum(1 for o in offers if o["status"] == "sent"),
        "accepted": sum(1 for o in offers if o["status"] == "accepted"),
        "declined": sum(1 for o in offers if o["status"] in ("declined", "timed_out", "rejected")),
        "attention_items": sum(1 for d in detections if d["severity"] != "info"),
    }


def build_insights(physicians: list[dict]) -> list[dict]:
    on = [p for p in physicians if p["on_shift"] and p["kind"] == "scheduled"]
    if len(on) < 3:
        return []
    med_c = statistics.median(p["consults_this_shift"] for p in on)
    med_h = statistics.median(len(p["credentialed"]) for p in on)
    out = []
    for p in on:
        if p["consults_this_shift"] <= 0.6 * med_c and len(p["credentialed"]) < med_h:
            out.append({"physician_id": p["physician_id"], "kind": "credentialing_imbalance",
                        "message": f"{p['name']} has {p['consults_this_shift']} consults vs a median of {med_c:g}. "
                                   f"Credentialed at {len(p['credentialed'])} hospitals vs a median of {med_h:g}: the "
                                   f"imbalance is credentialing, not effort."})
    return out


def build_timeline(X: Ctx) -> dict:
    """Activity lanes (physician) and stage lanes (consult) for the last 3 hours."""
    lo = X.now - timedelta(hours=3)
    lanes = []
    for pid, p in X.r["physicians"].items():
        segs = []
        for kind, cid, st, en in p.segments:
            en2 = en or X.now
            if en2 >= lo:
                segs.append({"kind": kind, "consult_id": cid, "start": iso(max(st, lo)), "end": iso(en2),
                             "open": en is None})
        lanes.append({"physician_id": pid, "name": X.name(pid), "segments": segs})
    stages = []
    for c in X.consults.values():
        if c.stage == "Signed Off" and c.history and c.history[-1][1] < lo:
            continue
        segs = []
        for i, (s, t) in enumerate(c.history):
            en = c.history[i + 1][1] if i + 1 < len(c.history) else X.now
            if en >= lo and s != "Signed Off":
                segs.append({"stage": s, "start": iso(max(t, lo)), "end": iso(en)})
        if segs:
            stages.append({"consult_id": c.consult_id, "hospital_name": X.hname(c.hospital_id),
                           "physician_id": c.physician_id, "consult_type": c.consult_type,
                           "stage": c.stage, "segments": segs})
    return {"start": iso(lo), "end": iso(X.now), "physicians": sorted(lanes, key=lambda l: l["physician_id"]),
            "consults": sorted(stages, key=lambda c: c["consult_id"])}


def snapshot_check(X: Ctx, physicians, consults) -> dict | None:
    ds = X.ds
    if not ds.snapshot_consults and not ds.snapshot_physicians:
        return None
    checks = []
    cmap = {c["consult_id"]: c for c in consults}
    for s in ds.snapshot_consults or []:
        c = cmap.get(s["consult_id"])
        got = None if not c else {
            "physician_id": c["physician_id"] or "Unassigned", "current_stage": c["current_stage"],
            "stage_entered_at": parse_ts(c["stage_entered_at"]).strftime("%H:%M:%S"),
            "minutes_in_stage": str(c["minutes_in_stage"]), "minutes_since_received": str(c["minutes_since_received"])}
        for k in ("physician_id", "current_stage", "stage_entered_at", "minutes_in_stage", "minutes_since_received"):
            checks.append({"entity": s["consult_id"], "field": k, "expected": s.get(k),
                           "actual": got.get(k) if got else None, "ok": bool(got) and str(s.get(k)) == got.get(k)})
    pm = {p["physician_id"]: p for p in physicians if p["kind"] == "scheduled"}
    for s in ds.snapshot_physicians or []:
        p = pm.get(s["physician_id"])
        for k in ("self_reported_status", "desktop_agent", "derived_state", "consults_this_shift",
                  "calls_this_shift", "open_consults", "minutes_to_shift_end"):
            a = None if not p else str(p.get(k))
            checks.append({"entity": s["physician_id"], "field": k, "expected": s.get(k), "actual": a,
                           "ok": a == str(s.get(k))})
    ok = sum(1 for c in checks if c["ok"])
    return {"total": len(checks), "matched": ok, "all_ok": ok == len(checks),
            "mismatches": [c for c in checks if not c["ok"]][:50]}
