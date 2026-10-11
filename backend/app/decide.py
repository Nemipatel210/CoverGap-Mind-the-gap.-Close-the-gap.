"""Split-shift decision card: eligibility per off-shift physician, options with projected impact,
and the routing what-if simulator that addresses the split-shift trap."""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta

from .config import ROUTING, SPLIT_SHIFT
from .datasets import parse_ts
from .engine import Ctx, OPEN_OFFER, build_coverage, hm, iso, is_spike


def offer_window(X: Ctx, inc: dict, hours: float | None = None) -> tuple[datetime, float]:
    start = parse_ts(inc["start"])
    if start <= X.now:
        start = X.now.replace(second=0, microsecond=0)
        start += timedelta(minutes=(5 - start.minute % 5) % 5 or 5)
    if hours is None:
        hours = X.A["default_offer_hours"]
        if inc.get("end"):
            span = (parse_ts(inc["end"]) - start).total_seconds() / 3600
            hours = min(X.A["max_offer_hours"], max(X.A["default_offer_hours"], math.ceil(span * 2) / 2))
    return start, float(hours)


def offers_last_week(X: Ctx, pid: str) -> int:
    lo = datetime.now().astimezone() - timedelta(days=7)
    return sum(1 for o in X.offers if o["physician_id"] == pid and o.get("sent_wall")
               and parse_ts(o["sent_wall"]) >= lo)


def evaluate_candidates(X: Ctx, inc: dict, start: datetime, hours: float, exclude_offer: str | None = None):
    end = start + timedelta(hours=hours)
    need = [h for h, v in inc["remaining"].items() if v > 0] or inc["hospitals"]
    rows = []
    for r in X.ds.off_roster:
        pid = r["physician_id"]
        cred = X.ds.cred.get(pid, set())
        scoped = sorted(set(need) & cred)
        last_end, next_start = parse_ts(r.get("last_shift_end")), parse_ts(r.get("next_shift_start"))
        rest_h = (start - last_end).total_seconds() / 3600 if last_end else None
        accepted_h = sum(o["hours"] for o in X.joiners if o["physician_id"] == pid)
        hrs7 = float(r.get("hours_worked_last_7d") or 0) + accepted_h
        est = int(float(r.get("est_minutes_to_online") or 0))
        overlap_sched = bool(next_start and start < next_start + timedelta(hours=X.A["scheduled_shift_hours"])
                             and next_start < end)
        overlap_split = any(o["physician_id"] == pid and parse_ts(o["start"]) < end and start < parse_ts(o["end"])
                            for o in X.joiners)
        # An open offer for this same gap is the same ask, not a second offer, so it doesn't disqualify.
        open_offer = [o for o in X.offers if o["physician_id"] == pid and o["status"] in OPEN_OFFER
                      and o["id"] != exclude_offer and o.get("incident_id") != inc["id"]]
        week = offers_last_week(X, pid)
        prior = [o for o in X.offers if o["physician_id"] == pid and o.get("incident_id") == inc["id"]
                 and o["status"] in ("declined", "timed_out", "rejected")]
        opted = str(r.get("split_shift_opt_in", "")).strip().lower() in ("yes", "y", "true", "1")
        usable = hours * 60 - est
        need_names = " or ".join(X.hname(h) for h in need)
        first = r["name"].split()[-1] if r.get("name") else pid
        rules = [
            {"rule": "Willing to take extra shifts", "pass": opted,
             "detail": "Opted in" if opted else "Has not opted in",
             "plain": "Hasn't opted in to extra shifts"},
            {"rule": "Approved at a short hospital", "pass": bool(scoped),
             "detail": ", ".join(X.hname(h) for h in scoped) if scoped else "Not approved at " + need_names,
             "plain": f"Not approved at {need_names}"},
            {"rule": f"Rested {SPLIT_SHIFT['min_rest_hours']}h+ by the start",
             "pass": rest_h is not None and rest_h >= SPLIT_SHIFT["min_rest_hours"],
             "detail": f"{rest_h:.1f}h since last shift at {hm(start)}" if rest_h is not None else "Last shift unknown",
             "plain": f"Only {rest_h:.1f}h rest by {hm(start)}" if rest_h is not None else "Last shift unknown"},
            {"rule": f"{SPLIT_SHIFT['max_hours_7d']}h or less in 7 days", "pass": hrs7 + hours <= SPLIT_SHIFT["max_hours_7d"],
             "detail": f"{hrs7:g}h + {hours:g}h = {hrs7 + hours:g}h",
             "plain": f"Would reach {hrs7 + hours:g}h this week ({hrs7:g}h + {hours:g}h)"},
            {"rule": "No clash with own shift", "pass": not overlap_sched and not overlap_split,
             "detail": (f"Own shift starts {next_start.strftime('%a %H:%M')}" if overlap_sched else
                        "Already joining a split shift" if overlap_split else
                        f"Next shift {next_start.strftime('%a %H:%M')}" if next_start else "No next shift"),
             "plain": (f"Own shift starts {hm(next_start)}; that already counts as cover" if overlap_sched and next_start
                       else "Already joining a split shift")},
            {"rule": f"Worth {SPLIT_SHIFT['min_offer_hours']}h+ after getting online",
             "pass": usable >= SPLIT_SHIFT["min_offer_hours"] * 60,
             "detail": f"{hours:g}h offer − {est} min to get online = {usable / 60:.1f}h",
             "plain": f"Needs {est} min to get online, so the {hours:g}h offer is worth only {usable / 60:.1f}h"},
            {"rule": "No other open offer", "pass": not open_offer,
             "detail": f"Open offer {open_offer[0]['id']}" if open_offer else "None open",
             "plain": "Already has an open offer"},
            {"rule": f"Under {SPLIT_SHIFT['max_offers_per_week']} offers this week",
             "pass": week < SPLIT_SHIFT["max_offers_per_week"], "detail": f"{week} sent in last 7 days",
             "plain": f"Already had {week} offers this week"},
        ]
        failed = [x for x in rules if not x["pass"]]
        if overlap_sched and next_start and start <= next_start < end:
            reason_note = "A scheduled shift start is not a split-shift offer; it already counts toward coverage."
        else:
            reason_note = None
        rows.append({
            "physician_id": pid, "name": r["name"], "role": r.get("role"), "eligible": not failed,
            "failed_rules": [x["rule"] for x in failed], "rules": rules, "scoped_hospitals": scoped,
            "scoped_hospital_names": [X.hname(h) for h in scoped], "est_minutes_to_online": est,
            "online_at": iso(start + timedelta(minutes=est)), "hours_last_7d": hrs7,
            "declined_30d": int(float(r.get("offers_declined_last_30d") or 0)), "offers_this_week": week,
            "preferred_channel": r.get("preferred_channel"), "previously_declined_this_gap": bool(prior),
            "reason": "Passes every rule" if not failed else ". ".join(x["plain"] for x in failed) + ".",
            "summary": "Eligible" if not failed else f"Fails: {failed[0]['rule']}"
            + (f" (+{len(failed) - 1} more)" if len(failed) > 1 else ""), "note": reason_note,
        })
    return rows


