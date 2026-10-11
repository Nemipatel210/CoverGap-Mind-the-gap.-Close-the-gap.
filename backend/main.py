"""Sevaro Tele-Neurology Operations Command Center — FastAPI backend (hackathon prototype).

Run:  uvicorn main:app --reload --port 8000
All data is synthetic. Not a clinical decision-support system. Demo logins only (see app/auth.py).
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Literal

from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.service import ApiError, Service, init_reference
from app import auth, storage

storage.ensure_dirs()
init_reference()
svc = Service()


@contextlib.asynccontextmanager
async def lifespan(_app):
    async def ticker():
        while True:
            await asyncio.sleep(5)
            try:
                svc.expire_offers()
            except Exception:  # noqa: BLE001
                pass
    task = asyncio.create_task(ticker())
    yield
    task.cancel()


app = FastAPI(title="Sevaro Operations Command Center API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every /api call needs a login, and each role may only do its own job (see app/auth.py)."""
    path, method = request.url.path, request.method
    if not path.startswith("/api") or method == "OPTIONS" or (method, path) in auth.OPEN:
        return await call_next(request)
    h = request.headers.get("authorization", "")
    user = auth.lookup(h[7:] if h.lower().startswith("bearer ") else None)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Please sign in."})
    if not auth.allowed(user, method, path):
        return JSONResponse(status_code=403, content={"error": f"A {user['title'].lower()} can't do that."})
    token = auth.current.set(user)
    try:
        return await call_next(request)
    finally:
        auth.current.reset(token)


def who(fallback: str) -> str:
    """The signed-in person is the actor in the audit log (the admin test account may name one)."""
    u = auth.current.get()
    return fallback if (u is None or u["role"] == "admin") else u["name"]


def me() -> dict:
    return auth.current.get() or {}


@app.exception_handler(ApiError)
async def api_error(_req: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"error": exc.message})


# ----------------------------------------------------------------------------- models
class Actor(BaseModel):
    actor: str = Field("Ops Coordinator", max_length=80)


class ProposeOffer(Actor):
    incident_id: str
    physician_id: str
    hours: float | None = None
    policy: str | None = None


class Decision(Actor):
    note: str | None = None


class Respond(BaseModel):
    physician_id: str = ""
    action: Literal["accept", "decline"]


class Reassign(Actor):
    physician_id: str


class Escalate(Actor):
    intervention_id: str
    note: str | None = None


class EscalationDecision(Actor):
    decision: Literal["authorize", "reject"]
    note: str | None = None


class LoadReq(Actor):
    mode: Literal["replace", "append_events"] = "replace"
    label: str | None = None


class EventIn(Actor):
    event_id: str | None = None
    event_time: str
    ingested_at: str | None = None
    consult_id: str | None = ""
    event_type: str
    physician_id: str | None = ""
    hospital_id: str | None = ""
    description: str | None = ""


class LoginReq(BaseModel):
    username: str
    password: str


# ----------------------------------------------------------------------------- auth
@app.post("/api/auth/login")
def login(req: LoginReq):
    r = auth.login(svc.ds, req.username, req.password)
    if not r:
        raise ApiError(401, "Wrong username or password.")
    return r


@app.get("/api/auth/accounts")
def demo_accounts():
    """Demo only: lets the login screens prefill the three kinds of account."""
    docs = auth.doctor_accounts(svc.ds)
    return {"password": auth.DEMO_PASSWORD,
            "staff": [{"username": u, **a} for u, a in auth.STAFF.items()],
            "doctors": [{"username": u, "name": a["name"], "physician_id": a["physician_id"]} for u, a in docs.items()],
            "default_doctor": next(iter(docs), None)}


@app.get("/api/auth/me")
def whoami():
    return me()


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(None)):
    auth.logout(authorization[7:] if authorization else None)
    return {"ok": True}


# ----------------------------------------------------------------------------- read
@app.get("/api/health")
def health():
    v = svc.view()
    return {"status": "ok", "dataset": v["dataset"], "as_of": v["as_of"], "version": svc.version}


@app.get("/api/meta")
def meta():
    v = svc.view()
    return {"dataset": v["dataset"], "as_of": v["as_of"], "as_of_label": v["as_of_label"], "version": svc.version,
            "stats": v["stats"], "kpis": v["kpis"],
            "hospitals": [{"hospital_id": h, "hospital_name": r["hospital_name"], "tier": r.get("coverage_tier"),
                           "timezone": r.get("local_timezone")} for h, r in svc.ds.hospitals.items()],
            "off_shift": [{"physician_id": r["physician_id"], "name": r["name"]} for r in svc.ds.off_roster],
            "on_shift": [{"physician_id": r["physician_id"], "name": r["name"]} for r in svc.ds.on_shift]}


