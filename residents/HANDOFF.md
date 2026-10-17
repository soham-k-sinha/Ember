# residents/ HANDOFF: full context for the next agent (Soham's lane)

Last updated: Sat 2026-10-17, ~12:30 (D60 + the voice plan). Hackathon: **HackHarvard 2026**. **Devpost
submission due Sunday 8:00 AM.** Venue closes 8 PM nightly.

**State right now**
- `main` = `e26af22`: Aryaman's D58 (declines are constraints, nearest drop-off = the Treehouse) and D59 (a van collects
  a nearby household on its list before the drop-off: shared trips).
- Soham's work is in **one PR to merge: `soham/questions`** (see §8). It contains #38 (D55) and #39 (D56, D57)
  **rebased onto main**, plus D60 and the D58/D59 compatibility fixes; **198 tests pass**.
- **#38 and #39 are superseded:** their branches are *not* rebased and conflict with main (DECISIONS.md), and #39's
  decline test fails against D58. Merge `soham/questions` and close #38/#39.
- Soham merges by hand: the agent's `gh pr merge` is blocked by Claude Code's auto-mode classifier.
- **Next big piece: the voice channel**, planned in `residents/VOICE_PLAN.md` (nothing built yet; §11 there lists
  Soham's decisions).

Read this file first, then:
- `CLAUDE.md` (hard rules)
- `docs/HANDOFF.md` (team-wide status, Aryaman's)
- `docs/DECISIONS.md` (D1–D54 on main; D55 is in #38, D56–D57 in #39)
- every `docs/log/*.md`
- `docs/team/soham.md` (the brief)
- `residents/README.md` (API, how to run the drill)

---

## 1. The project in one paragraph
**EMBER** is a disaster-coordination system for a flood of the Charles River in the district around the David
Rubenstein Treehouse (Harvard, Allston), where the hackathon is held.
- **One shared picture:** water, closed roads, households that need help, a hospital, a sewage pumping station, vans
  and generators.
- **The planner:** a deterministic allocator, scored by a simulator, produces one coordinated plan plus a personal
  instruction for each household.
- **Real people by iMessage:** residents and hospital operators take part over Photon 2.0. **One LLM call** turns a
  text into structured facts. The planner replans in about 0.5–2 s, and only *changed* instructions are texted back.
- **Robustness and metrics:** plans are stress-tested on **Daytona** sandboxes. The sustainability metric, inside the
  objective, is **m³ of untreated sewage kept out of the Charles**.
- **Against the baseline:** it beats incident-by-incident dispatch. Over 5 seeds that's about +50 people reached
  before their deadline, less hospital outage and less overflow.

**Demo moment:** the judge plays household **#10296** and texts something like *"2 of us, one is in a wheelchair,
River St is blocked"*. That one text changes their own rescue (they get Accessible Van 3) and an infrastructure
decision (Generator 1 is rerouted), and the map shows why.

**Drill (new, D56/D57):** testers can run a whole evacuation from scratch by text, in one process
(`uv run ember-drill`). They text where they are, answer the plan's questions, reply YES, then get one step at a time
and reply DONE. The sim clock advances with those replies.

## 2. Hard rules (CLAUDE.md, enforced in code here)
1. **Contracts are the interface** (`contracts/*.schema.json` + fixtures). Changing one = bump the version, update the
   fixture, add a DECISIONS line. `contracts/` is **Aryaman's lane**; the residents layer changes none of them.
2. **No LLM in the planner or the tick loop.** The only LLM call is `residents/residents/extract.py` (free text → typed
   facts). Routes, times, assignments, steps and every reply sentence are computed (`outbound.py`, `guide.py`,
   `briefing.py`). The LLM only labels things: fact kinds, a question's topic, the place as written.
3. Agents are rows, not personas.
4. Time is `t_s` (seconds since sim start); coordinates are `[lon, lat]`; distances in metres, speeds in m/s.
5. Hazards implement `polygon_at` / `closed_edges_at`.
6. Engines are plug-ins.
7. 2D simulation, 2.5D view (D50).
8. Daytona Tier 1/2 has no internet egress.
9. **Photon 2.0 Beta** (`api.photon.codes/v1`): shared iMessage lines, **the tester must text first**, no group
   chats, no calls.
10. Label what's synthetic.

Also enforced here:
- Every outbound text starts with **`[EMBER drill]`** and carries its **`plan_version`**.
- Offers stay provisional until the person replies YES.
- **Secrets live only in `residents/.env`** (gitignored). **Never commit keys or real phone numbers** (tests use
  555 placeholders; D56 scrubbed the real ones). Real drill numbers go on the command line or in `.env`
  (`DRILL_RESIDENTS`, `DRILL_OPERATORS`).
- Never send surprise texts to real phones. Use `--dry` / `PHOTON_ENABLED=0` for anything automated. A reset, or
  starting the drill, texts every opted-in phone a welcome or a question; that's expected.

## 3. Team and lanes (`.github/OWNERS.json`, CI-enforced)
| Person | GitHub login | Lane (paths a PR may touch) | Doing |
|---|---|---|---|
| **Soham (you)** | `soham-k-sinha` (repo owner) | `residents/` + own log `docs/log/soham.md` + shared `docs/DECISIONS.md` | backend, Photon, LLM extraction, replan loop, drill |
| Aryaman | `aryamangoenka` | `engine/`, `contracts/`, `.github/`, `CLAUDE.md`, `README.md`, `docs/{TECHNICAL,HANDOFF,SIM_ENV_PLAN}.md`, `docs/team/`, and since D49 also `web/`, `scenarios/`, `docs/DEMO.md`, `docs/QA.md`, `docs/devpost/` | engine (world, hazards, plan simulator, allocator, baseline, compare, Daytona, `EngineSession`), contracts; now also the web UI and the demo script / QA checklist |
| Arnav | `aarnavkhanna` | `web/` | web (Vite + React + deck.gl map, panels, WS client); Aryaman covers it too |
| Anshuman | `anshunevatia-del` | `scenarios/`, `docs/DEMO.md`, `docs/QA.md`, `docs/devpost/` | scenario `allston_flood_v1`, sources and assumptions; Aryaman covers it too |

- **Never edit another person's lane**, not even a one-line fix. Engine problems become notes in your log and in chat
  (see §10).
- Soham's earlier instruction to agents: write code only on `soham/*` branches; nothing goes to `main` or to anyone
  else's branch.

## 4. Git / GitHub protocol (non-negotiable)
- Repo: `https://github.com/soham-k-sinha/Ember`, `origin`. The **integration branch is `main`** (also the default).
  Always pass `--base main`. `gh` is authenticated as `soham-k-sinha`.
- **CI `ownership / check`** (`.github/ownership.py`) fails a PR that touches files outside your lane, or whose branch
  doesn't start with `soham/`. GitGuardian also scans for secrets.
- Per feature:
```bash
git checkout main && git pull --ff-only origin main
git checkout -b soham/<topic>
# … work, test …
git add residents docs/log/soham.md docs/DECISIONS.md      # only your paths, never `git add -A` at the repo root
git commit -m "residents: <what and why>"                    # end with the Co-Authored-By line if an agent wrote it
git fetch origin && git rebase origin/main                   # ALWAYS before pushing
(cd residents && uv run pytest -q)                           # must pass after the rebase (~95 s)
AUTHOR=soham-k-sinha BASE=origin/main HEAD=HEAD HEAD_REF=soham/<topic> python3 .github/ownership.py   # local lane check
git push -u origin soham/<topic>                             # --force-with-lease only after rebasing a pushed branch
gh pr create --base main --head soham/<topic> --title … --body …   # body ends with the Claude Code line if an agent wrote it
gh pr checks <n>                                              # ownership + GitGuardian
# merge: squash; Soham does it (self-merge is allowed when only his lane changed and pytest passes)
```
- **DECISIONS.md conflicts are routine.** Others append too. Keep *every* line and renumber yours to the next free
  `D<n>` (fix the number in your log entry as well). Check with
  `grep -o "^| D[0-9]*" docs/DECISIONS.md | sort | uniq -d`, which must print nothing. If someone takes D55–D57
  before #38/#39 merge, renumber ours.
- **Log protocol:** after every feature, append to `docs/log/soham.md` (What / Files / Run / Interfaces / Status /
  Next, per `docs/log/README.md`). At the start of a session, read all logs and DECISIONS.

## 5. Architecture
```
scenarios/allston_flood_v1/scenario.json  flood keyframes, facilities, fleet (Van 1, Van 2, Accessible Van 3, Generator truck,
                                          Road crew, Generator 1 500 kW camlock, Generator 2 150 kW twist-lock; all at EMS 14),
                                          40 synthetic households, judge #10296, reserve rule (1 van, 1 generator)
engine/data/town.json.gz                  shared OSM town: 586 nodes (intersections), 1,196 edges, 17,810 buildings
        │
engine/ember_engine  (Aryaman)  world · hazards · models · sim/plan_sim (simulate → metrics, per-assignment outcomes,
        │                       state_at) · allocator (candidates × local search, every move scored by the simulator;
        │                       rationale, unresolved, info_requests, changes) · baseline · compare · daytona
        │                       api.EngineSession  ← the ONLY entry point residents uses (D42)
        ▼
residents/  (Soham)  FastAPI + SQLite. The DB is the source of truth; the engine session is resumed from it on every call.
   Photon 2.0 ⇄ phones (iMessage)      HTTP + WS /ws  ⇄  web/ (deck.gl map, panels, scatter, comparison)
   ember-drill = the same app + phone registration + a console, in one process
```
**State model (D41):**
- **Backend-owned:** the sim clock, live reports (with original text and confidence), every raw allocator plan
  version (and which reports it saw), messages, phones, and per-run conversation memory in `kv`.
- **Derived:** everything else, via `EngineSession.resume(plan, reports)` → `state_at(clock)` after each replan or
  clock move.
- **Plan view:** the state shows the simulation's view of the plan (routes, as-of-t statuses such as `en_route`).
  The **raw plan** keeps the backend's statuses (`offered` / `confirmed` / `rejected`).

**How the planner decides (what residents see explained since D57):**
- **Candidate plans:** priority rules (deadline-first, least-slack, largest-household, mobility-first,
  nearest-first) × reserve held or released × generator policy.
- **Local search:** relocate / swap / reorder / insert / drop moves, each scored by simulating everyone.
- **What the simulation accounts for:** every household, every vehicle's queue, road travel times, closures, flood
  deadlines, seats and wheelchair access.
- **Objective (lexicographic):** people unreached, then hospital outage, then overflow m³, then people reached,
  then churn, then fuel and km, then reserve kept.
- **Limits** (engine-side, see §10): one household per trip; drop-off is always the response base (EMS 14);
  declines aren't constraints.

### residents/ files
| File | Role |
|---|---|
| `residents/app.py` | `create_app(settings, photon_client=, bridge=, llm=)`; the arguments let tests inject fakes. Lifespan order: store → hub → bridge (+ `restore_households`) → planner → messenger → outbound (plan hook) → guide (plan + clock hook) → intake (inbound hook) → locator (lobby hook + plan hook) → **then** bootstrap → Photon listener → failed-send retry loop. All endpoints. Request models live at module level. |
| `config.py` | `Settings` from env / `residents/.env` (see §6 for the knobs). |
| `db.py` | stdlib sqlite3 `Store`. Tables: meta, closures, households, facilities, resources, reports, plans (+reports_used), assignments, messages (+delivery, external_id, created_wall, recipient_handle), **phones** (handle, role, thread_key UNIQUE, scenario_id, Photon assignment / line / user ids / space / last_inbound_at), **kv**, **inbound_seen**. Contract objects stored as JSON (D36). `snapshot()` returns the state contract. `clear_scenario()` (reset) drops the run, including the kv prefixes `pending: instr: asked: rejected: guide: located: lobby: welcomed: keep:` plus `extra_households`, and un-places phones that were placed by location. `rebind_phone` / `delete_phone` are used by the drill. |
| `bus.py` | WS hub; envelope `{type, seq, t_s, data}` (`contracts/ws-events.schema.json`). |
| `engine_bridge.py` | The only file importing `ember_engine`. Uses `EngineSession` (resumed from the DB each call). `optimize()` runs on a separate session **and** a separate World, because World's caches aren't thread-safe. `solo` drops the scenario's synthetic households and scripted reports. `set_extra_households()` adds households texted in at runtime (town buildings) and clears the World's `_flood_cache`, so deadlines include them. `outcomes(plan, reports)` returns per-assignment arrive / pickup / complete times (cached). `deadline(hid)`, `flood_corners(k)` (cached), `household_node(hid)`, `resolve_road()` (street name → edges: cross street, else within 150 m of the household; both directions). `places` is a `Gazetteer`. |
| `planner.py` | Replan loop: `bootstrap` (also resets the extra households), `submit_report`, `replan` → `_store_plan` → `_publish` (WS `plan`, one `assignment` per change, `metrics`, plan hooks), `set_clock` (+ **clock hooks**), `respond` (confirm/reject, stale check), `optimize` (outside the lock; discarded as "superseded" if the plan moved), `simulate`, `comparison`, `close_road`, `set_facility`, `add_household` / `restore_households` / `extra_households`. One asyncio lock; engine work runs in a threadpool. |
| `contracts.py` | jsonschema validators over `contracts/`. |
| `photon.py` | Photon transport. `PhotonClient`: retries 429/5xx with the same Idempotency-Key; `_backoff` hook for tests. `parse_inbound` (text messages only). `PhotonListener`: Socket.IO subscribe with a durable cursor, reconnects forever, polling fallback capped at 10 min (D54), certifi SSL. |
| `threads.py` | One phone per household/facility (D55): `resolve_thread`, `phone_thread`, `phone_for_thread`, `select_thread`. `unplaced()`: a resident registered with `locate` that has no household yet (thread_key NULL, scenario_id set). Legacy rows (both NULL) auto-bind to the judge/hospital. `normalize_handle`. |
| `messaging.py` | `Messenger`: inbound (dedupe by id + `inbound_seen`, ignore texts from before this run, learn the opt-in ids) → stored message → WS → hooks. Unplaced phones go to **lobby hooks**, with a kv `lobby:<handle>` log that is moved into the household's thread once placed. `send_message` / `send_to_phone` (drill prefix, opt-in enforced; delivery = sent / failed / dev / no_phone / not_opted_in). `phone_inbound` (console/dev, by handle). `taps` (console printer). `retry_failed`. |
| `extract.py` | **The one LLM call.** Claude Opus 5.5 (`EXTRACT_MODEL`), effort low, structured outputs (`beta.messages.parse` + Pydantic) with the server-side refusal fallback. Fact kinds: need, closure_report, facility_status, **location**, **done**, confirm, reject, question (+ **question_topic**: eta / pickup_place / destination / others / vehicles / bring / other), other. `to_outcome()` is deterministic: confidence < 0.6 → ask; a need without a head count → `pending` + ask; needs merge with known ones (D46); closure → `resolve_road` or ask; endurance in minutes (D53); confirm/reject only if something was offered; the model's own question next to a need goes into `follow_up`. |
| `intake.py` | Inbound hook, serialized. A DONE (regex `guide.STEP_DONE`) while a step waits goes straight to the guide, no LLM. Otherwise: extract → reports (dupes skipped) → **one** replan per text → reply. Reply order: missing-info question; else instruction / "Got it." + status + follow-up; questions always answered (D60): topic answer from briefing, else `Outbound.situation` (status + current step + open question); `other` also goes to the coordinators' queue (kv `question:`, escalation hooks → drill console). YES/NO → `planner.respond`, with D57: a NO to the only fitting vehicle asks first (kv `keep:`), and a YES after a decline undoes it. A YES starts the guide. Planner failure → an honest text. |
| `outbound.py` | Plan hook. Per phone thread, texts only when **its** instruction materially changed (D44). Offers name the pickup corner, the deadline, **why this vehicle and who's ahead on it** (D57), and say "precaution" outside the flood. Never re-offers a declined vehicle. No false "no longer coming" once a pickup is under way or done. Asks `info_requests` once. `status_text` is honest about confirmed, picked up, safe, powered, shelter-in-place, and declining the only vehicle. |
| `places.py` | Location (D56): `parse_coords` (typed coordinates, Apple/Google maps links), `Gazetteer` (intersections, nearest free building, corner labels, distance/bearing, town bbox), `nominatim()` (OSM geocoder bounded to the town; `GEOCODE=0` turns it off). |
| `locate.py` | `Locator` (D56): the lobby. Ask where they are → LLM reads the place and any needs → `Gazetteer.locate` → nearest free building becomes a household of the run → phone bound → pre-placement needs submitted (or held as pending) → one replan, after which the plan asks its question or offers. "Water reaches your street in N min" / "outside the forecast flood area" (+ a drill tip with a flood corner). Welcomes opted-in unplaced phones after a reset. |
| `guide.py` | `Guide` (D56): after YES, one text per step, timed from the simulator's outcomes. Rescue: get ready + walk to the corner (distance, direction, minutes) or wait inside for a door pickup → board → ride → checked in. Protect: meet the crew → connecting → powered. DONE replies; `auto_clock` jumps the clock to the next event once nobody is pending. kv `guide:<thread>`. |
| `briefing.py` | D57: what the plan knows, in words. `why()`, `fits()`, `alternatives()`, `queue()`, `neighbors()` (other households of the run within 300 m, same corner, shared vehicle), `answer(topic, thread, road)`, `walk_phrase()`. D60: `flood_text()` (scenario keyframes), `roads_text()` (closures for the whole named street, `EngineBridge.named_edges`), fixed `SAFETY` / `BRING` wording. Facts only. |
| `drill.py` | `uv run ember-drill` (§6). Preflight: refuses to start if the port is busy or another Photon-enabled EMBER is running (both would answer every text). Fresh run: the command line decides who plays what (re-binds phones from the last run and keeps their opt-in; drops unlisted ones). Console prints every text. `SetupError` → one-line message. |
| `tests/` | **198 tests**, about 85 s. `test_questions.py` (17, D60): every topic in every state, the live transcript, the coordinator queue. No network, no paid API: Photon faked at the HTTP layer (`fake_photon.py`), LLM faked (`FakeLLM`, keyed on exact text), `EMBER_LOCAL_POOL=1`, `GEOCODE=0`, engine at `moves=10`. `test_drill.py` (32) covers the whole text-driven drill and replays the two-phone transcript. `samples.json` = 32 messages for the live eval. |
| `scripts/eval_extract.py` | Live accuracy of the LLM call on samples.json (real API, ~$0.25). Last run **32/32, median 2.3 s**. |

### API (full table in residents/README.md)
- **State and plans:** `GET /health` · `GET /state` · `GET /plan/current` · `GET /plan/{v}` · `WS /ws`
- **Facts and disruptions:** `POST /reports` · `POST /disruption` (`close_edges`, or `facility_id` + `set`) ·
  `POST /replan` · `POST /clock {t_s}`
- **Analysis:** `GET /comparison?seeds=` · `POST /optimize?seeds=&k=` (202) + `GET /optimize` ·
  `POST /simulate {planner}`
- **Questions (D60):** `GET /questions?open_only=` · `POST /questions/{report_id}/answer {text}`
- **People:** `POST /ask {role, household_id?|facility_id?, question?}` ·
  `POST /assignments/{id}/confirm|reject {plan_version?}` (the console reject is immediate) ·
  `GET/POST /phones {role, handle, household_id?|facility_id?|locate?}` · `POST /messages`
- **Dev:** `POST /dev/reset` · `POST /dev/inbound {role, text, household_id?|facility_id?|handle?}`
- **WS events:** `state`, `plan`, `assignment` (incl. `status_changed`), `message` (upsert by id), `report`,
  `metrics`, `scatter_point`.
- **What the web calls:** `/state`, `/clock` (every 1.2 s while playing), `/disruption`, `/replan`, `/comparison`,
  `/optimize`, `/ws`. CORS allows `:5173` and `:43123`.

## 6. Running it
```bash
cd residents && uv sync           # after every pull (engine is an editable path dependency)
cp .env.example .env              # PHOTON_ENABLED, PHOTON_API_KEY, PHOTON_PROJECT_ID, ANTHROPIC_API_KEY (filled in on Soham's laptop)

# the drill (one process: backend on :8000 + phones + console)
uv run ember-drill --resident <phone> [--resident <phone2>] [--operator <phone>@mt-auburn]
uv run ember-drill --dry                      # nothing sent; type texts as @r1 …
#   --crowded  also the scenario's 40 synthetic households compete (default: only the drill's people = solo)
#   --keep     continue the last drill (default: start from scratch)    --manual-clock   clock only moves with next/+N
#   own DB residents/drill.db, log residents/drill.log; console: status · next · +N · @r1 <text> · close <street> and <cross> · plan · reset · quit

# the demo backend (DEMO.md)
RESET_ON_START=1 PHOTON_ENABLED=1 uv run uvicorn residents.app:app --port 8000   # fresh plan v1 (texts the judge phone)
uv run uvicorn residents.app:app --port 8000                                      # keep the existing DB (residents/ember.db)

uv run pytest -q                                   # ~95 s
uv run python scripts/eval_extract.py              # live LLM accuracy (costs a little)
```
**Settings** (env vars):
- **Engine:** `SCENARIO` (default allston; empty = static fixture mode), `START_T_S`, `ENGINE_MOVES`, `DB_PATH`,
  `RESET_ON_START`, `DEV_ENDPOINTS`
- **Photon:** `PHOTON_ENABLED`, `PHOTON_LISTEN`, `RETRY_EVERY_S`, `OPERATOR_FACILITY_ID`
- **LLM and web:** `EXTRACT_ENABLED|MODEL|EFFORT`, `CORS_ORIGINS`
- **Drill:** `GEOCODE`, `DRILL_SOLO`, `AUTO_CLOCK`, `DRILL_RESIDENTS` / `DRILL_OPERATORS`
- Python is 3.13 here (the pin allows 3.12–3.13).

**Drill flow:**
1. Text HI to the printed number (the Photon line, e.g. `+1 628-…`; opt-in survives runs).
2. Text where you are.
3. Answer the plan's question.
4. The offer arrives (who, where, when, why, who's ahead).
5. Reply YES.
6. The steps arrive; reply DONE after each.

Questions get answered from the plan. **The flood zone is the Cambridgeport/Riverside side** (Putnam Ave, Banks St,
Memorial Dr × River St; e.g. "Putnam Ave and Western Ave"). Allston addresses (Western Ave near Stadium Rd /
EMS 14) are outside it: those get a precautionary pickup or shelter in place.

**Phones and live processes:**
- Soham's phone and the judge test phone are both opted in on Photon. Numbers: ask Soham, or see `GET /phones`;
  never write them into the repo.
- At the time of writing an `ember-drill` (Photon on) started at 06:28 is running on :8000. It runs code from
  **before D57**, so restart it to get the new replies.
- The old 05:00 uvicorn server is gone.
- **Every reset or drill start texts the opted-in phones** (welcome / question).
- **A Photon outage** is covered: sends are retried, texts arrive via polling, and `/dev/inbound` or `@r1` is the
  fallback.

## 7. Soham's brief (docs/team/soham.md) and status
| # | Task | Status / PR |
|---|---|---|
| 1 | Skeleton + DB, GET /state, WS | ✅ #10 |
| 2 | Photon plumbing (2 phones, inbound socket, send with plan_version) | ✅ #13, live-verified |
| 3 | LLM extraction + samples + accuracy | ✅ #15 (now 32/32), D43/D46/D53/D57 |
| 4 | Reports + replan loop, only changed instructions texted | ✅ #14, #16 (D41, D44) |
| 5 | Confirm / reject, stale versions | ✅ #17 (D45), refined in D57 |
| 6 | Operator thread (info_requests → facility_status) | ✅ #16 + #32 (`/ask`) |
| 7 | Disruption, simulate, comparison, scatter forwarding | ✅ #14, #16, #32 |
| 8 | Robustness (dupes, two replies, old versions, Photon outage) | ✅ #29, #35 |
| 9 | Voice: residents in the flood zone get a phone call that works like the text thread | 📝 planned: `residents/VOICE_PLAN.md` (needs Soham: Photon payment method + number, LiveKit project) |
| + | Multi-household phones (Soham asked) | 🟡 #38 open (D55) |
| + | Text-driven drill: location, steps, clock, `ember-drill` (Soham asked) | 🟡 #39 open (D56) |
| + | Plan explained to residents, questions answered, safer declines (Soham asked, after the two-phone run) | 🟡 #39 open (D57) |
| + | Every question answered from the plan, coordinator queue (Soham asked: "what's the plan?" got only "passed to the coordinators") | 🟡 `soham/questions` (D60) |

## 8. Everything Soham's lane changed (in order)
**Merged:**
- **#10 backend-skeleton:** FastAPI + SQLite (JSON-in-row), GET /state round-trips the fixture, WS hub, a draft
  ws-events schema (moved to contracts/ by Aryaman in #11). Bug: the seed version was hard-coded → now read from the
  schema.
- **#13 photon-plumbing:** Photon built from the live OpenAPI, socket listener, polling, opt-in-safe sends,
  `/phones`, `/messages`, `/dev/inbound`. Bugs found live: `/health` crashed in a worker thread; socket SSL failed on
  macOS → certifi.
- **#14 engine-bridge:** engine mode, `/reports` → replan → WS events, `/disruption`, `/clock`, `/comparison`. Bug:
  `replan_latency_s` was dropped → carried over.
- **#15 llm-extraction:** the one LLM call, ask-never-guess, street resolution, one replan per text.
- **#16 optimize-outbound:** material-change texts, `offered`, info requests once, `/optimize` streaming. Bugs: a
  swallowed hook NameError; the generator spec doubled; `offered` lost on replan.
- **#17 confirm-reject:** stale check, sticky confirmations, no re-offer of declined vehicles. Bug: a request model
  inside `create_app()` was invisible to FastAPI → module level + a regression test.
- **#19 conversation-fixes** (first real-phone run): "Yes, 2 people" erased the wheelchair → needs merge; every fact
  gets a reply.
- **#22 engine-session:** all engine calls go through `EngineSession`.
- **#29 robustness:** serialized intake, dupes, planner failure, send retries, 150 m street resolution; tests never
  patch global `asyncio.sleep`.
- **#32 operator-simulate:** `/ask`, `/simulate`; `/optimize` outside the lock on its own World.
- **#34 demo-dry-run:** full DEMO.md dry run; v1 questions texted on reset; endurance in minutes.
- **#35 replay-guard (INCIDENT):** 6 old texts were re-answered on the judge phone after a restart → run boundary,
  `inbound_seen`, bounded poll window, socket retries forever. Verified live.
- **#37 handoff-doc:** this file.

**Open:**
- **#38 multi-household-phones** (Codex-authored on Soham's branch, D55): one phone per household/facility, many
  testers on one plan, 409 instead of silent replacement, opt-in guidance (`action_needed`, `assigned_number`). 149
  tests.
- **#39 drill**, 3 commits:
  1. **D56:** location by text, step-by-step guide, auto clock, `ember-drill`, preflight, the shelter-in-place text,
     tester numbers scrubbed from tests.
  2. **The fix for Soham's live crash:** a phone that was the operator last run, listed as a resident now, raised
     `PhoneConflict` → the command line decides, opt-in kept.
  3. **D57**, from the two-phone transcript:
     - offers explain why and who's ahead
     - questions answered by topic
     - a NO to the only fitting vehicle asks first; YES undoes a decline
     - no "Reply YES" after a YES
     - honest "nothing scheduled" texts
     - garbled needs get a follow-up question
     - the precaution note outside the flood; a drill tip

  Verification: 8–10 deliberate mutations per feature, all caught by a test; live eval 32/32.
- **`soham/questions`** (supersedes #38/#39: their commits rebased onto main with D58, plus one commit):
  - **D60:** every question gets a computed answer. New topics `plan` / `flood` / `roads` / `safety`; `plan` and
    "nothing specific yet" get `Outbound.situation` (status + current step + the plan's open question); `other` gets
    the situation **and** the coordinators' queue (`GET /questions`, `POST /questions/{id}/answer`, console
    `questions` / `tell r1 …`). A question before a location says why we need it.
  - D58 compatibility: the "you declined the only vehicle" status is checked before the engine's new unresolved entry.
  - `test_listener` poll test made relative to now (it hard-coded 12:00 UTC; D54's 10-minute clamp failed it later).
  - Verification: 198 tests; 25 mutations all caught; live eval 45/45; dry drills with the real LLM, including the
    exact transcript that prompted it.

**Decisions written by Soham:** D36, D37, D40, D41, D43, D44, D45, D46, D51, D52, D53, D54 (main), D55, D56,
D57, D60 (`soham/questions`). D58 and D59 are Aryaman's (on main). The voice decision will be D61.

## 9. Demo (docs/DEMO.md, docs/QA.md: Aryaman owns them)
Soham's last dry run (before Aryaman's #36):
- **Setup:** after a reset, the judge phone gets *"How many people are with you, and does anyone need a
  wheelchair-accessible vehicle?"*.
- **Beat 2:** v2 in about 3.7 s; Accessible Van 3 → #10296, pickup 121 min (deadline 165); Generator 1 ETA 14 → 32.
- **Beat 4:** v3 in about 2.2 s; Generator 1 → Mount Auburn; overflow 0 → 9,600 m³; hospital outage 15 min.
- **Beat 5:** Optimize → 100 runs, chooses c03.

Soham holds the operator phone on stage. **Re-measure after #36, and after #38/#39 merge.**
- The demo path (judge household, `/dev/reset`, role-only phones) still works; the tests cover it.
- One deliberate behaviour change (D57): a *texted* NO to the only accessible van now needs a second NO. The demo
  doesn't use a decline.

## 10. Open items / notes for others (also in docs/log/soham.md)
**Aryaman (engine): what would make the plan itself smarter.** An LLM in the allocator would break hard rule 2 and
can't beat the simulator-scored search. **D58 (main) shipped items 1, 3, 4 (reason text), 5 and 6, and D59 (main)
shipped item 2 (shared trips)**; `briefing.trip_mates` reads it from the rationale ("shares the trip with household #…").
1. **Declines aren't constraints.** `carry_over` and the allocator re-propose a declined (vehicle, household) pair.
   The backend hides it, so the household can end up with nothing although another vehicle is free.
2. **One household per trip.** Neighbours at one corner can't share a van even with seats free.
3. **Every rescue drops off at the response base** (EMS 14), never the Treehouse shelter, even for people standing
   next to EMS 14.
4. **Unthreatened households** (deadline null) are sometimes served (crowded) and sometimes not (solo), and the
   unresolved reason then says "committed to earlier deadlines".
5. **Queue order:** confirming moves work to the front of the vehicle's queue (judge 153 → 21 min).
6. **Optimize at t=0** tags its points v1 but returns v2.

**Others:**
- **Aryaman (DEMO/QA):** update the measured numbers (121 / 15); setup step 6 no longer needs `POST /replan`.
- **Web:** upsert messages by id. Households added by the drill appear in `/state` like any other.
- **Location pins:** iMessage location pins aren't read (Photon text messages only); people type an address, or paste
  a maps link.
- **Task 9** (voice) not started.

## 11. Gotchas that cost time before
- Run `uv sync` after pulling. If tests can't import `residents`: `uv sync --reinstall-package ember-residents`.
- Worker-process code (the local optimize pool) must run from a file, not stdin (macOS spawn).
- Never patch the global `asyncio.sleep` in tests; patch `residents.photon._backoff`.
- Fake Photon timestamps default to *now* (texts from before the last reset are ignored by design).
- FastAPI request models live at module level (postponed annotations).
- `FakeLLM` is keyed on the exact text. A drill test that texts something new must script it (`llm.script[...]`).
- Raising `SystemExit` inside the TestClient's event loop kills the app → the drill raises `SetupError`.
- The view's assignment status is simulated progress (`en_route` at t=0), not `confirmed`. Check the raw plan
  (`store.current_plan()`) for backend statuses.
- `drill.db` keeps phones between runs. Two EMBER backends with Photon on would both answer every text; the drill's
  preflight blocks that.
- Real phones are on the line whenever Photon is enabled. Automated checks use `--dry` / `PHOTON_ENABLED=0`.

## 12. Keep working in a new chat: everything the agent needs
### How Soham wants you to work (his standing instructions)
- **Order of work.** Make a plan, then implement. Explain the code you write and every decision you make (why, and
  the alternative you rejected). Ask when you genuinely need something, e.g. a phone number, a key, a merge, or a
  decision that's his. Otherwise proceed.
- **"Make no mistakes."** Test rigorously and prove the intended behaviour, not just green tests:
  - write tests for every change
  - **mutation-check** new guards: break the line and confirm a test fails; the pattern is in §12.3
  - replay real transcripts
  - run the live LLM eval when the extraction changes
  - do a `--dry` drill with the real LLM before saying it works
  - fix every mistake you find, including old ones (the tester-number scrub, D56)
- **"Don't break anything."** Keep existing tests and public behaviour. When a behaviour must change, say so
  explicitly, update the pinned test on purpose, and write a DECISIONS line (e.g. D57's second NO).
- **Git.** Code only on `soham/*` branches, never `main` or anyone else's branch. Pull/rebase from `main` before every
  push. Soham handed PR handling to the agent ("you can handle PRs from now on"), but merges must be done by Soham
  (the classifier blocks `gh pr merge` for the agent).
- **Phones.** Never send surprise texts to real phones; use `--dry` / `PHOTON_ENABLED=0`. Live sends are only for
  what Soham is actively running. Never write his numbers into files that get committed.
- **Realism.** He wants the drill realistic. Instructions must be genuine (go to this corner, wait inside, meet the
  crew, board, ride, check in), and the plan must reflect other people, free vehicles and distances. He asked about
  an LLM for planning; the agreed answer is **no LLM in planning** (hard rule 2). Make the reasoning visible
  (briefing.py) and push the planning gaps to the engine (§10).
- **Replies to him.** Plain language, what changed and why, exact commands to run, what's verified vs not, and
  honesty about limits (e.g. "not yet tested on a real phone").

### Session history (what was asked, in order)
1. Understand the project and his brief → step-by-step plan with the git workflow.
2. Implement tasks 1–8 with tests → merged PRs #10–#35 (§8).
3. Fix the PR conflict on #10 and act on Aryaman's requests (review #11/#12, CORS 43123, engine wiring, delete the
   residents copy of the WS schema, switch to `EngineSession`) → done.
4. First handoff doc → #37.
5. "We changed the Photon API a bit" (Codex's multi-household commit) → reviewed and PR'd as #38. Then the drill:
   location by text, the plan's questions, YES, step-by-step directions with DONE, the clock moving one step at a
   time, one process → #39 (D56).
6. "Will this run on iMessage?" → yes; explained how to run it.
7. Live crash `PhoneConflict` (a phone changed role between runs) → fixed in #39.
8. Two-phone run felt "hardcoded" → diagnosis: the allocator does plan around everyone, but the texts hid it and the
   decline handling was wrong → D57 in #39, engine asks in §10.
9. This handoff, refreshed twice.
10. "what's the plan?" / "what to do?" got only "passed to the coordinators" → decided against an LLM coordinator
    (or LLM judge): computed answers for every topic + the situation fallback + a real coordinator queue → D60.
    Then: "plan the voice agent (Photon 2.0) so flood-zone residents get a call that works exactly like the texts"
    → `residents/VOICE_PLAN.md`.

### How to verify (commands that worked)
```bash
cd residents
uv run pytest -q                                     # all; ~95 s. Single file: uv run pytest -q tests/test_drill.py
uv run python scripts/eval_extract.py                # live extraction accuracy; add a sample to tests/samples.json (indent=1) for new phrasing
# a scripted dry drill with the real LLM + geocoder (no texts sent): pipe console lines in
printf '@r1 Putnam Ave and Western Ave\n@r1 2 of us\n@r1 yes\n@r1 done\n@r1 done\n@r1 done\nstatus\nquit\n' | \
  uv run ember-drill --dry --db /tmp/x.db --port 8015 --resident 6175550101 2>&1 | sed -n '/^\[t=/,$p'
# mutation check: replace one guard line with a no-op in a copy, run the one test that should catch it, restore.
# The scripts used are deleted; re-create from this description (a list of (file, old, new, test) tuples, assert
# old occurs once, write, run pytest -x on that test, restore in `finally`).
```
- **Tool quirks on this Mac:**
  - `timeout` doesn't exist.
  - Foreground `sleep` is blocked by the harness; run long jobs with `run_in_background`.
  - zsh doesn't word-split `$var` lists (use `xargs -0`).
  - BSD `sed -i ''`.
  - The scratchpad dir from earlier sessions is gone; use `/tmp`.
- **Live state checks:**
  - `curl -s 127.0.0.1:8000/health`
  - `lsof -nP -iTCP:8000 -sTCP:LISTEN`
  - `sqlite3 residents/drill.db "select handle, role, thread_key, assigned_number, last_inbound_at is not null from phones"`
    (this is also where Soham's tester numbers can be read; never copy them into the repo)
  - `tail residents/drill.log`
- **Ask Soham before:** killing a process he started; deleting his DBs; anything that texts real phones outside a
  run he's doing.

### Environment
- **Machine:** macOS (Darwin 24), zsh, Python 3.13.7 (python.org build, so certifi is needed for SSL), `uv` at
  `~/.local/bin/uv`, `gh` (Homebrew), `sqlite3`.
- **Repo:** `/Users/soham/Documents/Coding/HackHarvard/Ember`.
- **Local files (gitignored):**
  - `residents/.env`: real keys (Photon key + project id, Anthropic key).
  - `residents/ember.db`: the demo backend.
  - `residents/drill.db` + `drill.log`: the drill.
  - `data/town.json`: unpacked from `engine/data/town.json.gz` on first use.
- **Ports:** backend / drill on `:8000`; web dev on `:5173` (or `:43123`).
- **Photon:** shared lines are assigned per phone (`POST /phones` → `assigned_number`, e.g. +1 628-998-…). The opt-in
  (space id, agent user id) is learned from the phone's first text and survives runs and resets.
- **Models:** extraction uses `claude-opus-5-5`, effort low, `beta.messages.parse` with
  `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`. Before touching the call, use the claude-api
  skill and don't guess SDK shapes.

### Key data (allston_flood_v1)
- **Fleet** (all start at `ems14`, Boston EMS Station 14 on Western Ave by Stadium Rd):

  | Id | Kind | Seats | Notes |
  |---|---|---|---|
  | `van-1` | van | 6 | usually the reserve |
  | `van-2` | van | 6 | |
  | `van-3` | accessible_van | 6 | **the only wheelchair-accessible vehicle** |
  | `truck-1` | Generator truck | 2 | also used for rescues |
  | `crew-1` | road crew | – | clears roads |
  | `gen-1` | generator | – | 500 kW, camlock |
  | `gen-2` | generator | – | 150 kW, twist-lock |

  Reserve rule: 1 van and 1 generator.
- **Facilities:**
  - `mt-auburn`: hospital, **critical**; the operator thread defaults here
  - `cottage-farm`: pumping station / CSO, drives the overflow m³
  - `putnam-ave-sub`: substation
  - `outfall-mwr201`
  - `ems14`: response base; **every rescue drops off here**
  - `treehouse-shelter`: capacity 200, unused as a drop-off
- **Timing:** `t_end_s` 14400 (4 h), tick 60 s, deadline margin 900 s: a household's deadline is the first flood
  keyframe at its node minus 15 min.
- **Households:** 40 synthetic ones (judge **#10296**, needs unknown); solo mode removes them. The town has 17,810
  buildings; texted-in households are the nearest free building to the point they gave.
- **Flood zone** (pickups needed): Flagg St & Memorial Dr (by 75 min); Akron St & Banks St, Ballord Pl & Putnam Ave,
  Banks St & Elmer St, Putnam Ave & Western Ave, Callender St & Putnam Ave (by 135 min); Memorial Dr & River St, etc.
  (by 165 min). Western Ave near Stadium Rd (123/125 Western Ave) is **outside** it.

### Code conventions in this lane
- Module docstrings explain the why. Comments are short and say what the code can't. Lines up to about 120
  characters. Type hints. `from __future__ import annotations`.
- Messages are f-string templates over computed fields. Every outbound text goes through
  `Messenger.send_message(thread, text, plan_version, assignment_id)`, or `send_to_phone` before a household exists.
- Per-run memory lives in `kv` with a prefix, and **every new prefix must be added to `Store.clear_scenario()`**.
- New settings: a `Settings` field in config.py with an env name, mirrored in `.env.example` and HANDOFF §6.
- **Test helpers** (tests/test_drill.py): fixtures `drill` (solo bridge, auto clock, fake LLM) and `pair` (two
  wheelchair neighbours). Helpers:
  - `Tap(c).outs(handle)`: texts EMBER sent that phone
  - `register(c, handle, locate=True)`
  - `text(c, handle, msg, role=)`: through `/dev/inbound` by handle
  - `place(c, tap, handle, where)`
  - `thread_of`, `clock`, `outcome`
  - `SCRIPT` / `NEIGHBORS`: the fake LLM's answers per exact text
- Engine fixtures: `bridge` (moves=10, full scenario, session-scoped), `solo_bridge`.
- The extraction schema change pattern: add the Field to `Fact`; add it to `NONE` in `tests/test_extract.py` and to
  the two explicit `Fact(...)` calls in `tests/test_conversation.py`; update `SYSTEM`; add live samples; run the eval.

### Next steps (in priority order)
1. Soham merges `soham/questions` (and closes #38/#39). Then re-run the DEMO.md dry run (`RESET_ON_START=1`, Photon
   off, `/dev/inbound`) and send Aryaman the new numbers (D58 changed drop-offs to the Treehouse).
2. **Voice:** Soham answers `VOICE_PLAN.md` §11 (payment method + number, LiveKit project, voice provider). Phases V1–V3
   don't need those and can start immediately.
3. Soham re-tests the drill on both phones with the D57 + D60 code (restart `ember-drill`) from flood-zone corners. Watch
   for: the "why" line in offers, answers to questions, the second-NO check, the steps, and the clock.
4. Aryaman's D58 + D59 shipped the §10 engine list (shared trips included; the texts now say when you share one).
5. Possible residents-side work if asked:
   - read iMessage location pins, if Photon exposes them (`parse_inbound` drops non-text content today)
   - a placed phone correcting its location ("no, I'm at …": `Outcome.location` is extracted but ignored today; part of
     voice V2)
   - a web panel for drill participants (Aryaman's lane: ask)
