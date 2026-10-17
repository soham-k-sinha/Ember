# residents/ HANDOFF: full context for the next agent (Soham's lane)

Last updated: Sat 2026-10-17, afternoon. `main` at `c0c65ba` + this file. **129 residents tests pass on it.**
Hackathon: HackHarvard 2026. **Devpost submission due Sunday 8:00 AM.** Venue closes 8 PM nightly.

Read this file first, then: `CLAUDE.md` (hard rules), `docs/HANDOFF.md` (team-wide status, Aryaman's),
`docs/DECISIONS.md` (D1–D54), every `docs/log/*.md`, `docs/team/soham.md` (the brief), `residents/README.md` (API).

---

## 1. The project in one paragraph
**EMBER** is a disaster *coordination* system for an urban flood (the Charles River) in one district around the
David Rubenstein Treehouse (Harvard, Allston), the hackathon venue. It keeps one shared picture: water,
closed roads, 40 households that need help, a hospital, a sewage pumping station, vans and generators. A
**deterministic, simulator-scored allocator** produces one coordinated plan plus a personal instruction per household.
Real people (a resident and a hospital operator) take part **by iMessage over Photon 2.0**. **One LLM call** turns a
free-text message into a structured fact; the planner replans in ~0.5 s and only the *changed* instructions are texted
back. Plans are stress-tested on **Daytona** sandboxes. The sustainability metric is **m³ of untreated sewage kept out of
the Charles**, inside the objective. It beats an incident-by-incident baseline (5 seeds: about +53 people reached
before deadline, less hospital outage, less overflow).

**The demo moment:** the judge, playing household **#10296**, texts something like *"2 of us, one is in a wheelchair, River St
is blocked"*. That text changes both their own rescue (they get Accessible Van 3) and an infrastructure decision
(Generator 1 is rerouted). The judge can see why on the map.

## 2. Hard rules (from CLAUDE.md; enforced in code here)
1. **Contracts are the interface** (`contracts/*.schema.json` + fixtures). Changing one = bump version, update fixture, line in DECISIONS. `contracts/` is **Aryaman's lane**.
2. **No LLM in the tick loop / planner.** The only LLM call is `residents/residents/extract.py`. It never produces routes, times or assignments.
3. Agents are rows, not personas. 4. Time = `t_s` seconds since sim start; coordinates `[lon, lat]`; meters, m/s.
5. Hazards: `polygon_at(t)` / `closed_edges_at(t)`. 6. Engines are plug-ins. 7. 2D sim (2.5D *view* allowed, D50).
8. Daytona Tier 1/2 has no internet egress; results come back as return values. 9. **Photon = Beta / 2.0** (`api.photon.codes/v1`): shared iMessage lines, **the tester must text first**, no group chats, no calls.
10. Label what's synthetic.
- Every outbound text starts with **`[EMBER drill]`** and carries its **`plan_version`**. Nobody is auto-assigned to help a stranger; offers stay provisional until confirmed.
- **Secrets only in `residents/.env`** (gitignored). Never commit keys or the tester phone numbers.

## 3. Team and lanes (`.github/OWNERS.json`, CI-enforced)
| Person | GitHub login | Lane (paths a PR may touch) | Doing |
|---|---|---|---|
| **Soham (you)** | `soham-k-sinha` (repo owner) | `residents/` + `docs/log/soham.md` + `docs/DECISIONS.md` | backend, Photon, LLM extraction, replan loop |
| Aryaman | `aryamangoenka` | `engine/`, `contracts/`, `.github/`, `CLAUDE.md`, `docs/{TECHNICAL,HANDOFF,SIM_ENV_PLAN}.md`, `docs/team/` **and, since D49, also `web/`, `scenarios/`, `docs/DEMO.md`, `docs/QA.md`, `docs/devpost/`** | engine (world, hazards, simulator, allocator, baseline, compare, Daytona, `EngineSession`), contracts, now also the web UI and the demo script / QA checklist |
| Arnav | `aarnavkhanna` | `web/` | web (Vite + React + deck.gl); Aryaman also covers it now |
| Anshuman | `anshunevatia-del` | `scenarios/`, `docs/DEMO.md`, `docs/QA.md`, `docs/devpost/` | scenario `allston_flood_v1`, sources/assumptions; Aryaman also covers it now |

Never edit another lane. Notes for others go in **your own log** (`docs/log/soham.md`) and in chat.

## 4. Git / GitHub protocol (non-negotiable)
- Repo: `https://github.com/soham-k-sinha/Ember`. `origin` is that. **Integration branch = `main`** (also the GitHub default
  branch now; it used to be `aryaman/sim-env`, so keep passing `--base main`). `gh` is installed and authenticated as `soham-k-sinha`.
- **CI `ownership / check`** (`.github/ownership.py`) fails a PR that touches files outside your lane or whose branch doesn't start with `soham/`. GitGuardian also scans for secrets.
- Per feature:
```bash
git checkout main && git pull --ff-only origin main
git checkout -b soham/<topic>
# … work, test …
git add residents docs/log/soham.md docs/DECISIONS.md      # never `git add -A`
git commit -m "residents: <what and why>"                    # end with the Co-Authored-By line if an agent wrote it
git fetch origin && git rebase origin/main                   # ALWAYS before pushing
(cd residents && uv run pytest -q)                           # must pass after the rebase
AUTHOR=soham-k-sinha BASE=origin/main HEAD=HEAD HEAD_REF=soham/<topic> python3 .github/ownership.py   # local lane check
git push -u origin soham/<topic>                             # --force-with-lease only if you rebased an already-pushed branch
gh pr create --base main --head soham/<topic> --title … --body …
gh pr checks --watch                                          # wait for ownership + GitGuardian
gh pr merge <n> --squash --delete-branch                      # self-merge allowed: only your lane changed and pytest passes
git checkout main && git pull --ff-only origin main
```
- **Nothing is ever committed directly to `main` or to anyone else's branch.**
- **DECISIONS.md conflicts are routine.** Others append too. Keep *all* lines and renumber yours to the next free `D<n>`
  (also fix the number in your log entry). Check with `grep -o "^| D[0-9]*" docs/DECISIONS.md | sort | uniq -d` (must print nothing).
- **Log protocol:** after every feature, append an entry to `docs/log/soham.md` (template in `docs/log/README.md`:
  What / Files / Run / Interfaces / Status / Next). At session start, read all logs + DECISIONS.

## 5. Architecture
```
scenarios/allston_flood_v1/scenario.json  (flood keyframes, facilities, fleet, 40 households, judge #10296)
engine/data/town.json.gz                  (shared OSM town: 586 nodes, 1,196 edges, ids everyone uses)
        │
engine/ember_engine  (Aryaman)  world · hazards · models · sim (plan simulator, state_at) · allocator (allocate/replan,
        │                       rationale, info_requests, changes) · baseline · compare · daytona (robust fan-out)
        │                       api.EngineSession  ← the ONLY entry point residents uses (D42)
        ▼
residents/  (Soham)  FastAPI + SQLite.  DB is the source of truth; engine is resumed from it on every call.
   Photon 2.0 ⇄ phones        WS /ws + HTTP  ⇄  web/ (Aryaman/Arnav: deck.gl map, panels, scatter, comparison)
```
**State model (D41):** the backend owns the sim clock, live reports (with original text/confidence), every raw
allocator plan version (+ which reports it saw), messages, phones. Everything else is derived:
`EngineSession.resume(plan, reports)` → `state_at(clock)` after each replan/clock move. The state shows the snapshot's view of
the plan (routes + as-of-t statuses), with `search` and `replan_latency_s` carried over from the raw plan.

### residents/ files
| File | Role |
|---|---|
| `residents/app.py` | FastAPI app factory `create_app(settings, photon_client=, bridge=, llm=)` (injection for tests); lifespan wires store → hub → planner → messenger → outbound → intake → **then** bootstraps (so v1's questions get texted) → Photon listener → failed-send retry loop. All endpoints. |
| `config.py` | `Settings` from env / `residents/.env`. |
| `db.py` | stdlib sqlite3 `Store`. Tables: meta, closures, households, facilities, resources, reports, plans(+reports_used), assignments, messages(+delivery, external_id, created_wall), phones, **kv** (cursor, pending/instr/asked/rejected/run_started_at), **inbound_seen**. Contract objects stored verbatim as JSON (D36). `snapshot()` → state contract. Small migrations in `_migrate()`. |
| `bus.py` | WS hub; envelope `{type, seq, t_s, data}` (`contracts/ws-events.schema.json`); `seq` +1 per broadcast; connect sends `state` with the current seq. |
| `engine_bridge.py` | The only file importing `ember_engine`. Uses `EngineSession` (resumed from DB each call). `optimize()` runs on a **separate** EngineSession **and separate World** (World's caches aren't thread-safe). `resolve_road()`: street name → town edges (normalized names; at a cross street, else engine's `edges_by_name(…, radius_m=150)` near the household; both directions). |
| `planner.py` | The replan loop. `bootstrap`, `submit_report` (validate against report.schema + refs), `replan` → `_store_plan` → `_publish` (WS `plan`, one `assignment` per change, `metrics`, then plan hooks). `set_clock`, `respond` (confirm/reject + stale check), `optimize` (fan-out **outside** the lock; superseded if the plan moved), `simulate`, `comparison` (cached per version), `close_road`, `set_facility`. One asyncio lock; engine work in a threadpool. |
| `contracts.py` | jsonschema validators over `contracts/` (`validate_report`, `errors`, `def_errors`). |
| `photon.py` | Photon transport. `PhotonClient` (httpx; retries 429/5xx with the **same Idempotency-Key**; `_backoff` hook for tests). `parse_inbound`. `PhotonListener`: Socket.IO at `/v1/projects/{id}/events/ws`, `subscribe {startSeq}`, serial `delivery` worker, durable cursor, **reconnects forever**; polling fallback after 5 s down, window kept fresh while subscribed and capped at 10 min (D54). certifi SSL context (macOS python.org builds lack CA certs). |
| `threads.py` | One phone per household/facility (D55, Codex-authored on Soham's branch): `phone_thread`, `phone_for_thread`, `select_thread`; role defaults (`resident` → judge household, `operator` → critical hospital) only when no target is given. `unplaced()`: a resident registered with `locate` that has no household yet (D56). `normalize_handle`. |
| `places.py` | Where a resident is (D56): `parse_coords` (typed / maps links), `Gazetteer` over town.json (street intersections, nearest free building, pickup-corner names, distance/bearing), `nominatim()` address lookup bounded to the town. |
| `locate.py` | `Locator` (D56): texts from unplaced phones (the "lobby"): ask where they are → LLM pulls the place (+ any needs) → `Gazetteer.locate` → nearest free building becomes an assisted household of this run (`planner.add_household`, kv `extra_households`) → phone bound → one replan (the plan asks / offers). Welcomes opted-in unplaced phones after a reset. |
| `guide.py` | `Guide` (D56): after YES, one text per step from the plan simulator's arrive / pickup / drop-off times (`bridge.outcomes`): rescue = get ready + walk to the corner (or wait inside for a door pickup) → board → ride → checked in; protect = meet the crew → connecting → powered. DONE replies (regex, or the LLM's `done` fact); `auto_clock` jumps the sim clock to the next event once nobody is pending. kv `guide:<thread>`. |
| `drill.py` | `uv run ember-drill`: one process = backend + phone registration + a console printing every text, with `status / next / +N / @r1 text / close / reset`. Preflight refuses to run next to another Photon-enabled EMBER. |
| `messaging.py` | `Messenger`: inbound (dedupe by id + `inbound_seen`, ignore texts from before the last reset, learn space/agent ids from the first text = opt-in) → stored message → WS → hooks. `send_message`: drill prefix, plan_version, opt-in enforced (`not_opted_in`), `delivery` = sent/failed/dev/no_phone. `retry_failed`. |
| `extract.py` | **The one LLM call.** Claude Opus 5.5 (`EXTRACT_MODEL`), effort low, structured outputs (`beta.messages.parse` + Pydantic `Extraction{facts[], confidence, clarifying_question}`), server-side refusal fallback. `to_outcome()` is deterministic: confidence < 0.6 → question; need without head count → hold `pending` + ask; **merge with known needs** (D46); closure → `resolve_road` or ask; `endurance_min` → `backup_endurance_s` (D53); confirm/reject only if something was offered. |
| `intake.py` | Inbound hook, **serialized**: extract → reports (dupes skipped) → **one** replan per text → `report_id` on the message → reply: missing-info question, else (after a replan) instruction or "Got it." + status, else for chatter: plan's open question → status → model prompt; questions → "passed to the coordinators". Planner failure → honest text. YES/NO → `planner.respond`. |
| `outbound.py` | Plan hook. Per opted-in thread, texts only when **its** instruction materially changed (new/replaced vehicle, cancelled, ETA ±10 min; D44). Marks `offered`; confirmed changes → "Update: …". Never re-offers a declined vehicle. Asks `info_requests` once. `status_text` / `ack` / `latest` templates. |
| `tests/` | 173 tests (`test_drill.py`: the whole text-driven drill on the real allocator with no synthetic households) (no network, no paid API: Photon faked at HTTP layer `fake_photon.py`, LLM faked `FakeLLM`; `EMBER_LOCAL_POOL=1`; engine at `moves=10`, demo-beat test at full search). `samples.json` = 27 messages for the live eval. |
| `scripts/eval_extract.py` | Live accuracy of the LLM call on samples.json (real API, ~$0.20). Last run **27/27, median 2.2 s** (2026-10-17, incl. location and DONE replies). |

### API (full table in residents/README.md)
`GET /health` · `GET /state` · `GET /plan/current` · `GET /plan/{v}` · `WS /ws` · `POST /reports` · `POST /disruption`
(`close_edges` or `facility_id`+`set`) · `POST /replan` · `POST /clock {t_s}` · `GET /comparison?seeds=` · `POST /optimize?seeds=&k=` (202) +
`GET /optimize` · `POST /simulate {planner}` · `POST /ask {role, question?}` · `POST /assignments/{id}/confirm|reject {plan_version?}` ·
`GET/POST /phones {role, handle, household_id?|facility_id?|locate?}` · `POST /messages` · dev: `POST /dev/reset`, `POST /dev/inbound {role, text, household_id?|facility_id?|handle?}`.
WS events: `state`, `plan`, `assignment` (incl. `status_changed`), `message` (re-sent when its report_id is set; upsert by id), `report`, `metrics`, `scatter_point`.
The web calls `/state`, `/clock` (every 1.2 s while playing), `/disruption`, `/replan`, `/comparison`, `/optimize`, `/ws`; CORS allows `:5173` and `:43123`.

## 6. Running it
```bash
cd residents && uv sync
cp .env.example .env     # PHOTON_ENABLED, PHOTON_API_KEY, PHOTON_PROJECT_ID, ANTHROPIC_API_KEY (already filled in on Soham's laptop)
uv run uvicorn residents.app:app --port 8000                       # keeps the existing DB
RESET_ON_START=1 PHOTON_ENABLED=1 uv run uvicorn residents.app:app --port 8000   # demo start: fresh plan v1
uv run ember-drill --resident <phone> [--crowded] [--dry]          # a whole drill by text, one process (README "The drill")
uv run pytest -q                                                   # ~90 s
uv run python scripts/eval_extract.py                              # live LLM accuracy (costs a little)
curl -s localhost:8000/state > /tmp/s.json && uv run --project ../engine ember validate-state /tmp/s.json --scenario ../scenarios/allston_flood_v1/scenario.json
```
Env knobs: `SCENARIO` (default allston; empty = static fixture mode, engine endpoints 503), `START_T_S`, `ENGINE_MOVES`,
`DB_PATH` (default `residents/ember.db`), `RESET_ON_START`, `DEV_ENDPOINTS`, `PHOTON_LISTEN`, `RETRY_EVERY_S`,
`OPERATOR_FACILITY_ID`, `EXTRACT_ENABLED|MODEL|EFFORT`, `CORS_ORIGINS`, `GEOCODE` (Nominatim, default on), `DRILL_SOLO`,
`AUTO_CLOCK`, `DRILL_RESIDENTS` / `DRILL_OPERATORS` (drill phones; .env only). Python is 3.13 here (pin allows 3.12–3.13).

**Phones:** two testers are registered (roles `resident` = judge phone, `operator` = Soham's phone), assigned to Photon
shared lines, opted in. See `GET /phones` for numbers and lines. Registrations survive resets. **Every `/dev/reset` or
`RESET_ON_START=1` texts the judge phone plan v1's question** (D53); that's the DEMO setup step, so expect it.
**A Photon outage** is covered: sends are retried; texts arrive via polling; `/dev/inbound` is the stage fallback.

## 7. What Soham's brief asked (docs/team/soham.md) and status
| # | Task | Status / PR |
|---|---|---|
| 1 | Skeleton + DB, GET /state, WS | ✅ #10 |
| 2 | Photon plumbing (2 phones, inbound socket, send with plan_version) | ✅ #13, live-verified |
| 3 | LLM extraction + 20 samples + accuracy | ✅ #15 (now 21/21), D43/D46/D53 |
| 4 | Reports + replan loop, only changed instructions texted | ✅ #14, #16 (D41, D44) |
| 5 | Confirm / reject, stale versions | ✅ #17 (D45) |
| 6 | Operator thread (info_requests prompts → facility_status) | ✅ #16 + #32 (`/ask`) |
| 7 | Disruption, simulate, comparison, scatter forwarding | ✅ #14, #16, #32 |
| 8 | Robustness (dupes, two replies, old versions, Photon outage) | ✅ #29, #35 |
| 9 | Voice (stretch, only if green-lit at the SpaceXAI workshop) | ❌ not started; cut unless green-lit |

## 8. Everything Soham's lane changed (merged PRs, in order)
- **#10 backend-skeleton:** FastAPI + SQLite store (JSON-in-row), GET /state round-trips the fixture exactly, WS hub, draft ws-events schema (later moved to contracts/ by Aryaman, #11 approved by Soham). Bug: the seed version was hard-coded to 0.1 and broke when state went to v0.2 → now read from the schema.
- **#13 photon-plumbing:** Photon from the live OpenAPI (project-scoped paths), socket listener, polling, opt-in-safe sends, `/phones`, `/messages`, `/dev/inbound`. Bugs found live: `/health` crashed on the loop clock in a worker thread; socket SSL failed on macOS → certifi.
- **#14 engine-bridge:** engine mode on Allston, `/reports` → replan → WS events, `/disruption` (both directions), `/clock`, `/comparison`. Bug: `replan_latency_s` was dropped by the snapshot → carried over.
- **#15 llm-extraction:** the one LLM call, ask-never-guess, street resolution, one replan per text. Found: the judge is AT River St × Memorial Dr; closing River St wide cut them off.
- **#16 optimize-outbound:** material-change texts, `offered`, info requests once, `POST /optimize` streaming scatter points. Bugs: plan hook NameError swallowed; generator spec doubled; `offered` lost on replan.
- **#17 confirm-reject:** stale-version check, sticky confirmations, no re-offer of declined vehicles. Bug: a request model defined inside `create_app()` was invisible to FastAPI (postponed annotations) → body silently ignored; regression test checks every JSON endpoint declares a body.
- **#19 conversation-fixes (from the first real-phone run):** "Yes, 2 people" erased the wheelchair need → non-accessible truck assigned (critical) → needs now merge; every fact gets a reply; chatter → plan question / status. Replay test.
- **#22 engine-session:** all engine calls via `EngineSession` (Aryaman's request), verified identical to the direct path.
- **#29 robustness:** serialized intake, dupes, planner-failure handling, send retries, 150 m street resolution matching the tuned beat; tests stopped patching global `asyncio.sleep` (it deadlocked); `EMBER_LOCAL_POOL=1`; adopted `EngineSession(moves=)`.
- **#32 operator-simulate:** `/ask`, `/simulate`; `/optimize` outside the lock on its own World (World caches race across threads).
- **#34 demo-dry-run:** full DEMO.md dry run passed; v1 questions texted on reset; endurance in minutes (10 min = 600 s, was 612).
- **#38 multi-household-phones (Codex-authored, D55):** one phone per household/facility, many testers on one plan, 409 instead of silent replacement, opt-in guidance.
- **soham/drill (D56):** residents text their location and get placed; step-by-step directions with DONE replies; the clock steps with the texts; `ember-drill`. Found: the engine sends no vehicle to an unthreatened household (solo), and our status text blamed busy vehicles → now "outside the forecast flood area: shelter in place". Tester numbers removed from tests (555 placeholders).
- **#35 replay-guard (INCIDENT):** at a restart Photon was slow → socket gave up → stale poll window + reset-emptied dedupe → 6 old texts re-answered on the judge test phone. Fixed with a run boundary, `inbound_seen`, bounded poll window, socket retries forever. Verified live: 7 redelivered events → 0 texts.
Decisions written by Soham: **D36, D37, D40, D41, D43, D44, D45, D46, D51, D52, D53, D54, D55, D56.**

## 9. Demo (docs/DEMO.md, docs/QA.md: Aryaman owns them)
Measured by Soham's dry run (real LLM + allocator, Photon off): setup after reset → judge phone gets *"How many people are
with you, and does anyone need a wheelchair-accessible vehicle?"*. **Beat 2** (clock 5:00) judge text → v2 in ~3.7 s,
Accessible Van 3 → #10296 pickup **121 min** (deadline 165; DEMO.md still says 132), Generator 1 ETA 14 → 32 min, judge texted.
**Beat 4** (clock 15:00) operator *"…on backup and it has about 10 minutes left"* → v3 in ~2.2 s, Generator 1 → Mount Auburn,
Cottage Farm unresolved, overflow 0 → 9,600 m³, hospital outage **15 min** (DEMO says 16), operator texted. **Beat 5** Optimize →
100 runs, chooses c03 over c00, judge's van + hospital generator unchanged. Soham holds the **operator phone** on stage.
Re-measure after Aryaman's #36 (generator re-targeting change) before quoting numbers.

## 10. Open items / notes for others (also in docs/log/soham.md)
- **Aryaman (engine):** `rejected` isn't understood by `carry_over` (declined pairs get re-proposed; the backend hides them and keeps them `rejected`). Confirming moves work to the front of the vehicle's queue (judge 153 → 21 min). At t=0, `optimize` tags points v1 but returns v2.
- **Aryaman (DEMO/QA):** update the measured numbers (121 / 15). Setup step 6 no longer needs `POST /replan`.
- **Web:** upsert messages by id; each `/clock` already broadcasts a full `state` (the web also refetches /state).
- Residents' questions ("is the bridge open?") are stored as `question` reports and acknowledged; nobody answers them automatically.
- **Aryaman (engine):** an unthreatened household (deadline null) with known needs gets no vehicle when it's the only household (solo), but does in the full scenario; the unresolved reason then says "committed to earlier deadlines". The backend now tells such residents to shelter in place.
- The drill's flood zone is the Cambridgeport/Riverside side (Putnam Ave, Banks St, Memorial Dr × River St); Allston addresses are mostly outside it, so they get "shelter in place". `ember-drill` prints corners to try.
- Task 9 (voice) not started.

## 11. Gotchas that cost time before
- Run `uv sync` after pulling (engine is an editable path dependency). If tests can't import `residents`: `uv sync --reinstall-package ember-residents`.
- Worker-process code (the local optimize pool) must be run from a file, not stdin (macOS spawn).
- Never patch the global `asyncio.sleep` in tests; patch `residents.photon._backoff`.
- Fake Photon timestamps default to *now* (texts before the last reset are ignored by design).
- Request models for FastAPI must live at module level (postponed annotations).
- The live server keeps its DB across restarts; `RESET_ON_START=1` / `/dev/reset` start a new run (and text the judge's question).
- Real phones are on the line whenever `PHOTON_ENABLED=1`. For dry runs use `PHOTON_ENABLED=0` + `/dev/inbound`.