@app.get("/api/dashboard")
def dashboard():
    v = svc.view()
    p = svc.prefs["coordinator"]
    det = v["detections"]
    if p["hospitals"]:
        det = [d for d in det if not d.get("hospital_id") or d["hospital_id"] in p["hospitals"]]
    det = [d for d in det if d["severity"] in p["severities"]]
    return {"as_of": v["as_of"], "as_of_label": v["as_of_label"], "dataset": v["dataset"], "kpis": v["kpis"],
            "detections": det, "interventions": v["interventions"], "incidents": v["incidents"],
            "routing_gaps": v["routing_gaps"], "roster_gaps": v["roster_gaps"], "demand": v["demand"],
            "coverage": v["coverage"], "corrections": v["corrections"], "insights": v["insights"],
            "stats": v["stats"], "preferences": p}


@app.get("/api/problems")
def problems():
    v = svc.view()
    return {"as_of": v["as_of"], "as_of_label": v["as_of_label"], "dataset": v["dataset"], "problems": v["problems"],
            "summary": _summary(v), "data": {"events": v["stats"]["events_unique"], "late": v["stats"]["late_events"],
                                             "duplicates": len(v["stats"]["duplicates"]), "corrections": v["corrections"]},
            "next90": _next90(v)}


def _summary(v):
    pr = v["problems"]
    return {"critical": sum(1 for p in pr if p["severity"] == "critical"),
            "stroke_waiting": sum(1 for c in v["consults"] if not c["physician_id"] and c["consult_type"].lower() == "stroke"),
            "short_now": sum(1 for g in v["routing_gaps"] if g["remaining"] > 0),
            "short_soon": len(v["roster_gaps"]),
            "awaiting_approval": v["kpis"]["awaiting_approval"], "offers_out": v["kpis"]["offers_out"]}


def _next90(v):
    """Hospitals that are short, or only just covered, in the look-ahead window."""
    out = []
    for r in v["coverage"]["rows"]:
        worst = min(r["cells"], key=lambda c: (c["margin"], c["t"]))
        if worst["margin"] > 0:
            continue
        first = next(c for c in r["cells"] if c["margin"] == worst["margin"])
        if first["margin"] == 0 and not first["spike"]:
            continue  # at the minimum without a surge is normal; showing it would just be noise
        out.append({"hospital_id": r["hospital_id"], "hospital": r["hospital_name"], "at": first["t"],
                    "available": first["available"], "required": first["required"], "short": first["margin"] < 0,
                    "surge": first["spike"]})
    return sorted(out, key=lambda x: (not x["short"], x["at"]))


@app.post("/api/problems/{pid}/escalate")
def problem_escalate(pid: str, req: Decision):
    return svc.escalate_problem(pid, who(req.actor), req.note)


@app.post("/api/problems/{pid}/alert")
def problem_alert(pid: str, req: Actor):
    return svc.alert_problem(pid, who(req.actor))


@app.post("/api/events/upload")
async def upload_events(file: UploadFile = File(...), actor: str = Form("Ops Coordinator")):
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise ApiError(413, "File is larger than 20 MB.")
    return svc.upload_events(file.filename or "events.csv", raw, who(actor))


@app.get("/api/consults")
def consults():
    v = svc.view()
    return {"as_of": v["as_of"], "consults": v["consults"], "timeline": v["timeline"]}


@app.get("/api/physicians")
def physicians():
    v = svc.view()
    return {"as_of": v["as_of"], "on_shift": v["physicians"], "off_shift": v["off_shift"],
            "hospitals": [{"hospital_id": h, "hospital_name": r["hospital_name"]} for h, r in svc.ds.hospitals.items()],
            "insights": v["insights"]}


@app.get("/api/coverage")
def coverage():
    v = svc.view()
    return {"as_of": v["as_of"], "coverage": v["coverage"], "routing_gaps": v["routing_gaps"],
            "roster_gaps": v["roster_gaps"], "incidents": v["incidents"], "demand": v["demand"],
            "assumptions": svc.assumptions}


@app.get("/api/incidents/{incident_id}/plan")
def incident_plan(incident_id: str, mode: str | None = None, hours: float | None = None):
    return svc.split_plan(incident_id, mode, hours)


@app.get("/api/snapshot-check")
def snapshot_check():
    return svc.snapshot_check() or {"total": 0, "matched": 0, "all_ok": None, "mismatches": [],
                                    "message": "No reference snapshot in the active dataset."}


# ----------------------------------------------------------------------------- act
@app.get("/api/offers")
def offers(physician_id: str | None = None, status: str | None = None):
    svc.expire_offers()
    o = svc.wf["offers"]
    if me().get("role") == "doctor":
        physician_id = me()["physician_id"]
        status = status or "sent,accepted,declined,timed_out,not_needed,withdrawn"
    if physician_id:
        o = [x for x in o if x["physician_id"] == physician_id]
    if status:
        o = [x for x in o if x["status"] in status.split(",")]
    esc = [] if me().get("role") == "doctor" else svc.wf["escalations"]
    return {"offers": sorted(o, key=lambda x: x["id"], reverse=True), "escalations": esc}