def rank(rows: list[dict], mode: str) -> list[dict]:
    def key(r):
        base = (not r["eligible"], r["previously_declined_this_gap"], -len(r["scoped_hospitals"]))
        if mode == "lightest_load":
            return base + (r["hours_last_7d"], r["est_minutes_to_online"])
        if mode == "fewest_offers":
            return base + (r["offers_this_week"], r["declined_30d"], r["est_minutes_to_online"])
        return base + (r["est_minutes_to_online"], r["hours_last_7d"])
    rows = sorted(rows, key=key)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ---------------------------------------------------------------------------------
# Split-shift trap: what-if routing simulation
# ---------------------------------------------------------------------------------
def simulate(X: Ctx, pmap: dict, gap_hosps: list[str], joiner: dict | None, start: datetime, end: datetime,
             scope: str = "all", seed: int = 0) -> dict:
    A = X.A
    svc = timedelta(minutes=A["sim_service_min"])
    docs = []
    for p in pmap.values():
        if p["kind"] != "scheduled":
            continue
        s, e = parse_ts(p["shift_start"]), parse_ts(p["shift_end"])
        if e <= start or p["unavailable"]:
            continue
        busy_until = X.now + svc / 2 if p["busy"] else X.now
        docs.append({"id": p["physician_id"], "cred": set(p["credentialed"]), "s": s, "e": e,
                     "n": p["consults_this_shift"], "busy": busy_until, "last": parse_ts(p["last_answer"]) or s,
                     "night": False, "joiner": False, "got": 0, "got_gap": 0})
    for o in X.joiners:
        docs.append({"id": o["physician_id"], "cred": set(o["hospitals"]), "s": parse_ts(o["effective_start"]),
                     "e": parse_ts(o["end"]), "n": o.get("policy", {}).get("seed", 0), "busy": X.now,
                     "last": parse_ts(o["effective_start"]), "joiner": False, "got": 0, "got_gap": 0})
    if A["count_scheduled_starts"]:
        for r in X.ds.off_roster:
            ns = parse_ts(r.get("next_shift_start"))
            if ns and start <= ns < end:
                docs.append({"id": r["physician_id"], "cred": X.ds.cred.get(r["physician_id"], set()), "s": ns,
                             "e": ns + timedelta(hours=A["scheduled_shift_hours"]), "n": 0, "busy": ns, "last": ns,
                             "joiner": False, "got": 0, "got_gap": 0})
    if joiner:
        cred = X.ds.cred.get(joiner["physician_id"], set())
        docs.append({"id": joiner["physician_id"], "cred": (cred & set(gap_hosps)) if scope == "gap" else cred,
                     "s": parse_ts(joiner["online_at"]), "e": end, "n": seed, "busy": parse_ts(joiner["online_at"]),
                     "last": parse_ts(joiner["online_at"]), "joiner": True, "got": 0, "got_gap": 0})
    # deterministic arrivals from baseline (p90 while a hospital is projected to be in surge, else mean)
    arrivals = []
    for hid in X.ds.hospitals:
        acc, t = 0.5, start
        while t < end:
            mean, p90 = X.baseline(hid, t)
            rate = p90 if is_spike(X.trailing(hid, t), p90, False) else mean
            acc += rate * 5 / 60
            while acc >= 1:
                arrivals.append((t, hid))
                acc -= 1
            t += timedelta(minutes=5)
    arrivals.sort()
    failed = {"gap": 0, "other": 0}
    waits = []
    queue = list(arrivals)
    while queue:
        t, hid = queue.pop(0)
        if t >= end:
            failed["gap" if hid in gap_hosps else "other"] += 1
            continue
        elig = [d for d in docs if d["s"] <= t < d["e"] and hid in d["cred"] and d["busy"] <= t]
        if not elig:
            queue.append((t + timedelta(minutes=ROUTING["retry_min"]), hid))
            queue.sort()
            continue
        thr = ROUTING["low_volume_night"] if (t.hour >= ROUTING["night_start_hour"] or
                                              t.hour < ROUTING["day_start_hour"]) else ROUTING["low_volume_day"]
        low = [d for d in elig if d["n"] <= thr]
        pool = low or elig
        d = min(pool, key=lambda d: (d["n"], d["last"]))
        d["n"] += 1
        d["got"] += 1
        d["got_gap"] += hid in gap_hosps
        d["busy"] = t + svc
        d["last"] = t
        if hid in gap_hosps:
            waits.append(0)
    j = next((d for d in docs if d["joiner"]), None)
    others = [d["got"] for d in docs if not d["joiner"] and d["got"]]
    return {"arrivals": len(arrivals), "joiner_total": j["got"] if j else 0,
            "joiner_gap": j["got_gap"] if j else 0, "joiner_other": (j["got"] - j["got_gap"]) if j else 0,
            "unrouted_gap": failed["gap"], "unrouted_other": failed["other"],
            "peer_avg": round(statistics.mean(others), 1) if others else 0}


