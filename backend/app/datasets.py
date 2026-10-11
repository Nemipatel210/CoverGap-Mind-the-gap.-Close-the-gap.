"""Dataset schemas, parsing, validation and the in-memory Dataset object.

Nothing here knows about specific physicians, hospitals, dates or record counts:
everything is derived from the files.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ET

ID_HOSP = re.compile(r"^[A-Za-z0-9_-]+$")

SCHEMAS: dict[str, dict[str, Any]] = {
    "event_stream": {
        "label": "Event stream", "required": True, "key": "event_id",
        "columns": ["event_id", "event_time", "ingested_at", "consult_id", "event_type", "physician_id",
                    "hospital_id", "description"],
        "timestamps": ["event_time", "ingested_at"], "nonnull": ["event_id", "event_time", "event_type"],
        "description": "Source of truth. One row per system event; event_time + ingested_at with UTC offsets.",
    },
    "hospitals": {
        "label": "Hospitals", "required": True, "key": "hospital_id",
        "columns": ["hospital_id", "hospital_name", "local_timezone", "coverage_tier"],
        "nonnull": ["hospital_id", "hospital_name"],
        "description": "Hospitals with local time zone and coverage tier.",
    },
    "physicians_on_shift": {
        "label": "Physicians on shift", "required": True, "key": "physician_id",
        "columns": ["physician_id", "name", "shift_start_et", "shift_end_et", "split_shift_opt_in"],
        "hhmm": ["shift_start_et", "shift_end_et"], "nonnull": ["physician_id", "name"],
        "description": "Physicians currently on shift with ET shift times.",
    },
    "physicians_off_shift_roster": {
        "label": "Off-shift roster", "required": True, "key": "physician_id",
        "columns": ["physician_id", "name", "role", "split_shift_opt_in", "last_shift_end", "next_shift_start",
                    "hours_worked_last_7d", "est_minutes_to_online", "preferred_channel",
                    "offers_declined_last_30d"],
        "timestamps": ["last_shift_end", "next_shift_start"],
        "ints": ["hours_worked_last_7d", "est_minutes_to_online", "offers_declined_last_30d"],
        "nonnull": ["physician_id", "name"],
        "description": "Off-shift physicians: opt-in, last/next shift, hours worked, time to come online.",
    },
    "credentialing_matrix": {
        "label": "Credentialing matrix", "required": True, "key": "physician_id",
        "columns": ["physician_id", "name"], "dynamic_hospital_columns": True,
        "nonnull": ["physician_id"],
        "description": "One column per hospital ID; 'Y' means credentialed.",
    },
    "baseline_hourly_volume": {
        "label": "Baseline hourly volume", "required": True, "key": None,
        "columns": ["hospital_id", "hospital_name", "dow_type", "hour_start_et", "mean_consults",
                    "p90_consults", "weeks_sampled"],
        "hhmm": ["hour_start_et"], "floats": ["mean_consults", "p90_consults"],
        "nonnull": ["hospital_id", "hour_start_et"],
        "description": "Weekday mean and p90 consults per hospital per hour.",
    },
    "coverage_requirements": {
        "label": "Coverage requirements", "required": True, "key": None,
        "columns": ["hospital_id", "hospital_name", "time_block_et", "min_available_credentialed_physicians"],
        "ints": ["min_available_credentialed_physicians"], "nonnull": ["hospital_id", "time_block_et"],
        "description": "Minimum available credentialed physicians per hospital per time block.",
    },
    "snapshot_open_consults": {
        "label": "Reference snapshot: open consults", "required": False, "key": "consult_id",
        "columns": ["consult_id", "hospital_id", "hospital_name", "physician_id", "consult_type", "current_stage",
                    "stage_entered_at", "minutes_in_stage", "minutes_since_received"],
        "nonnull": ["consult_id"],
        "description": "Optional. Used only to verify that the replay reproduces the reference state.",
    },
    "snapshot_physicians": {
        "label": "Reference snapshot: physicians", "required": False, "key": "physician_id",
        "columns": ["physician_id", "name", "shift_et", "self_reported_status", "desktop_agent", "derived_state",
                    "consults_this_shift", "calls_this_shift", "open_consults", "minutes_to_shift_end"],
        "nonnull": ["physician_id"],
        "description": "Optional. Used only to verify that the replay reproduces the reference state.",
    },
}

KNOWN_EVENT_TYPES = {
    "consult_received", "consult_triaged", "physician_assigned", "incoming_call_ringing",
    "incoming_call_started", "incoming_call_ended", "outgoing_call_started", "outgoing_call_ended",
    "imaging_requested", "imaging_returned", "video_started", "video_ended", "note_started", "note_signed",
    "routing_attempt_failed", "physician_status_changed", "camera_active", "camera_inactive",
    "agent_heartbeat_lost", "agent_heartbeat_restored", "shift_started", "shift_ended",
}


def guess_type(filename: str, columns: list[str] | None = None) -> str | None:
    name = filename.lower()
    for t in sorted(SCHEMAS, key=len, reverse=True):
        if t in name:
            return t
    if "snapshot" in name and "consult" in name:
        return "snapshot_open_consults"
    if "snapshot" in name and "physician" in name:
        return "snapshot_physicians"
    if "off_shift" in name or "roster" in name:
        return "physicians_off_shift_roster"
    if "on_shift" in name:
        return "physicians_on_shift"
    if columns:
        cols = set(columns)
        best, score = None, 0
        for t, s in SCHEMAS.items():
            sc = len(cols & set(s["columns"])) / len(s["columns"])
            if sc > score:
                best, score = t, sc
        if score >= 0.8:
            return best
    return None


def read_table(raw: bytes, filename: str) -> pd.DataFrame:
    """Parse CSV or JSON (array of records, or {"records": [...]}) into strings."""
    if not raw or not raw.strip():
        raise ValueError("File is empty.")
    if filename.lower().endswith(".json"):
        data = json.loads(raw.decode("utf-8-sig"))
        if isinstance(data, dict):
            for k in ("records", "data", "rows", "items"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError("JSON must be an array of objects, or an object with a 'records' array.")
        df = pd.DataFrame(data)
        return df.astype(object).where(pd.notna(df), None).astype(str).replace({"None": "", "nan": ""})
    if not filename.lower().endswith((".csv", ".txt")):
        raise ValueError("Unsupported file type. Upload a .csv or .json file.")
    return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="utf-8-sig")


def parse_ts(v: str | None) -> datetime | None:
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=ET)
    return d.astimezone(ET)


def valid_hhmm(v: str) -> bool:
    return bool(re.match(r"^\d{1,2}:\d{2}$", str(v).strip()))


def validate_table(dtype: str, df: pd.DataFrame) -> dict[str, Any]:
    """Validate one file in isolation. Returns issues and the cleaned frame (bad rows dropped)."""
    s = SCHEMAS[dtype]
    issues: list[dict[str, Any]] = []
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in s["columns"] if c not in df.columns]
    if missing:
        issues.append({"level": "error", "message": f"Missing required column(s): {', '.join(missing)}"})
        return {"issues": issues, "df": df, "dropped": 0}
    if len(df) == 0:
        issues.append({"level": "error", "message": "The file has a header but no data rows."})
        return {"issues": issues, "df": df, "dropped": 0}
    for c in df.columns:
        df[c] = df[c].fillna("").astype(str).str.strip()
    bad = set()
    for c in s.get("nonnull", []):
        rows = df.index[df[c] == ""].tolist()
        for r in rows[:5]:
            issues.append({"level": "warning", "row": int(r) + 2, "message": f"'{c}' is empty; row skipped"})
        bad.update(rows)
    for c in s.get("timestamps", []):
        rows = [i for i, v in df[c].items() if v and parse_ts(v) is None]
        for r in rows[:5]:
            issues.append({"level": "warning", "row": int(r) + 2,
                           "message": f"'{c}' is not an ISO timestamp ('{df.at[r, c]}'); row skipped"})
        bad.update(rows)
    for c in s.get("hhmm", []):
        rows = [i for i, v in df[c].items() if v and not valid_hhmm(v)]
        for r in rows[:5]:
            issues.append({"level": "warning", "row": int(r) + 2, "message": f"'{c}' must be HH:MM; row skipped"})
        bad.update(rows)
    for c in s.get("ints", []) + s.get("floats", []):
        rows = [i for i, v in df[c].items() if v and pd.to_numeric(v, errors="coerce") != pd.to_numeric(v, errors="coerce")]
        for r in rows[:5]:
            issues.append({"level": "warning", "row": int(r) + 2, "message": f"'{c}' must be numeric; row skipped"})
        bad.update(rows)
    if dtype == "coverage_requirements":
        rows = [i for i, v in df["time_block_et"].items()
                if not re.match(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$", v)]
        for r in rows[:5]:
            issues.append({"level": "warning", "row": int(r) + 2, "message": "time_block_et must be HH:MM-HH:MM"})
        bad.update(rows)
    if dtype == "event_stream":
        unknown = sorted(set(df["event_type"]) - KNOWN_EVENT_TYPES - {""})
        if unknown:
            issues.append({"level": "warning", "message": f"Unknown event types are kept but ignored by the "
                                                         f"state engine: {', '.join(unknown[:6])}"})
    if dtype == "credentialing_matrix":
        hosp_cols = [c for c in df.columns if c not in ("physician_id", "name")]
        if not hosp_cols:
            issues.append({"level": "error", "message": "No hospital columns found in credentialing matrix."})
        for c in hosp_cols:
            odd = sorted(set(df[c].str.upper()) - {"Y", "N", "", "YES", "NO"})
            if odd:
                issues.append({"level": "warning", "message": f"Column {c} has values other than Y/blank: {odd[:3]}"})
    if bad:
        if len(bad) > 5:
            issues.append({"level": "warning", "message": f"{len(bad)} malformed rows will be skipped in total"})
        df = df.drop(index=list(bad))
    key = s.get("key")
    if key and len(df):
        dups = df[df[key].duplicated(keep="first")][key].tolist()
        if dups:
            lvl = "warning" if dtype == "event_stream" else "error"
            msg = (f"Duplicate {key}: {', '.join(sorted(set(dups))[:6])}"
                   + (" (duplicates are de-duplicated on replay)" if lvl == "warning" else ""))
            issues.append({"level": lvl, "message": msg})
    if len(df) == 0:
        issues.append({"level": "error", "message": "No valid rows remain after validation."})
    return {"issues": issues, "df": df.reset_index(drop=True), "dropped": len(bad)}


def cross_validate(tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Referential checks across a full dataset."""
    issues: list[dict[str, Any]] = []
    for t, s in SCHEMAS.items():
        if s["required"] and t not in tables:
            issues.append({"level": "error", "message": f"Required dataset missing: {s['label']}"})
    if issues:
        return issues
    hosp = set(tables["hospitals"]["hospital_id"])
    on = set(tables["physicians_on_shift"]["physician_id"])
    off = set(tables["physicians_off_shift_roster"]["physician_id"])
    cred = tables["credentialing_matrix"]
    cred_ids = set(cred["physician_id"])
    hosp_cols = [c for c in cred.columns if c not in ("physician_id", "name")]
    if on & off:
        issues.append({"level": "error", "message": f"Physicians listed both on and off shift: {sorted(on & off)}"})
    unknown_cols = sorted(set(hosp_cols) - hosp)
    if unknown_cols:
        issues.append({"level": "error", "message": f"Credentialing columns not in hospitals: {unknown_cols}"})
    no_cred = sorted((on | off) - cred_ids)
    if no_cred:
        issues.append({"level": "warning", "message": f"Physicians with no credentialing row (treated as "
                                                       f"credentialed nowhere): {no_cred}"})
    for t in ("baseline_hourly_volume", "coverage_requirements"):
        bad = sorted(set(tables[t]["hospital_id"]) - hosp)
        if bad:
            issues.append({"level": "warning", "message": f"{SCHEMAS[t]['label']} references unknown hospitals {bad}"})
    missing_req = sorted(hosp - set(tables["coverage_requirements"]["hospital_id"]))
    if missing_req:
        issues.append({"level": "warning", "message": f"No coverage requirement for {missing_req}; treated as 0"})
    ev = tables["event_stream"]
    bad_p = sorted(set(ev["physician_id"]) - on - off - cred_ids - {""})
    bad_h = sorted(set(ev["hospital_id"]) - hosp - {""})
    if bad_p:
        issues.append({"level": "warning", "message": f"Events reference unknown physicians {bad_p[:6]}; kept"})
    if bad_h:
        issues.append({"level": "warning", "message": f"Events reference unknown hospitals {bad_h[:6]}; kept"})
    return issues