@app.post("/api/offers")
def propose(req: ProposeOffer):
    return svc.propose_offer(req.incident_id, req.physician_id, who(req.actor), req.hours, req.policy)


@app.post("/api/offers/{oid}/approve")
def approve(oid: str, req: Decision):
    return svc.approve_offer(oid, who(req.actor), req.note)


@app.post("/api/offers/{oid}/reject")
def reject(oid: str, req: Decision):
    return svc.reject_offer(oid, who(req.actor), req.note)


@app.post("/api/offers/{oid}/respond")
def respond(oid: str, req: Respond):
    pid = me()["physician_id"] if me().get("role") == "doctor" else req.physician_id
    return svc.respond_offer(oid, req.action, pid)


@app.post("/api/offers/{oid}/expire")
def expire(oid: str, req: Actor):
    return svc.expire_offer(oid, who(req.actor))


@app.post("/api/consults/{cid}/reassign")
def reassign(cid: str, req: Reassign):
    return svc.reassign(cid, req.physician_id, who(req.actor))


@app.post("/api/escalations")
def escalate(req: Escalate):
    return svc.create_escalation(req.intervention_id, who(req.actor), req.note)


@app.post("/api/escalations/{eid}/decide")
def decide_escalation(eid: str, req: EscalationDecision):
    return svc.decide_escalation(eid, req.decision, who(req.actor), req.note)


@app.post("/api/interventions/{iid}/alert")
def alert(iid: str, req: Actor):
    return svc.verify_alert(iid, who(req.actor))


@app.get("/api/notifications")
def notifications(audience: str | None = None, physician_id: str | None = None):
    if me().get("role") == "doctor":
        audience, physician_id = "physician", me()["physician_id"]
    n = svc.notifications(audience, physician_id)
    return {"notifications": n[:100], "unread": sum(1 for x in n if not x["read"])}


@app.post("/api/notifications/read")
def read_notifications(nid: str | None = None, audience: str | None = None):
    svc.mark_read(nid, audience)
    return {"ok": True}


@app.get("/api/activity")
def activity(actor: str | None = None, action: str | None = None, entity: str | None = None,
             q: str | None = None, limit: int = 300):
    a = storage.read_json("activity_log.json", [])
    if actor:
        a = [x for x in a if x["actor"] == actor]
    if action:
        a = [x for x in a if x["action"] == action]
    if entity:
        a = [x for x in a if x["entity"] == entity]
    if q:
        ql = q.lower()
        a = [x for x in a if ql in str(x).lower()]
    return {"activity": a[:limit], "total": len(a)}


# ----------------------------------------------------------------------------- settings
@app.get("/api/config")
def config():
    return {**svc.rules(), "preferences": svc.prefs}


@app.put("/api/preferences/{role}")
def put_prefs(role: str, data: dict[str, Any]):
    return svc.set_prefs(role, data)


@app.put("/api/config/assumptions")
def put_assumptions(data: dict[str, Any]):
    actor = data.pop("actor", "Ops Coordinator")
    return svc.set_assumptions(data, who(actor))


# ----------------------------------------------------------------------------- datasets
@app.get("/api/datasets/types")
def dataset_types():
    return {"types": svc.dataset_types(), "active": {"label": svc.ds.label, **svc.manifest},
            "staging": svc.staging()}


@app.get("/api/datasets/sample/{dtype}", response_class=PlainTextResponse)
def sample(dtype: str):
    return PlainTextResponse(svc.sample_csv(dtype), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{dtype}.csv"'})


@app.post("/api/datasets/validate")
async def validate(files: list[UploadFile] = File(...), dataset_type: str = Form("auto")):
    payload = []
    for f in files:
        raw = await f.read()
        if len(raw) > 20 * 1024 * 1024:
            raise ApiError(413, f"{f.filename} is larger than 20 MB.")
        payload.append((f.filename or "upload.csv", raw))
    return svc.validate_upload(payload, dataset_type)


@app.get("/api/datasets/composed")
def composed(mode: str = Query("replace")):
    return svc.composed_check(mode)


@app.post("/api/datasets/load")
def load(req: LoadReq):
    return svc.load_staged(req.mode, who(req.actor), req.label)


@app.delete("/api/datasets/staging")
def clear_staging():
    svc.clear_staging()
    return {"ok": True}


@app.post("/api/datasets/reset")
def reset(req: Actor):
    return svc.reset_demo(who(req.actor))


@app.post("/api/events")
def inject(ev: EventIn):
    return svc.inject_event(ev.model_dump(), who(ev.actor))
