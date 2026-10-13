# CoverGap: Mind the gap. Close the gap.

Recognized with a Special Shout-Out at Rutgers Health Hack · Sevaro Challenge · Team 07.

The command center sits on top of Sevaro's existing live view. It **detects** coverage risk from the event stream, **decides** on the right intervention and explains it, and **acts** through a clinical-lead approval step. After acting it closes the loop by updating projected coverage.

> Hackathon prototype. All data is synthetic. Not a clinical decision-support system, not HIPAA-compliant, and its sign-in is demo-only (fixed passwords, local session file). Don't expose the dev servers publicly.

> <img width="3200" height="1800" alt="CoverGap-flowchart-logos (1) (1)" src="https://github.com/user-attachments/assets/f8710b1a-edf4-4206-85eb-c822feff5200" />

## Run it

You need Python 3.10+ and Node 18+.

```bash
# Backend (port 8000)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend (port 5173, proxies /api to the backend)
cd frontend
npm install
npm run dev            # add `-- --host` to open the physician app from a phone on the same Wi-Fi
```

Open http://localhost:5173 and sign in.

### Demo logins

Every login is prefilled. Pick the role and press **Sign in**.

| Who | Where | Username | Password |
|---|---|---|---|
| Operations coordinator | http://localhost:5173/login | `coordinator` | `demo1234` |
| Clinical lead on duty | http://localhost:5173/login | `lead` | `demo1234` |
| Off-duty doctor | **http://localhost:5173/m** (open on your phone) | `okafor` (prefilled; any off-duty doctor's surname works) | `demo1234` |

Each browser tab keeps its own sign-in, so you can have the coordinator in one tab and the clinical lead in another. The API enforces the roles:
- only the coordinator can propose, reassign, escalate or load data;
- only the clinical lead can approve or reject;
- a doctor sees and answers only their own offers.

**Phone:** run the frontend with `npm run dev -- --host`, then open the "Network" address it prints plus `/m` (for example `http://192.168.1.20:5173/m`) on a phone on the same Wi-Fi. If the venue network blocks this, use your phone's hotspot for both devices.

API testing account: `admin` / `admin-demo`, which has every permission; change it with `SEVARO_ADMIN_PASSWORD`. These are demo credentials only.

Tests: `cd backend && python -m pytest -q` (38 tests, including replay against the reference snapshot and the full offer loop).

## Screens

| Who | Screen | What it's for |
|---|---|---|
| Coordinator | **What to do now** | The one problem to act on first (what, where, why it matters, what to do, who approves), then the rest in order, with one action button each. |
| Coordinator | **Coverage ahead** | Which hospitals will be short in the next 2 hours, with shift ends marked. |
| Coordinator | **Offers** | Each extra-shift offer: approved, sent, accepted, declined or timed out. |
| Coordinator | **Add new events** | Drop the judges' file (event_stream.csv format). It's added to the day, the engine re-runs, and you see what changed. |
| Coordinator | **Doctors & consults** | Reference: what each doctor is doing (from signals) and where each consult is, against its time limit. |
| Both | **Record of actions** | Who was considered, who was excluded and why, who approved, what happened. |
| Clinical lead | **Your decisions** | Offers and escalations to approve or reject in one step, plus stroke care at risk. |
| Off-duty doctor | **Phone view** at `/m` (own login) | Hospitals, hours, start time, why them. Accept or decline. |

Settings (gear icon) holds the coordinator's preferences and the projection assumptions. The safety rules are fixed.

## Demo clock (simulate time)

Click the time in the top bar (as the coordinator) to move the scenario clock:
- step it (−15m to +1h), jump to a time (18:30, 18:59, 19:05, 20:05 are one click), or press **Play** to advance it automatically by 1–10 minutes every 5 seconds;
- **Back to data time** returns to the time of the latest event.

Moving the clock re-runs the whole engine at that moment:
- **Moving back:** events after the chosen time are hidden.
- **Moving forward:** waiting times grow past their limits, shifts end, night doctors come on at their scheduled start, consults left with doctors who have gone home are flagged, and offers expire 10 minutes after sending on the demo clock.
- **Alerts:** new critical problems pop up as alerts, and the panel lists what's new, worse and resolved.

Moving forward doesn't invent events: a doctor who was on a video call at the last event is still on it until new events say otherwise. Add events (Add new events) to move activity forward.

## Plan A and Plan B