def plan(X: Ctx, pmap: dict, inc: dict, mode: str, hours: float | None = None) -> dict:
    start, hours = offer_window(X, inc, hours)
    end = start + timedelta(hours=hours)
    cands = rank(evaluate_candidates(X, inc, start, hours), mode)
    top = next((c for c in cands if c["eligible"]), None)
    need = [h for h, v in inc["remaining"].items() if v > 0]
    sim_rows, recommended = [], None
    if top:
        med = int(statistics.median([p["consults_this_shift"] for p in pmap.values() if p["kind"] == "scheduled"]
                                    or [0]))
        seed_combined = ROUTING["low_volume_day"] + 1
        policies = [
            ("naive", "Naive start", "all", 0, "Joins with zero consults at every credentialed hospital."),
            ("seeded", "Seeded count", "all", med, f"Starting count seeded to the on-shift median ({med})."),
            ("scoped", "Gap hospitals only", "gap", 0, "Routing limited to the gap hospitals."),
            ("combined", "Scoped + seeded", "gap", seed_combined,
             f"Gap hospitals only, seeded to {seed_combined} (above the low-volume priority threshold) so the "
             f"joiner shares, not absorbs, gap calls."),
        ]
        base = simulate(X, pmap, need, None, parse_ts(top["online_at"]), end)
        for key, label, scope, seed, desc in policies:
            s = simulate(X, pmap, need, top, parse_ts(top["online_at"]), end, scope, seed)
            sim_rows.append({"policy": key, "label": label, "scope": scope, "seed": seed, "description": desc, **s})
        for r in sim_rows:
            r["unrouted_gap_relief"] = base["unrouted_gap"] - r["unrouted_gap"]
        recommended = min(sim_rows, key=lambda r: (r["unrouted_gap"], r["joiner_other"],
                                                   abs(r["joiner_total"] - r["peer_avg"]),
                                                   0 if r["policy"] == "combined" else 1))["policy"]
        baseline_sim = base
    else:
        baseline_sim = None
    # projected impact with and without the top candidate
    impact = None
    if top:
        hyp = {"physician_id": top["physician_id"], "hospitals": top["scoped_hospitals"],
               "effective_start": top["online_at"], "end": iso(end), "start": iso(start), "hours": hours}
        slots = [X.now + timedelta(minutes=X.A["step_min"] * i) for i in range(X.A["horizon_min"] // X.A["step_min"] + 1)]
        before = {r["hospital_id"]: r for r in build_coverage(X, pmap, slots, X.joiners)}
        after = {r["hospital_id"]: r for r in build_coverage(X, pmap, slots, X.joiners + [hyp])}
        impact = {"slots": [iso(s) for s in slots], "hospitals": []}
        for hid in top["scoped_hospitals"]:
            impact["hospitals"].append({
                "hospital_id": hid, "hospital_name": X.hname(hid),
                "required": [c["required"] for c in before[hid]["cells"]],
                "before": [c["available"] for c in before[hid]["cells"]],
                "after": [c["available"] for c in after[hid]["cells"]]})
    rem_after = {h: max(0, v - (1 if top and h in top["scoped_hospitals"] else 0)) for h, v in inc["remaining"].items()}
    still_open = [X.hname(h) for h, v in rem_after.items() if v > 0]
    next_cand = next((c for c in cands if c["eligible"] and top and c["physician_id"] != top["physician_id"]), None)
    options = []
    if top:
        options.append({
            "key": "split_shift", "title": f"Split shift: {top['name']}",
            "why": f"Only {sum(1 for c in cands if c['eligible'])} of {len(cands)} off-shift physicians pass every "
                   f"rule. Credentialed at {', '.join(top['scoped_hospital_names'])}.",
            "if_approved": f"Offer sent ({hm(start)}–{hm(end)}, {hours:g}h). Online ≈{hm(parse_ts(top['online_at']))} "
                           f"(+{top['est_minutes_to_online']} min). "
                           + (f"Still short at {', '.join(still_open)}." if still_open else "Gap closes at all "
                                                                                             "scoped hospitals."),
            "if_rejected": (f"Next eligible: {next_cand['name']}." if next_cand else
                            "No other eligible off-shift physician — gap stays open; escalate."),
            "recommended": True})
    options.append({
        "key": "reassign_escalate", "title": "Reassign stranded work & escalate",
        "why": "Moves waiting/at-risk consults to physicians who stay on shift; relieves current breaches.",
        "if_approved": "Breaches relieved where a credentialed physician frees up; adds no new capacity.",
        "if_rejected": "Breaches continue; capacity gap unaffected.", "recommended": not top})
    options.append({
        "key": "no_action", "title": "Take no action",
        "why": "Avoids contacting anyone off shift.",
        "if_approved": "No extra load on anyone.",
        "if_rejected": "—",
        "risk": f"{', '.join(X.hname(h) for h in need) or 'Gap hospitals'} stay below minimum coverage."})
    return {"incident": inc, "offer": {"start": iso(start), "end": iso(end), "hours": hours,
                                       "hospitals": need, "hospital_names": [X.hname(h) for h in need]},
            "ranking_mode": mode, "candidates": cands, "top": top, "options": options, "simulation": sim_rows,
            "simulation_baseline": baseline_sim, "recommended_policy": recommended, "impact": impact,
            "eligible_count": sum(1 for c in cands if c["eligible"])}
