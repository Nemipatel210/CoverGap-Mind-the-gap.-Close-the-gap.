"""Demo authentication: three kinds of login, enforced by the API.

Prototype only: fixed demo passwords, bearer tokens kept in a local JSON file. Not production auth.
  coordinator   - operations coordinator: sees everything, proposes offers, reassigns, escalates, loads data
  clinical_lead - approves or rejects offers and authorizes escalations
  doctor        - an off-duty physician: sees and answers only their own offers (the /m phone view)
An `admin` account exists for API testing and has every permission.
"""
from __future__ import annotations

import contextvars
import os
import secrets

from . import storage

DEMO_PASSWORD = "demo1234"
ADMIN_PASSWORD = os.environ.get("SEVARO_ADMIN_PASSWORD", "admin-demo")

STAFF = {
    "coordinator": {"role": "coordinator", "name": "Ops Coordinator", "title": "Operations coordinator"},
    "lead": {"role": "clinical_lead", "name": "Clinical Lead on Duty", "title": "Clinical lead on duty"},
}

current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("current_user", default=None)


def doctor_accounts(ds) -> dict[str, dict]:
    """One login per off-shift physician in the active dataset; username = surname, lower-case."""
    out: dict[str, dict] = {}
    for r in ds.off_roster:
        base = (r["name"].split()[-1] if r.get("name") else r["physician_id"]).lower().strip(".")
        user = base if base not in out else f"{base}-{r['physician_id'].lower()}"
        out[user] = {"role": "doctor", "name": r["name"], "title": "Off-duty physician", "physician_id": r["physician_id"]}
    return out


def accounts(ds) -> dict[str, dict]:
    return {**STAFF, **doctor_accounts(ds)}


def login(ds, username: str, password: str) -> dict | None:
    u = (username or "").strip().lower()
    if u == "admin" and password == ADMIN_PASSWORD:
        acct = {"role": "admin", "name": "API admin", "title": "Admin"}
    else:
        acct = accounts(ds).get(u)
        if not acct or password != DEMO_PASSWORD:
            return None
    token = secrets.token_urlsafe(24)
    sessions = storage.read_json("sessions.json", {})
    sessions[token] = {**acct, "username": u}
    storage.write_json("sessions.json", sessions)
    return {"token": token, **sessions[token]}


def lookup(token: str | None) -> dict | None:
    if not token:
        return None
    return storage.read_json("sessions.json", {}).get(token)


def logout(token: str | None) -> None:
    sessions = storage.read_json("sessions.json", {})
    if token and sessions.pop(token, None) is not None:
        storage.write_json("sessions.json", sessions)


# --------------------------------------------------------------------------- permissions
# (method, path prefix) -> roles allowed. First match wins. Unlisted /api paths need a staff login.
OPEN = {("GET", "/api/health"), ("POST", "/api/auth/login"), ("GET", "/api/auth/accounts")}
LEAD_ONLY = ("/approve", "/reject", "/decide")
DOCTOR_ALLOWED = [("GET", "/api/auth/me"), ("POST", "/api/auth/logout"), ("GET", "/api/offers"),
                  ("POST", "/api/offers/", "/respond"), ("POST", "/api/offers/", "/call"), ("GET", "/api/notifications"), ("POST", "/api/notifications/read"),
                  ("GET", "/api/meta")]


def allowed(user: dict, method: str, path: str) -> bool:
    role = user["role"]
    if role == "admin":
        return True
    if role == "doctor":
        for rule in DOCTOR_ALLOWED:
            if rule[0] == method and path.startswith(rule[1]) and (len(rule) < 3 or path.endswith(rule[2])):
                return True
        return False
    if path.endswith(("/respond", "/call")):
        return False  # only the doctor the offer was sent to answers it
    if method == "GET" or path.startswith(("/api/auth/", "/api/notifications/read")):
        return True
    lead_action = path.startswith(("/api/offers/", "/api/escalations/", "/api/plans/")) and path.endswith(LEAD_ONLY)
    if role == "clinical_lead":
        return lead_action
    if role == "coordinator":
        return not lead_action
    return False