@dataclass
class Dataset:
    label: str
    hospitals: dict[str, dict]
    on_shift: list[dict]
    off_roster: list[dict]
    cred: dict[str, set]
    names: dict[str, str]
    baseline: dict[tuple, tuple]
    requirements: dict[str, list]
    events: list[dict]
    snapshot_consults: list[dict] | None = None
    snapshot_physicians: list[dict] | None = None
    raw_counts: dict[str, int] = field(default_factory=dict)


def load_dir(path: Path) -> Dataset:
    tables: dict[str, pd.DataFrame] = {}
    for t in SCHEMAS:
        p = path / f"{t}.csv"
        if p.exists():
            tables[t] = validate_table(t, read_table(p.read_bytes(), p.name))["df"]
    label = "Dataset"
    mf = path / "manifest.json"
    if mf.exists():
        label = json.loads(mf.read_text()).get("label", label)
    return build_dataset(tables, label)


def build_dataset(tables: dict[str, pd.DataFrame], label: str) -> Dataset:
    hospitals = {r["hospital_id"]: r for r in tables["hospitals"].to_dict("records")}
    cred_df = tables["credentialing_matrix"]
    hosp_cols = [c for c in cred_df.columns if c not in ("physician_id", "name")]
    cred: dict[str, set] = {}
    names: dict[str, str] = {}
    for r in cred_df.to_dict("records"):
        cred[r["physician_id"]] = {h for h in hosp_cols if str(r.get(h, "")).strip().upper() in ("Y", "YES")}
        if r.get("name"):
            names[r["physician_id"]] = r["name"]
    on = tables["physicians_on_shift"].to_dict("records")
    off = tables["physicians_off_shift_roster"].to_dict("records")
    for r in on + off:
        names[r["physician_id"]] = r["name"]
    baseline: dict[tuple, tuple] = {}
    for r in tables["baseline_hourly_volume"].to_dict("records"):
        hh = int(r["hour_start_et"].split(":")[0])
        baseline[(r["hospital_id"], (r.get("dow_type") or "weekday").lower(), hh)] = (
            float(r["mean_consults"] or 0), float(r["p90_consults"] or 0))
    reqs: dict[str, list] = {}
    for r in tables["coverage_requirements"].to_dict("records"):
        a, b = r["time_block_et"].split("-")
        reqs.setdefault(r["hospital_id"], []).append(
            (_mins(a), _mins(b), int(float(r["min_available_credentialed_physicians"] or 0)), r["time_block_et"]))
    events = tables["event_stream"].to_dict("records")
    ds = Dataset(label=label, hospitals=hospitals, on_shift=on, off_roster=off, cred=cred, names=names,
                 baseline=baseline, requirements=reqs, events=events,
                 snapshot_consults=tables["snapshot_open_consults"].to_dict("records")
                 if "snapshot_open_consults" in tables else None,
                 snapshot_physicians=tables["snapshot_physicians"].to_dict("records")
                 if "snapshot_physicians" in tables else None,
                 raw_counts={t: len(df) for t, df in tables.items()})
    return ds


def _mins(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)
