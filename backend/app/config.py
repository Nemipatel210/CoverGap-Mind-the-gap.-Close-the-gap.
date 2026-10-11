"""Rules and thresholds.

Every threshold below comes from the Sevaro challenge brief (marked BRIEF) or is a
documented demo assumption (marked ASSUMPTION). Safety rules are not user-editable;
only the `assumptions` block can be changed from the Settings page.
"""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEMO_DIR = DATA_DIR / "demo"
# Runtime data (active dataset, staging, workflow state) can be redirected, e.g. for tests.
DATA_DIR = Path(os.environ.get("SEVARO_DATA_DIR", DATA_DIR))
ACTIVE_DIR = DATA_DIR / "active"
STAGING_DIR = DATA_DIR / "staging"
STATE_DIR = DATA_DIR / "state"

# --- BRIEF: operational standards (minutes) -----------------------------------
# key -> (stage(s), applies_to, warning, critical, label)
STANDARDS = [
    {"key": "triage_unassigned", "stages": ["Triaged"], "applies": "All", "warning": 5, "critical": 10,
     "label": "Triaged, not yet assigned", "clock": "stage"},
    {"key": "assigned_not_contacted", "stages": ["Assigned"], "applies": "Stroke", "warning": 3, "critical": 8,
     "label": "Assigned, physician not yet contacted", "clock": "stage"},
    {"key": "imaging_pending", "stages": ["CT/CTA or Imaging Pending"], "applies": "Stroke", "warning": 12,
     "critical": 20, "label": "CT/CTA or Imaging Pending", "clock": "stage"},
    {"key": "imaging_review", "stages": ["Imaging Review"], "applies": "Stroke", "warning": 6, "critical": 12,
     "label": "Imaging Review (imaging back, video not started)", "clock": "stage"},
    {"key": "note_stroke", "stages": ["Note Pending", "Documentation"], "applies": "Stroke", "warning": 30,
     "critical": 45, "label": "Note Pending + Documentation from end of video/call", "clock": "clinical_end"},
    {"key": "note_general", "stages": ["Note Pending", "Documentation"], "applies": "General Neuro",
     "warning": 45, "critical": 90, "label": "Note Pending + Documentation from end of video/call",
     "clock": "clinical_end"},
]
# BRIEF: open notes within 60 min of shift end -> warning on any, critical on 2+
END_OF_SHIFT_WINDOW_MIN = 60

# --- BRIEF: routing rules -----------------------------------------------------
ROUTING = {
    "low_volume_day": 6,
    "low_volume_night": 4,
    "recent_call_block_min": 2,
    "retry_min": 5,
    "day_start_hour": 7,
    "night_start_hour": 19,
}

# --- BRIEF: split-shift eligibility and notification safety ---------------------
SPLIT_SHIFT = {
    "min_rest_hours": 10,
    "max_hours_7d": 60,
    "min_offer_hours": 2,
    "offer_expiry_min": 10,
    "max_offers_per_week": 3,
    "max_open_offers_per_physician": 1,
}

SPIKE_WINDOW_MIN = 60  # BRIEF: trailing 60-minute consults vs p90 baseline

# --- ASSUMPTIONS (editable, documented in README) -------------------------------
DEFAULT_ASSUMPTIONS = {
    "horizon_min": 120,                 # brief requires >= 90
    "step_min": 15,
    "count_scheduled_starts": True,     # proposal Q3 default: scheduled shift starts count toward coverage
    "scheduled_shift_hours": 12,        # roster has no shift end for off-shift physicians
    "unavailable_persists": True,       # Temporarily Unavailable assumed to persist through the horizon
    "default_offer_hours": 2.5,         # long enough that a 2h minimum survives a typical time-to-online
    "max_offer_hours": 4,
    "late_event_threshold_sec": 60,
    "sim_service_min": 25,              # what-if simulator: minutes a consult keeps a physician busy
    "offer_timeout_wall_min": 10,       # wall-clock minutes before an unanswered offer expires
}

DEFAULT_PREFERENCES = {
    "coordinator": {
        "hospitals": [],                 # empty = all
        "severities": ["critical", "warning", "info"],
        "intervention_types": ["reassign", "escalate", "split_shift", "handoff", "verify_signal"],
        "ranking": "fastest",           # fastest | lightest_load | fewest_offers
    },
    "clinical_lead": {"stroke_only": True},
}

STAGE_ORDER = [
    "Received", "Triaged", "Assigned", "Provider Contacted", "CT/CTA or Imaging Pending",
    "Imaging Review", "Video Consult In Progress", "Note Pending", "Documentation", "Signed Off",
]