Every problem that needs action comes with two plans where two real options exist:
- **Plan A** is the recommended fix.
- **Plan B** is the best alternative: another approved doctor, queueing with a busy approved doctor, a second eligible off-duty doctor, a handoff versus a reminder, or escalation.

Each plan card says what it does, why, and what happens if approved. The coordinator presses **Send Plan A** (or B) **for approval**. The clinical lead sees the chosen plan next to the one not chosen and approves or rejects it in one step. Approval runs the plan straight away: it assigns the consult, sends the extra-shift offer, records the escalation or sends the alert. A rejection comes back to the coordinator with the lead's note, so a plan can be sent again.

## AI-assisted call when a doctor doesn't reply

If an approved offer gets no reply within **1 minute**, the system starts an AI-assisted call to that doctor. The delay is adjustable in Settings, and it also triggers when the demo clock moves 1 minute past sending.

1. The doctor's phone (`/m`) shows an incoming call from the "Sevaro coverage assistant".
2. On **Answer**, the assistant reads the approved offer aloud (hospitals, hours, start time and why they were asked) and listens for "yes" or "no". **Accept** and **Decline** buttons are always on screen too.
3. The answer is recorded "via AI call". The coordinator sees the call status and transcript on **Offers**, and the problem card shows "AI call in progress".
4. If the doctor taps **Not now**, the call is marked "no answer" and the offer stays open until its 10-minute expiry.

Safety: the call is a follow-up on an offer the clinical lead has already approved. It says only what the approved offer says, with no patient details, and every step is in the record of actions.

Demo limits:
- The call is simulated inside the phone view using the browser's built-in speech. No real phone number is dialled.
- Sound: browsers only play sound after a tap on the page, and signing in on `/m` counts. If the phone view was reloaded, tap the "Turn on call sound" bar. On iPhones the silent switch also mutes it.
- Voice replies need a browser with speech recognition (Chrome, Edge or Safari) and, on phones, a secure (https) page. Over a plain `http://192.168…` address, the assistant still speaks but the doctor answers with the buttons.
- In production this would connect to a telephony and voice-AI service, using the same script.

## Demo walkthrough (about 6 minutes)

1. **What to do now.** The top card answers the handbook's four questions for the stranded Oak Valley stroke (CON-2105): routing failed 3×, nobody approved there is free, and Dr. Okafor is the one off-duty doctor who passes every rule.
2. Click **Call in Dr. Grace Okafor**. The decision screen shows the recommendation, everyone considered with the rule each one fails, and how routing is limited so the new doctor isn't swamped. Click **Send to clinical lead for approval**.
3. In a second tab, sign in as the **Clinical lead**. On **Your decisions**, click **Approve and send**.
4. On your phone, open `/m`, press **Sign in** (Dr. Okafor is prefilled) and tap **Accept**.
5. Back as coordinator: the Oak Valley patient now reads "Dr. Grace Okafor joins at 18:40". Suncrest is still one short, and nobody else qualifies, so it's escalated rather than a rule being bent. Check **Record of actions** for the full trail.
6. **Show alerts being generated.** Open the clock and jump to **19:05**. Shifts change, consults left with doctors who've gone home are flagged with a reassignment to the night doctor, new coverage gaps appear, and alerts pop up. Press **Back to data time** before the live test.
7. **Live test.** Go to **Add new events** and drop the judges' file, or `sample_live_events.csv` to rehearse. You'll see the clock move, new and worsened problems, and the new top action. In the sample, a repeat call about CON-2105 moves it up without restarting its clock, and Dr. Kim finishing a video changes the top fix to "Assign to Dr. Daniel Kim".

## How it works

```
event_stream.csv ──► replay (event-time order, de-dup) ──► physician state  ┐
                                                         consult lifecycle ├─► Detect ─► Decide ─► Approve ─► Act ─► Update
reference tables ──► credentialing, shifts, baselines, requirements ─────────┘     ▲                                   │
                                                                                     └────────── loop back ──────────────┘
```

| Layer | What it does | Where |
|---|---|---|
| Replay | Dedupes on `event_id`, orders by `event_time` (ingest-time tiebreak), runs separate state machines for physician and consult, reconciles signals (Synapse / camera / status / agent heartbeat) | `backend/app/replay.py` |
| Detect | Stage timers vs. standards, end-of-shift notes, demand vs. p90, contradictory signals, routing gaps now, roster gaps projected over 120 min, credentialing-driven imbalance | `backend/app/engine.py` |
| Problems | Merges detections into one problem per consult / hospital / doctor and answers: what is going on, where, why it matters, what to do (one fix, who approves, why it beats the alternatives). Ranked. | `backend/app/problems.py` |
| Decide | Reassign candidates with per-rule checks, escalations, handoff plans, split-shift decision card (eligibility, ranking modes, options with impact), routing what-if simulator | `engine.py`, `decide.py` |
| Act | Propose → clinical-lead approve/reject → send (simulated, in-app) → accept / decline / 10-minute timeout → coverage update → stop when filled, propose the next eligible physician or escalate. Double-acceptance guard. Audit log of everything. | `backend/app/service.py` |

