# EMBER — technical execution plan

Status: locked 2026-10-16 (Fri night). This is the single source of truth for *what* we build and *how the work is split*. Per-person instructions live in `docs/team/<name>.md`; running logs in `docs/log/<name>.md`; decisions in `docs/DECISIONS.md`. Verified sponsor/tech facts are in `docs/EMBER-hackharvard-2026-plan.md` (cite it, don't re-research).

---

## 0. The product in one paragraph

EMBER is a disaster coordination system. During an urban flood in one district around the Treehouse, it keeps one shared picture of the situation (water, roads, people, facilities, resources, reports), asks real people for the facts that would change a decision, searches over candidate response plans with a constrained allocator and a simulator, and produces **one coordinated plan for the district plus a personalized instruction for every participating household**. It optimizes for people reached before their deadline, critical services kept running, and **untreated wastewater kept out of the Charles (m³)**, with reserves held back for the unknown. Residents and facility operators participate over Photon (text; voice as stretch). Candidate plans are stress-tested in parallel on Daytona.

**Demo success:** a judge, playing a resident, supplies an unexpected fact ("we need an accessible vehicle, and the pickup road is blocked"), watches it change both their own rescue assignment *and* an infrastructure decision (where the generator goes), and can inspect why the revised plan performs differently.

---

## 1. Architecture

```
scenarios/allston_flood_v1/scenario.json      (Anshuman)  district, flood keyframes, facilities, resources, assisted households, judge
data/town.json                                (engine)    roads, footways, buildings→households, assets, exits   [built, 4.3 MB]
                 │
                 ▼
┌────────────────────────────── engine/ (Aryaman) ──────────────────────────────┐
│ world.py (graph, routing)   hazards.py (flood keyframes → closed edges)       │
│ models/: facilities + wastewater, resources, assisted households + deadlines  │
│ sim/: plan executor (event timeline) → metrics                                │
│ allocator/: candidate generation + constraints + lexicographic objective      │
│ baseline.py: incident-by-incident planner                                     │
│ run_job(world, scenario, plan, perturbation) → metrics     (pure, no I/O)     │
│ daytona/: sandbox pool, fan-out, robust selection (worst-20%)                 │
└───────────────────────────────────────────────────────────────────────────────┘
                 │ python import                      ▲ job list / metrics
                 ▼                                    │
┌──────────────── residents/ = backend (Soham) ────────────────┐     ┌──────── web/ (Arnav) ────────┐
│ FastAPI · SQLite shared state · plan versions · reports      │ WS  │ deck.gl map, ledger,         │
│ Photon 2.0 Beta threads (resident, operator) · LLM extract   │◄───►│ household/facility inspector,│
│ POST /reports → replan → outbound messages (plan_version)    │     │ conversation, comparison,    │
│ WS /ws events: state, plan, assignment, message, scatter     │     │ scatter, rationale           │
└──────────────────────────────────────────────────────────────┘     └──────────────────────────────┘
```

Hard rules (from `CLAUDE.md`): no LLM in the simulation or allocator; the only LLM call turns free text into a structured report. Agents are rows. 2D simulation, 2.5D map view (tilted camera + extruded buildings, D50). Unknowns stay unknown (asked or enumerated), never invented.

---

## 2. Shared state (lives in the backend DB; engine reads a snapshot of it)

| Table | Columns (essentials) | Written by |
|---|---|---|
| `hazard` | keyframes `[(t_s, polygon)]`, `observed_at`, source | scenario (+ reports can add local closures) |
| `edges` | from `town.json` + `closed_from_t`, `closure_source`, `confidence` | engine (hazard), reports |
| `households` | id, lon/lat, node, size, vehicles, flags, **assisted** (bool), `needs {people, mobility, accessible_vehicle}`, `deadline_s`, `status` (unknown/needs/assigned/confirmed/picked_up/safe/unreached) | scenario, reports, sim |
| `facilities` | id, type (hospital/pumping_station/substation/outfall/response_base), node, `state` (ok/backup/down), `backup_endurance_s`, `power_kw_required`, `connector`, wastewater params (`storage_m3`, `storage_max_m3`, `inflow_m3ph`, `pump_m3ph`, `downstream_ok`), `depends_on[]`, `consequence` | scenario, reports, sim |
| `resources` | id, kind (van/accessible_van/truck/crew/generator), node, `capacity_people`, `accessible`, `kw`, `connector`, `fuel_l`, `status` (available/en_route/working/reserved), `assignment_id` | scenario, sim |
| `reports` | id, `source` (resident/operator/responder/judge), `household_id|facility_id`, `kind`, payload, `observed_at`, `confidence`, `resolved` | Photon → LLM extract → backend |
| `plans` | `version`, created_at, `assignments[]`, `unresolved[]`, `rationale[]`, `metrics`, `parent_version` | allocator |
| `assignments` | id, plan_version, resource_id → target (household or facility), `eta_s`, `deadline_s`, `status` (proposed/offered/confirmed/rejected/done), `route_edges[]` | allocator, confirmations |
| `messages` | id, thread (household/operator), direction, text, `plan_version`, `assignment_id`, sent_at | backend |

Every outbound message carries the `plan_version` it was generated from; a reply against an older version triggers a replan check.

---

## 3. Engine (Aryaman) — `engine/ember_engine/`

### 3.1 Already built (Friday)
`build_town.py` (OSM → `data/town.json`; venue pinned to its OSM footprint, D13), `world.py` (graph, reverse-Dijkstra next-hop routing under closures), `hazards.py` (polygon interface; ellipse + keyframes; closure by line intersection, D14), `engines/queue_traffic.py` (ambient vehicle flow; optional in the demo), `run_job.py`, `render_png.py`, `cli.py` (`build · smoke · render · gate-a · fixtures`), contracts schemas + tests.

### 3.2 Flood hazard
`KeyframePolygonHazard` from `scenario.hazard.keyframes` (lon/lat rings). Keyframes authored in `scenarios/` from public flood layers (FEMA NFHL via MassGIS; Boston Climate Ready layers) scaled over a storm timeline (e.g. t=0 dry → t=90 min riverfront roads → t=3 h crest). Edge closure = polygon intersects edge line. **Deadline for a household** = first keyframe time whose polygon contains its node, minus a margin (`scenario.deadline_margin_s`, default 900). Facilities get `threatened_at_s` the same way.

### 3.3 Models (`models/`)
- **Facilities.** State machine per facility: `ok → backup (on generator/backup power, endurance counts down) → down`. Dependencies as edges (`substation → pumping_station`, `substation → hospital`, `pumping_station → outfall`). A facility goes `backup` when a dependency goes `down` and it has endurance; `down` when endurance hits 0 or no backup. A deployed compatible generator (kW ≥ required, connector match) returns it to `ok` after `connect_s`.
- **Wastewater (the sustainability mechanism).** Per pumping station, per tick: `pumped = min(pump_m3ph, downstream_capacity) if powered else 0`; `storage += (inflow − pumped)·dt`; if `storage > storage_max`: `overflow += storage − storage_max; storage = storage_max`. Metric: `overflow_m3` total, and the time series for the panel. Inflow can rise with the flood (`inflow_m3ph(t)` keyframed).
- **Resources.** Position on the graph; move along the current shortest open route at edge free-flow speed (closures mid-route → re-route or stall; stall counts as delay). Work = `service_s` at the target (pickup time, connect time). Fuel = distance × l/km. `reserved` resources are never assigned.
- **Assisted households.** The scenario marks ~40 households (≈100 people) as `assisted` with needs; all other households stay on the map as background (optional ambient traffic from `queue_traffic`). Needs can be *unknown* until a report arrives (the judge's household starts unknown).

### 3.4 Simulator (`sim/`)
Executes a plan as an event timeline on the shared-state snapshot: dispatches, travel on the closed-edge-aware graph, pickups (capacity, accessibility), drop-offs at the response base/shelter, generator deployment and connection, facility state transitions, wastewater integration, road closures from the hazard, and report-driven changes (a reported closure applies at its `observed_at`). Tick 60 s is enough (people and vans, not traffic waves). Outputs `metrics`:
`people_reached_before_deadline, people_unreached, unresolved_needs, hospital_outage_s, service_outage_s_total, overflow_m3, fuel_l, vehicle_km, infeasible_assignments, reserve_remaining, replan_latency_s` plus per-assignment outcomes and a timeline for replay.

### 3.5 Allocator (`allocator/`)
Search over plans with the simulator as the oracle; the allocator never trusts its own arithmetic over the simulator's.
- **Tasks:** rescue(household) and protect(facility) (generator deploy; crew road-clear optional).
- **Constraints (hard):** resource availability; capacity ≥ people; `accessible` if mobility; generator kW/connector compatibility; crew qualification; a route must exist under closures at dispatch time; arrival ≤ deadline; reserve rule (keep ≥ `scenario.reserve.vans` vans and ≥ 1 generator unassigned when feasible).
- **Objective (lexicographic):** (1) people unreached before deadline ↓, (2) hospital/critical-service outage s ↓, (3) `overflow_m3` ↓, (4) fuel + vehicle-km ↓, (5) reserve kept ↑. The environmental term sits inside the search, not after it.
- **Algorithm (hackathon-feasible):** generate K≈20–50 candidate plans from priority rules (deadline-first, dependency-first: fix upstream before downstream, nearest-first) plus random pairwise swaps/reassignments; simulate each; keep the lexicographic best. **Replan** = same procedure from the *current* state (resources keep their progress; confirmed assignments are sticky unless infeasible). Target: < 2 s per replan locally for the demo district.
- **Rationale:** each assignment gets a one-line computed reason ("gen-2 → pumping station: overflow in 38 min vs hospital endurance 9 h; travel 11 min via Western Ave"). The web shows it verbatim.
- **Unmet needs output:** what remains unresolved, which constraint blocked it, what resource/info would unblock it, alternatives.

### 3.6 Baseline (`baseline.py`)
Incident-by-incident: alerts processed in arrival order, each served by the nearest available compatible resource, no lookahead, no dependency awareness, no reserve. Same state, same resources, same scenario, same seed.

### 3.7 Robustness (`daytona/`)
`run_job(world, scenario, plan, perturbation) → metrics`. Perturbations: travel-time multipliers (0.8–1.6), one resource failure, facility endurance ±30%, storage ±30%, sewage inflow 0.8–1.3×, the storm up to 30 min ahead of its forecast (D94), a random extra closure, report delays. For the top candidates, run M≈20 perturbations each in parallel on Daytona sandboxes (pool of N long-lived sandboxes, world + scenario baked into the snapshot, stateful `code_interpreter`, results via return value; see plan §6.5). Pick the plan with the best **worst-20%** of (people unreached, then overflow). Stream each result to the backend as a `scatter_point`. Local `multiprocessing` fallback behind an env flag.

### 3.8 CLI additions
`ember validate-scenario <path>` (schema + referential checks: nodes exist, households exist, generators have connectors…), `ember simulate --scenario … --plan baseline|ember`, `ember compare --scenario … --seeds 5` (writes `comparison.json`), `ember replan --state state.json --report report.json`.

---

## 4. Backend = `residents/` (Soham)

- **Stack:** FastAPI + SQLite (file), `httpx`, `python-socketio` client (Photon events), one LLM client. Runs on a laptop with a hotspot; optional small VM / Cloudflare Tunnel if the voice vendor needs a public URL.
- **Endpoints:** `GET /state`, `GET /plan/current`, `GET /plan/{version}`, `POST /reports` (structured), `POST /disruption` (close edge / set facility field; used by the judge via the map), `POST /replan`, `POST /assignments/{id}/confirm|reject`, `GET /comparison`, `POST /simulate` (baseline|ember), `WS /ws` (events: `state`, `plan`, `assignment`, `message`, `report`, `scatter_point`, `metrics`).
- **Photon 2.0 Beta** (`api.photon.codes/v1`, Python client `photonhq-api`): one shared iMessage assignment per tester phone (resident, operator); testers text first (opt-in rule); inbound via Socket.IO `message.received`; outbound `POST /messages` with `Idempotency-Key`; every message stored with `plan_version`. Email channel for the operator role if iMessage assignment slots run short.
- **LLM extraction** (the only LLM call): input = message text + the thread's role and household/facility record; output JSON `{kind: need|closure_report|facility_status|confirm|reject|question|other, people, mobility, accessible_vehicle, road_hint, cross_street, endurance_h, storage_pct, confidence}`. Low confidence → one clarifying question. Never emits routes, times or assignments. A `report` row is written and the planner is invoked.
- **Replan loop:** report → `engine.allocator.replan(state)` → new plan version → diff assignments → send only changed instructions ("[EMBER drill] Van 3 will pick you up at 14 Elm in 12 min. Reply if anything changed."). Offers are `offered` until the recipient confirms.
- **Operator thread:** scripted prompts ("What's your backup endurance now?") when the allocator flags a decision-changing unknown (`info_requests[]` in the plan).
- **Safety:** every message starts with "[EMBER drill]"; no implied official authority; nobody is auto-assigned to help a stranger.

---

## 5. Web (Arnav) — `web/`

- **Stack:** Vite + React + TypeScript, deck.gl 9.4 (`@deck.gl/maplibre`, `react-map-gl/maplibre`, CARTO basemap, no token), Zustand or plain context for state, a tiny WS client.
- **Layers:** roads (PathLayer; closed = red), flood polygon (PolygonLayer, keyframed by the sim clock), households (ScatterplotLayer; assisted ones colored by status; judge highlighted), facilities (IconLayer/Scatterplot with state badge), resources (moving dots along their route; interpolate between snapshots), assignments (ArcLayer resource → target), venue star. Optional ambient trips (TripsLayer from `trajectories.json`).
- **Panels:** resource ledger (status, assignment, ETA, fuel), household/facility inspector (status, needs, dependencies, rationale, message thread), conversation history (both threads), unresolved needs, **outcome comparison** (baseline vs EMBER table per metric with B−A and a spread note), **scatter** of robustness runs filling live, plan-version timeline (v1 → v2 → v3 with what changed).
- **Controls:** play/pause/scrub sim clock; "close this road" (POST /disruption); "replan"; "run comparison".
- **Data path:** fixtures first (`contracts/fixtures/*.json`), then live `/state` + WS. The UI must run fully from fixtures with no backend.

---

## 6. Scenario and story (Anshuman) — `scenarios/`, `docs/`

- `scenarios/allston_flood_v1/scenario.json` (schema in `contracts/scenario.schema.json`, provided by engine): district polygon inside the town box; flood keyframes (3–5) traced from public flood layers over a 3-hour timeline; facilities: hospital (`backup_endurance_s`), pumping station (`storage_max_m3`, `inflow_m3ph`, `pump_m3ph`, `connector`, `kw_required`), substation (goes down at t_x), outfall (dependency target), response base; resources: 3 vans (1 accessible), 1 truck, 1 crew, 2 generators (one compatible, one not), fuel; ~40 assisted households chosen from `town.json` (mix of sizes, 6 with mobility needs, 4 with unknown needs incl. the judge's); `assumptions.md` listing every assumed value and its justification; `sources.md` with real facts (NIST TN 2252 timestamps for the generic "orders → gridlock" story, Sandy sewage releases, MWRA CSO outfalls and per-storm volumes, Boston Climate Ready layers).
- Validation: `uv run ember validate-scenario scenarios/allston_flood_v1/scenario.json` must pass before commit.
- Demo script (`docs/DEMO.md`): six beats, who holds which phone, the sentence for each sponsor judge, fallbacks. Devpost write-up (≥ 900 words, ≥ 8 images, video < 3 min), README polish, ASUS content-challenge post, judge rehearsal checklist (`docs/QA.md`).

---

## 7. Contracts (`contracts/`)

Existing: `town`, `plan`, `job`, `metrics`, `trajectories` (+ fixtures via `ember fixtures`). To add (engine owns schemas; others consume): `scenario`, `state` (the shared-state snapshot the web renders), `assignment`, `report`, `comparison`, `ws-events`. Rule: a change bumps `version`, updates the fixture, gets one line in `DECISIONS.md`, and is announced in chat before merge.

---

## 8. Timeline and integration windows

Venue closes 8 PM. Lodging work is allowed and expected Saturday night.

| Window | Aryaman (engine) | Arnav (web) | Soham (backend) | Anshuman (scenario/story) | Gate |
|---|---|---|---|---|---|
| Fri night (lodging) | finish sim-env gates; `scenario.schema.json` + `validate-scenario`; facility/resource models skeleton | Vite app renders `town.fixture.json` + a flood polygon | FastAPI skeleton, DB, Photon assignment for 2 phones, first inbound event | scenario.json v0 with facilities/resources/households drafted from the rendered map | map renders with venue; fixtures load |
| Sat 09–12 | flood keyframes → deadlines; simulator executes a hand-written plan; wastewater model | facilities/resources/assignments layers from fixtures; ledger + inspector | `/state`, `/reports`, WS events; LLM extraction against 20 sample messages | scenario v1 validated; assumptions.md; sources.md | **I1 @ 12:00:** scenario → simulate(baseline) → metrics; web shows state via backend |
| Sat 12–17 | allocator (candidates + constraints + objective); baseline; replan; rationale | conversation panel, plan-version timeline, "close road" control | replan loop end-to-end; outbound messages with plan_version; operator thread | DEMO.md v1; content video; Devpost skeleton; SpaceXAI workshop 13:30 w/ Soham (voice go/no-go) | **I2 @ 17:00:** judge reply → replan → both a rescue and a generator assignment change on the map |
| Sat 17–20 | perturbations + Daytona pool (workshop 14:30) + robust selection | comparison panel + scatter | robustness: stale-version replies, duplicate reports, rejects | rehearse as judge; QA.md; fix copy in messages | **I3 @ 20:00:** comparison runs; scatter fills |
| Sat 20–24 (lodging) | perf, edge cases, `compare --seeds 5` | polish, empty states, screenshots | voice if green-lit, else cut; message copy | Devpost text, video edit, README | full run-through ×3 |
| Sun 00–06 | sleep in shifts; one person awake | | | | |
| Sun 06–07:30 | final merge to main, smoke, submit by 07:30 | | | | Devpost due 08:00 |

---

## 9. Team split and cut lines

| Person | Owns | Critical deliverable | Cut line if behind |
|---|---|---|---|
| Aryaman | `engine/` | simulator + allocator + replan + comparison | drop Daytona fan-out (local pool), drop crew tasks, K=10 candidates |
| Arnav | `web/` | live map with assignments + comparison panel | drop scatter animation (static), drop ambient trips |
| Soham | `residents/` | report → replan → changed messages, two threads | drop operator thread (scripted operator via UI), drop voice |
| Anshuman | `scenarios/`, `docs/DEMO.md`, `docs/QA.md`, Devpost, video, content post | validated scenario + demo script + submission | fewer households (20), 3 keyframes |

Nobody edits another's directory. Shared files: `contracts/` (announce + PR), `docs/DECISIONS.md` (append one line, rebase first), `docs/log/<own>.md` (own file only).

---

## 10. Git and logging protocol (everyone, every agent)

1. **One clone per person**, on your own machine: `git clone https://github.com/arnav-k-sinha/Ember.git && cd Ember`.
2. `git checkout main && git pull`, then `git checkout -b <name>/<topic>` (e.g. `arnav/map-layers`). Short-lived branches; new branch per feature.
3. Commit small and often: `git add <your-dir> docs/log/<name>.md && git commit -m "<dir>: what and why"`. Never `git add -A` from the repo root if you have stray files.
4. Before every push: `git fetch origin && git rebase origin/main`. Conflicts can only occur in shared files; resolve by keeping both lines (logs and decisions are append-only).
5. `git push -u origin <branch>` then open a PR to `main`. **Self-merge is allowed** when the PR touches only your directory (+ your log) and your check passes (`engine`: `uv run ember smoke` + `pytest`; `web`: `npm run build`; `residents`: `pytest`; `scenarios`: `ember validate-scenario`). Otherwise ask the owner of the other directory in chat.
6. `main` must always run. If you break main, fixing it is your next task.
7. **After every feature:** append an entry to `docs/log/<name>.md` (template in `docs/log/README.md`), commit it with the feature, push. **At every session start and before every integration window:** your agent reads `docs/log/*.md` (everyone's latest) and `docs/DECISIONS.md`.
8. Secrets in `.env` (gitignored); share keys in the team password note, never in chat logs committed to the repo.
9. Integration windows (12:00, 17:00, 20:00 Sat; 06:00 Sun): everyone merges to main, pulls main, runs the full demo path together.

---

## 11. Risks and fallbacks (ordered)

1. **Allocator too slow or too weak** → K smaller, simulator tick 120 s, greedy only; the demo still works if replan < 5 s.
2. **Photon beta flakiness** → polling `GET /messages` fallback; team phones pre-opted-in Friday; backup video of the reply moment.
3. **Daytona tier/limits** → local multiprocessing pool, same job list; say so on stage.
4. **Scenario looks invented** → every assumed value in `assumptions.md`; real sources on the slide; "simulation outcomes" wording everywhere.
5. **Venue Wi-Fi** → hotspot; backend on a laptop that never leaves the table.
6. **Scope creep** → anything not in §3–§6 needs a line in `DECISIONS.md` first.

---

## 12. References
`docs/EMBER-hackharvard-2026-plan.md` (verified Daytona/Photon/FIRMS/OSMnx/deck.gl facts, demo script, event rules) · `docs/SIM_ENV_PLAN.md` (world build) · `docs/PHYSICAL_REALITIES_NOTES.md` (what the MHacks winner did: decide at moments, move every tick; distance fields; paired-seed A/B; inspector with rationale) · `docs/DECISIONS.md` · `docs/HANDOFF.md`.
