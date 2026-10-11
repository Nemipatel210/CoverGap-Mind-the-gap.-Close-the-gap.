"""Problems: the handbook's four questions for every issue.

Detections are merged so each consult, hospital or doctor appears once, with:
  what      - what is going on (one sentence)
  where     - hospital / consult / doctor
  matters   - why it matters: time waited against the limit, and whether it gets worse soon
  fix       - the one recommended action, who approves it, and why it beats the alternatives
"""
from __future__ import annotations

from datetime import timedelta

from .datasets import parse_ts
from .decide import plan
from .engine import hm

SEV_BASE = {"critical": 100, "warning": 60, "info": 25}
STAGE_PLAIN = {
    "Received": "waiting to be triaged", "Triaged": "waiting for a doctor", "Assigned": "waiting for the doctor to be reached",
    "Provider Contacted": "doctor reached", "CT/CTA or Imaging Pending": "waiting for scans",
    "Imaging Review": "scans back, video not started", "Video Consult In Progress": "on video",
    "Note Pending": "note not started", "Documentation": "note being written",
}


def _short(name: str | None) -> str:
    return name or "—"


def build_problems(v: dict, wf: dict, mode: str = "fastest") -> list[dict]:
    X = v["_ctx"]
    now = X.now
    pmap = {p["physician_id"]: p for p in v["physicians"]}
    hname = X.hname
    routing = {g["hospital_id"]: g for g in v["routing_gaps"]}
    roster = {}
    for g in v["roster_gaps"]:
        roster.setdefault(g["hospital_id"], g)
    demand = {d["hospital_id"]: d for d in v["demand"]}
    ints = {i["id"]: i for i in v["interventions"]}
    plans = {}
    for inc in v["incidents"]:
        if inc["open"]:
            try:
                plans[inc["id"]] = plan(X, pmap, inc, mode)
            except Exception:  # noqa: BLE001 - a plan failure must never hide the problem list
                pass

    def cover_for(hid: str):
        """Best split-shift plan whose eligible doctor is approved at this hospital."""
        for iid, p in plans.items():
            if hid in p["incident"]["hospitals"] and p["top"] and hid in p["top"]["scoped_hospitals"]:
                return p
        for iid, p in plans.items():
            if hid in p["incident"]["hospitals"]:
                return p
        return None

    def open_offer_for(hid: str):
        return next((o for o in X.offers if o["status"] in ("proposed", "sent") and hid in o.get("hospitals", [])), None)

    def offer_fix(o: dict, hid: str) -> dict:
        return {"kind": "split_shift", "label": f"Call in {o['physician_name']} for an extra shift", "approver": "Clinical lead",
                "incident_id": o["incident_id"], "target_physician_id": o["physician_id"],
                "why": f"Offer to {o['physician_name']} for {', '.join(o['hospital_names'])} is in progress; "
                       f"they'd be online by {hm(parse_ts(o['effective_start']))}."}

    def leaving_soon(hid: str, within: int = 90):
        out = []
        for p in pmap.values():
            if p["on_shift"] and hid in p["credentialed"] and p["minutes_to_shift_end"] is not None \
                    and p["minutes_to_shift_end"] <= within and p["kind"] == "scheduled":
                out.append(p)
        return out

    problems: list[dict] = []

    # ------------------------------------------------------------------ consults
    for c in v["consults"]:
        stroke = c["consult_type"].lower() == "stroke"
        bad_timers = [t for t in c["timers"] if t["level"] != "ok"]
        unassigned = not c["physician_id"]
        waiting = unassigned and c["current_stage"] in ("Received", "Triaged") and not c["ringing_to"]
        rg = routing.get(c["hospital_id"]) if (waiting or c["physician_unavailable"]) else None
        ph = pmap.get(c["physician_id"] or "")
        ring_unverified = bool(c["ringing_to"] and pmap.get(c["ringing_to"]) and not pmap[c["ringing_to"]]["verified"])
        if not (bad_timers or c["physician_unavailable"] or rg or c["repeat_calls"] or ring_unverified
                or (waiting and c["routing_failures"])):
            continue
        sev = "critical" if any(t["level"] == "critical" for t in bad_timers) else "warning" if bad_timers else "info"
        if (rg and stroke) or (c["physician_unavailable"] and stroke):
            sev = "critical"
        elif rg or c["physician_unavailable"] or c["repeat_calls"]:
            sev = "critical" if sev == "critical" else "warning"
        ctype = c["consult_type"]
        stage = STAGE_PLAIN.get(c["current_stage"], c["current_stage"])
        if waiting and rg:
            what = f"{ctype} patient waiting and nobody approved at {c['hospital_name']} is free"
        elif waiting:
            what = f"{ctype} patient waiting for a doctor"
        elif c["physician_unavailable"]:
            what = f"{ctype} consult is assigned to a doctor who is unavailable"
        elif ring_unverified and not bad_timers:
            what = f"New {ctype.lower()} call is ringing to a doctor who may not be at their desk"
        elif c["current_stage"] in ("Note Pending", "Documentation"):
            what = f"{ctype} note is overdue"
        else:
            what = f"{ctype} consult stuck: {stage}"
        matters = []
        for t in bad_timers or c["timers"][:1]:
            matters.append(f"{t['minutes']} min at this step; limit {t['warning']} min (warning) / {t['critical']} min (critical).")
        if c["minutes_since_received"] is not None and not c["current_stage"] in ("Note Pending", "Documentation"):
            matters.append(f"Hospital has been waiting {c['minutes_since_received']} min in total.")
        if c["repeat_calls"]:
            matters.append(f"Hospital asked again {c['repeat_calls']}× about this patient (last {hm(parse_ts(c['last_repeat_at']))}). "
                           f"Same patient: clock still runs from the first request.")
        if c["routing_failures"] and waiting:
            matters.append(f"Automatic routing failed {c['routing_failures']}× and retries every 5 min.")
        if rg:
            matters.append("Approved there: " + "; ".join(rg["credentialed_on_shift"]) + "." if rg["credentialed_on_shift"]
                           else f"No doctor on shift is approved at {c['hospital_name']}.")
        if c["physician_unavailable"] and ph:
            matters.append(f"{ph['name']} set Temporarily Unavailable while this consult is still theirs.")
        if ring_unverified:
            matters.append(f"{pmap[c['ringing_to']]['name']}'s desktop helper app is offline, so we can't confirm they're there.")
        if ph and ph["on_shift"] and ph["minutes_to_shift_end"] is not None and ph["minutes_to_shift_end"] <= 60:
            matters.append(f"{ph['name']}'s shift ends at {hm(parse_ts(ph['shift_end']))}.")
        d = demand.get(c["hospital_id"])
        if d and d["spike"]:
            matters.append(f"{c['hospital_name']} is surging: {d['trailing_60']} consults in the last hour vs a normal busy level of {d['p90']:g}.")
        rgap = roster.get(c["hospital_id"])
        if rgap:
            matters.append(f"It gets worse: {c['hospital_name']} drops to {rgap['available']} of {rgap['required']} doctors at {hm(parse_ts(rgap['start']))}.")

        # ---- choose the one fix
        reassign = ints.get(f"int:reassign:{c['consult_id']}")
        ready = next((r for r in (reassign or {}).get("candidates", []) if r["ready_now"]), None) if reassign else None
        if not ready and (waiting or c["physician_unavailable"] or (ph and ph["busy"] and c["current_stage"] in ("Imaging Review", "Assigned"))):
            from .engine import reassignment_candidates
            cands = reassignment_candidates(X, pmap, c)
            ready = next((r for r in cands if r["ready_now"]), None)
        alternatives = []
        fix = None
        needs_doctor = waiting or c["physician_unavailable"] or (
            stroke and c["current_stage"] in ("Assigned", "Imaging Review") and ph and (ph["busy"] or ph["unavailable"]))
        if needs_doctor and ready:
            fix = {"kind": "assign", "label": f"Assign to {ready['name']}", "approver": "Coordinator",
                   "target_physician_id": ready["physician_id"],
                   "why": f"{ready['name']} is approved at {c['hospital_name']} and free now "
                          f"({ready['open_consults']} open consults, {ready['minutes_to_shift_end']} min left on shift). "
                          f"Fastest way to get this patient seen."}
            alternatives.append("Escalate to the clinical lead if the assignment doesn't land within the limit.")
        elif needs_doctor and open_offer_for(c["hospital_id"]):
            fix = offer_fix(open_offer_for(c["hospital_id"]), c["hospital_id"])
            alternatives.append("Escalate to the clinical lead now, in parallel, so someone owns this patient meanwhile.")
        elif needs_doctor and rg and rg["pending_joiners"]:
            j = rg["pending_joiners"][0]
            fix = {"kind": "joining", "label": f"{j['name']} joins at {hm(parse_ts(j['online_at']))}; route this patient to them",
                   "approver": "—", "target_physician_id": j["physician_id"],
                   "why": f"{j['name']} accepted an extra shift covering {c['hospital_name']} and will be the first free "
                          f"approved doctor there."}
            alternatives.append("Escalate to the clinical lead if the patient can't wait until then.")
        elif needs_doctor:
            pl = cover_for(c["hospital_id"])
            top = pl["top"] if pl else None
            if top and c["hospital_id"] in top["scoped_hospitals"]:
                fix = {"kind": "split_shift", "label": f"Call in {top['name']} for an extra shift",
                       "approver": "Clinical lead", "incident_id": pl["incident"]["id"],
                       "target_physician_id": top["physician_id"],
                       "why": f"Nobody approved at {c['hospital_name']} is free. {top['name']} is the only off-duty doctor "
                              f"who passes every rule" if pl["eligible_count"] == 1 else
                              f"Nobody approved at {c['hospital_name']} is free. {top['name']} passes every rule and is the "
                              f"fastest of {pl['eligible_count']} eligible"}
                fix["why"] += f", and can be online by {hm(parse_ts(top['online_at']))}."
                alternatives.append("Escalate to the clinical lead now, in parallel, so someone owns this patient meanwhile.")
            else:
                fix = {"kind": "escalate", "label": "Escalate to the clinical lead", "approver": "Clinical lead",
                       "why": f"Nobody approved at {c['hospital_name']} is free and no off-duty doctor passes every rule. "
                              f"Escalating is the only safe option; the rules are not bent."}
            busy = [p["name"] for p in pmap.values() if p["on_shift"] and c["hospital_id"] in p["credentialed"] and p["busy"]]
            if busy:
                alternatives.append(f"Wait for {busy[0]} to finish (busy now). Not recommended for a {ctype.lower()} patient.")
        elif ring_unverified and not bad_timers:
            fix = {"kind": "alert", "label": f"Alert: confirm {pmap[c['ringing_to']]['name']} is at their desk",
                   "approver": "Automatic (internal alert)",
                   "why": "Routing assumes this doctor is free, but nothing confirms it. An internal alert is low-risk."}
        elif c["current_stage"] == "CT/CTA or Imaging Pending":
            fix = {"kind": "escalate", "label": "Escalate: chase the hospital for the scans", "approver": "Clinical lead",
                   "why": "The delay is at the hospital's imaging, not with the doctor; the clinical lead can push the hospital."}
            if ph and ph["minutes_to_shift_end"] is not None and ph["minutes_to_shift_end"] <= 60:
                alternatives.append(f"Plan a handoff: {ph['name']} leaves at {hm(parse_ts(ph['shift_end']))}.")
        elif c["current_stage"] in ("Note Pending", "Documentation"):
            fix = {"kind": "alert", "label": f"Remind {_short(c['physician_name'])} to finish the note",
                   "approver": "Automatic (internal alert)",
                   "why": "The clinical part is done; only documentation is late. A reminder is enough."}
        else:
            fix = {"kind": "escalate", "label": "Escalate to the clinical lead", "approver": "Clinical lead",
                   "why": "Past its time limit with the assigned doctor busy and nobody else free."}

        score = SEV_BASE[sev] + (20 if stroke else 0) + 10
        score += min(15, max((t["minutes"] - t["critical"]) / 2 for t in bad_timers) if bad_timers else 0)
        score += (12 if rg else 0) + (8 if waiting else 0) + 15 * c["repeat_calls"] + (6 if c["physician_unavailable"] else 0)
        problems.append({
            "id": f"c:{c['consult_id']}", "kind": "consult", "severity": sev, "stroke": stroke, "score": round(score, 1),
            "what": what, "where": {"hospital_id": c["hospital_id"], "hospital": c["hospital_name"],
                                    "consult": c["consult_id"], "doctor": c["physician_name"]},
            "matters": matters, "fix": fix, "alternatives": alternatives, "horizon": "now",
            "repeat_calls": c["repeat_calls"],
        })

    # ------------------------------------------------------------------ hospitals
    consult_hosp = {p["where"]["hospital_id"] for p in problems if p["fix"]["kind"] == "split_shift"}
    for hid in X.ds.hospitals:
        d = demand.get(hid)
        g = roster.get(hid)
        cov = next((r for r in v["coverage"]["rows"] if r["hospital_id"] == hid), None)
        at_min = [c for c in (cov["cells"][1:] if cov else []) if c["status"] == "at_min" and c["spike"]]
        if not (g or (d and d["spike"])):
            continue
        matters = []
        if d and d["spike"]:
            matters.append(f"{d['trailing_60']} consults in the last hour vs a normal busy level of {d['p90']:g} for this hour "
                           f"(usual average {d['mean']:g}). A surge raises the doctors needed by one.")
        leaving = leaving_soon(hid)
        if g:
            st = parse_ts(g["start"])
            mins = max(0, int((st - now).total_seconds() // 60))
            what = (f"{hname(hid)} is short of approved doctors now" if mins == 0
                    else f"{hname(hid)} will be short of approved doctors at {hm(st)}")
            matters.insert(0, f"{g['available']} of {g['required']} approved doctors from {hm(st)} to {hm(parse_ts(g['end']))}.")
            if leaving:
                matters.append("Leaving: " + ", ".join(f"{p['name']} at {hm(parse_ts(p['shift_end']))}" for p in leaving) + ".")
            sev = "critical" if mins <= 60 else "warning"
            pl = cover_for(hid)
            top = pl["top"] if pl else None
            if open_offer_for(hid):
                fix = offer_fix(open_offer_for(hid), hid)
            elif top and hid in top["scoped_hospitals"]:
                fix = {"kind": "split_shift", "label": f"Call in {top['name']} for an extra shift", "approver": "Clinical lead",
                       "incident_id": pl["incident"]["id"], "target_physician_id": top["physician_id"],
                       "why": f"Adds an approved doctor at {hname(hid)} before the drop. "
                              f"{pl['eligible_count']} of {len(pl['candidates'])} off-duty doctors pass every rule."}
            else:
                fix = {"kind": "escalate", "label": "Escalate to the clinical lead", "approver": "Clinical lead",
                       "why": "No off-duty doctor approved here passes every rule. Escalate rather than bend a rule."}
            horizon = "now" if mins == 0 else f"+{mins}m"
        else:
            what = f"{hname(hid)} is far busier than normal"
            sev = "warning"
            horizon = "now"
            if at_min:
                c0 = at_min[0]
                relies = [X.name(m["physician_id"]) for m in c0["members"] if m["kind"] != "on_shift"]
                matters.append(f"Covered, but at exactly the minimum from {hm(parse_ts(c0['t']))}"
                               + (f": relies on {', '.join(relies)} starting on time." if relies else "."))
            if leaving:
                matters.append("Leaving soon: " + ", ".join(f"{p['name']} at {hm(parse_ts(p['shift_end']))}" for p in leaving) + ".")
            if hid in consult_hosp:
                fix = {"kind": "covered", "label": "Handled by the patient fix above", "approver": "—",
                       "why": "The extra-shift offer for this hospital's waiting patient also covers the surge."}
            else:
                fix = {"kind": "monitor", "label": "Watch; no action yet", "approver": "—",
                       "why": "Enough approved doctors for now. This turns into a coverage problem if a doctor leaves early."}
        score = SEV_BASE[sev] + 10 + (12 if g else 0) + (min(20, (d["trailing_60"] - d["p90"]) * 3) if d and d["spike"] else 0)
        problems.append({"id": f"h:{hid}", "kind": "hospital", "severity": sev, "stroke": bool(g), "score": round(score, 1),
                         "what": what, "where": {"hospital_id": hid, "hospital": hname(hid)}, "matters": matters,
                         "fix": fix, "alternatives": [], "horizon": horizon})

    # ------------------------------------------------------------------ doctors
    insights = {i["physician_id"]: i for i in v["insights"]}
    for p in v["physicians"]:
        if not p["on_shift"]:
            continue
        matters, fix, what, sev, horizon = [], None, None, "info", "now"
        flags = {f["code"]: f for f in p["flags"]}
        eos = p["minutes_to_shift_end"] is not None and p["minutes_to_shift_end"] <= 60 and p["open_notes"] >= 1
        if eos:
            sev = "critical" if p["open_notes"] >= 2 else "warning"
            what = f"{p['name']} leaves at {hm(parse_ts(p['shift_end']))} with {p['open_notes']} unfinished note" + \
                   ("s" if p["open_notes"] > 1 else "")
            matters.append(f"{p['minutes_to_shift_end']} min left; {p['open_consults']} open consults ({', '.join(p['open_consult_ids'])}).")
            matters.append("Limit: any unfinished note within an hour of shift end is a warning; 2 or more is critical.")
            h = ints.get(f"int:handoff:{p['physician_id']}")
            fix = {"kind": "handoff", "label": "Hand off open work before they leave", "approver": "Coordinator",
                   "items": h["items"] if h else [],
                   "why": "Moves open consults to doctors who stay on shift, so notes and patients aren't stranded."}
            horizon = f"+{p['minutes_to_shift_end']}m"
        if "external_platform" in flags:
            what = what or f"{p['name']} looks free but is probably on another video call"
            sev = sev if sev != "info" else "warning"
            matters.append("Camera on, no Synapse call, status says Available: treated as busy.")
            fix = fix or {"kind": "alert", "label": f"Alert: confirm what {p['name']} is doing", "approver": "Automatic (internal alert)",
                          "why": "Their status can't be trusted on its own; a quick internal check settles it."}
        if "agent_offline" in flags:
            what = what or f"Can't confirm {p['name']} is at their desk"
            sev = sev if sev != "info" else "warning"
            matters.append("Desktop helper app went quiet, so the camera state is unknown. Routing still treats them as free.")
            if p["ringing"]:
                matters.append(f"A call is ringing to them now ({p['ringing']}).")
            fix = fix or {"kind": "alert", "label": f"Alert: confirm {p['name']} is available", "approver": "Automatic (internal alert)",
                          "why": "Unverified availability is a risk for incoming stroke calls; an internal check is low-risk."}
        if "status_conflict" in flags:
            what = what or f"{p['name']}'s status contradicts their activity"
            matters.append(flags["status_conflict"]["message"])
            fix = fix or {"kind": "alert", "label": f"Alert: confirm {p['name']}'s status", "approver": "Automatic (internal alert)",
                          "why": "Signals disagree."}
        if p["physician_id"] in insights:
            matters.append(insights[p["physician_id"]]["message"])
            if not what:
                what = f"{p['name']}'s light workload is caused by credentialing, not effort"
                fix = {"kind": "monitor", "label": "No action needed", "approver": "—",
                       "why": "They can only take calls from the hospitals they're approved at."}
        if not what:
            continue
        score = SEV_BASE[sev] + (10 if horizon == "now" else 0) + p["open_consults"] * 3
        problems.append({"id": f"d:{p['physician_id']}", "kind": "doctor", "severity": sev, "stroke": False,
                         "score": round(score, 1), "what": what,
                         "where": {"doctor": p["name"], "physician_id": p["physician_id"]},
                         "matters": matters, "fix": fix, "alternatives": [], "horizon": horizon})

    # ------------------------------------------------------------------ status from the workflow
    for pr in problems:
        pr["status"] = action_status(pr, wf, X)
    problems.sort(key=lambda p: (-p["score"], p["id"]))
    for i, p in enumerate(problems, 1):
        p["rank"] = i
    return problems


def action_status(pr: dict, wf: dict, X) -> dict | None:
    """What has already been done about this problem (so the button changes to a status)."""
    esc = [e for e in wf.get("escalations", []) if e.get("problem_id") == pr["id"]]
    if esc:
        e = esc[-1]
        return {"state": "escalated" if e["status"] == "pending" else e["status"],
                "label": {"pending": "Escalated · waiting for the clinical lead", "authorized": "Escalation authorized",
                          "rejected": "Escalation rejected by the clinical lead"}[e["status"]]}
    alerts = [a for a in wf.get("alerts", []) if a["problem_id"] == pr["id"]]
    fix = pr["fix"]
    if fix["kind"] == "joining":
        return {"state": "accepted", "label": fix["label"].split(";")[0]}
    if fix["kind"] == "split_shift":
        offers = [o for o in X.offers if o.get("incident_id") == fix.get("incident_id")
                  or (pr["where"].get("hospital_id") in o.get("hospitals", []) and o["status"] == "accepted")]
        if offers:
            o = sorted(offers, key=lambda o: o["id"])[-1]
            label = {"proposed": f"Offer to {o['physician_name']} waiting for the clinical lead",
                     "sent": f"Offer sent to {o['physician_name']} · waiting for reply",
                     "accepted": f"{o['physician_name']} accepted · online {o['effective_start'][11:16]}",
                     "declined": f"{o['physician_name']} declined", "timed_out": f"{o['physician_name']} didn't reply",
                     "rejected": "Clinical lead rejected the offer", "not_needed": "Already covered",
                     "withdrawn": "Offer withdrawn (gap filled)"}.get(o["status"], o["status"])
            return {"state": o["status"], "label": label, "offer_id": o["id"]}
    if alerts:
        return {"state": "alerted", "label": f"Alert sent {alerts[-1]['time'][11:16]}"}
    return None