### Two kinds of gap

- **Routing gap (now):** a consult is waiting at a hospital and no credentialed on-shift physician is routable under the brief's routing rules (busy, ringing, unavailable, or ended a call less than 2 minutes ago). This is what strands CON-2105 and CON-2114.
- **Roster gap (projected):** available credentialed physicians (on shift and not Temporarily Unavailable, plus scheduled starts and accepted split shifts) fall below the requirement. A surge adds +1, every 15 minutes for 120 minutes.

### The split-shift trap

An accepted offer carries a **routing profile**: the joiner is scoped to the gap hospitals and their starting count is seeded to just above the low-volume priority threshold. The coverage model and the routing simulator both respect that scope. The simulator replays the brief's routing rules over the offer window to compare four profiles. It models the routing engine; it doesn't replace it.

## Storage

Everything is local files. There is no database.

```
backend/data/demo/      original synthetic files (never modified)
backend/data/active/    the active dataset (swapped in atomically on load/reset) + manifest.json
backend/data/staging/   validated uploads waiting to be loaded
backend/data/state/     workflow.json (offers, escalations, command-center events),
                        notifications.json, activity_log.json, preferences.json, assumptions.json
```

Writes use temp file + fsync + `os.replace`. A dataset load builds a new directory, replays it as a final check, then swaps it in with a rename. If validation or the replay fails, the active dataset is untouched. Delete `backend/data/active` and `backend/data/state` for a factory reset.

All reads and writes of state files go through one lock, and a brief "Access is denied" from Windows (an antivirus scanner, the search indexer, or another request holding the file) is retried for up to about 2 seconds instead of failing. If the server ever hits an unexpected error it returns a readable message rather than a bare 500 and writes the full traceback to `backend/data/state/errors.log`. Share that file if something goes wrong during testing.

## Dataset formats

Required: `event_stream`, `hospitals`, `physicians_on_shift`, `physicians_off_shift_roster`, `credentialing_matrix` (one column per hospital ID, `Y` = credentialed), `baseline_hourly_volume`, `coverage_requirements`. Optional: `snapshot_open_consults`, `snapshot_physicians` (used only by the replay check). Column lists appear on the Data management page, and each type can be downloaded there as a template. Kit file names like `1791647578874_event_stream.csv` are recognised automatically. JSON uploads must be an array of records, or `{"records": [...]}`.

Validation covers: file type, empty files, missing columns, timestamps/HH:MM/numeric types (bad rows are skipped and reported), duplicate keys (an error for reference tables, a warning for events), credentialing columns versus hospitals, physicians on and off shift at once, and events referencing unknown IDs.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/meta` | Status, scenario clock, dataset, KPIs |
| GET | `/api/dashboard` | KPIs, ranked detections, interventions, incidents, coverage, corrections |
| GET | `/api/consults` | Open consults with timers + activity/stage timeline |
| GET | `/api/physicians` | Derived physician state, off-shift roster, insights |
| GET | `/api/coverage` | Runway grid, routing gaps, roster gaps, demand |
| GET | `/api/incidents/{id}/plan?mode=&hours=` | Split-shift decision card |
| GET/POST | `/api/offers` | List / propose offers |
| POST | `/api/offers/{id}/approve` · `/reject` · `/respond` · `/expire` | Approval, physician response, demo timeout |
| POST | `/api/consults/{id}/reassign` | Reassign (appends a command-center event) |
| POST | `/api/escalations`, `/api/escalations/{id}/decide` | Escalate / authorize |
| GET/POST | `/api/notifications`, `/api/notifications/read` | In-app notifications by audience |
| GET | `/api/activity` | Audit log with filters |
| GET/PUT | `/api/config`, `/api/preferences/{role}`, `/api/config/assumptions` | Rules (read-only) and preferences |
| GET | `/api/datasets/types`, `/api/datasets/sample/{type}`, `/api/datasets/composed` | Types, templates, pre-load check |
| POST | `/api/datasets/validate`, `/api/datasets/load`, `/api/datasets/reset`; DELETE `/api/datasets/staging` | Upload pipeline |
| POST | `/api/events/upload` | The live test: add a file of events to the day and get a what-changed summary |
| GET | `/api/problems` | Ranked problems with what / where / why / fix |
| POST | `/api/problems/{id}/escalate`, `/api/problems/{id}/alert` | One-click escalation and internal alert |
| POST | `/api/events` | Inject one live event |
| GET | `/api/snapshot-check` | Replay vs. reference snapshot |

Interactive docs are at http://localhost:8000/docs.

## Handbook situations and how they're handled

| Handbook issue | Handling |
|---|---|
| Sudden rush at one hospital | Each hospital compared with its own p90 for that hour; surge raises the minimum by one |
| Doctors leaving while busy | 2-hour look-ahead with shift ends; open notes within 60 min of shift end flagged with a handoff plan |
| Free but not approved | Every check uses the credentialing matrix; nothing assumes cross-cover |
| "Available" isn't available | Status, Synapse, camera and helper-app signals reconciled; conflicts flagged |
| Consult stuck at a step | Timers from when each step started, by event time |
| Nobody can take the call | Routing gaps detected; several stuck consults ranked, with the first to act on |
| Same patient twice | A repeat request for the same consult ID raises its rank but doesn't restart its clock or count as new demand; different consults are never merged |
| Who can be called in | All eight rules checked and shown; online time counts against the 2-hour minimum; nobody eligible → escalate |
| Extra doctor gets swamped | Offer carries a routing profile: short hospitals only, seeded count; simulated against normal routing |
| Approvals and safety | Clinical lead approves every offer; no patient details; one open offer per doctor, ≤3/week; 10-min expiry; double acceptance handled; everything logged |
| Day moves past 19:00 in new data | Roster doctors whose scheduled shift has started come on shift automatically |

## Assumptions (where the brief is silent)

All of these are in `backend/app/config.py`, and most can be edited on the Settings page.

- Scheduled shift starts count toward coverage from their start plus time to come online (proposal default, Q3). The roster has no shift end, so a scheduled shift is assumed to last 12h.
- Temporarily Unavailable is assumed to persist through the horizon.
- Projected surge = known arrivals still inside the trailing 60-minute window plus the baseline mean for the unknown future. A projected count must round above p90.
- The offer window starts at the next 5-minute mark (current gaps) or at the gap start (future gaps). It lasts 2.5h by default, or up to 4h to span the gap. A doctor whose time to get online leaves less than 2 usable hours fails the minimum-length rule.
- Offer timeouts use the wall clock (10 min) because the scenario clock is frozen at the last event. Use *Simulate 10-minute timeout* to demo the path.
- The routing simulator uses deterministic arrivals from the baseline (p90 during a projected surge) and a configurable service time of 25 min.
- The weekly offer cap counts offers sent through this system. The dataset has no offer history.

## Proposal requirement checklist

| Proposal item | Status |
|---|---|
| Detect → Decide → Approve → Act → Update loop | Done |
| Replay with late/duplicate handling; reproduce 18:20 snapshot | Done (146/146, tested) |
| Physician activity and consult lifecycle kept separate | Done (state machines + activity lanes) |
| Breaches vs. standards, demand vs. baseline, contradictory signals, 90+ min projection | Done (120 min) |
| Split-shift card: every candidate, every rule, pass/fail | Done |
| Several options with if approved / if rejected | Done |
| Role views: coordinator, clinical lead, off-shift physician | Done |
| Coordinator preferences (hospitals, severities, ranking mode) | Done; safety rules locked |
| Clinical-lead approval before any physician message; no patient info | Done (enforced server-side, tested) |
| Track accept / decline / 10-min timeout; double acceptance; stop when filled; next candidate or escalate | Done |
| One open offer per physician, ≤3 per week | Done |
| Split-shift trap handled | Done (scoped + seeded profile, simulator) |
| Audit log of considered/excluded/approver/outcome | Done |
| In-app data loader without restart; live event injection | Done |
| Corrections from late events announced, not silent | Done |
| Optional voice / cloud LLM | Not built (no external services by design) |

## Known limitations

- No real authentication, messaging, scheduling or credentialing integration.
- The scenario clock comes from the data (latest event). Times are shown in ET.
- Polling (3–5 s) instead of server-sent events.
- Single-process file storage. Fine for a demo; not for concurrent production use.
