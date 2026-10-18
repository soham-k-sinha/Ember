# Aryaman — engine log (`engine/`)

## 2026-10-16 21:40 · scaffold + engine package · branch aryaman/sim-env · commit 3c77811
What: repo scaffold, docs, decision log, engine package (world builder, hazards, queue-traffic engine, job runner, CLI).
Files: engine/ember_engine/*, docs/*, CLAUDE.md
Run: cd engine && uv sync --extra dev && uv run ember build && uv run ember smoke
Interfaces: produces town, plan, job, metrics, trajectories (schemas in contracts/)
Status: partial — a second session is running build/smoke/gate-a and fixing API mismatches (see DECISIONS D13–D16); data/town.json built (4.3 MB)
Next: scenario.schema.json + validate-scenario; models/ (facilities, wastewater, resources); simulator; allocator

## 2026-10-16 23:05 · sim-env end to end + contracts v0.1 · branch aryaman/sim-env · commit c1faf6a
What: build/smoke/render/gate-a all work on the real town around the Treehouse (venue pinned to its OSM footprint, 20 Western Ave). Fixed routing (parallel-edge summing, dijkstra unpack), hazard closure (line intersection), exit/household snapping, congestion re-routing + storage floor, trajectory endpoints; Overpass-resilient builder (layer cache, mirrors, asset fallback). 12 tests.
Files: engine/ember_engine/{build_town,world,hazards,cli}.py, engine/ember_engine/engines/queue_traffic.py, engine/tests/*, contracts/*.schema.json, contracts/fixtures/*, contracts/README.md
Run: cd engine && uv run ember build --no-walk && uv run ember smoke && uv run ember render && uv run ember gate-a && uv run pytest -q
Interfaces: produces town, plan, job, metrics, trajectories v0.1 (contracts/*.schema.json + fixtures; pytest validates fixtures). metrics gained `exit_closure_order` (D15). town.fixture = full road network + 1/12 households (D27).
Status: done. Gaps: paths (walk network) empty and assets from cache fallback until Overpass recovers (D26); exits not hand-curated yet.
Next: hand-curate exits; then docs/team/aryaman.md task 1 (scenario.schema.json + validate-scenario) and task 2 (state.schema.json + fixture).

## 2026-10-17 00:30 · scenario contract v0.1 + validate-scenario · branch aryaman/scenario-schema · commit (this PR)
What: `contracts/scenario.schema.json` (district, flood keyframes, facilities incl. wastewater/power/connector/depends_on/events, resources, assisted households with needs or "unknown" + one judge, reserve, scripted reports) and `ember validate-scenario` (schema + referential checks against town.json + one-line summary + `--deadlines`). Flood keyframes plug into the hazard interface as `flood_keyframes`. Example scenario fixture generated from real town ids.
Files: contracts/scenario.schema.json, contracts/fixtures/scenario.fixture.json, contracts/README.md, engine/ember_engine/scenario.py, engine/ember_engine/{cli,hazards}.py, engine/tests/test_scenario.py, engine/pyproject.toml
Run: uv run --project engine ember validate-scenario contracts/fixtures/scenario.fixture.json --deadlines
Interfaces: produces scenario v0.1 (D28). Anshuman: copy the fixture's shape; keyframes can live in keyframes.geojson (features with properties.t_s). Engine reads it via `hazard_from_scenario` and `scenario.deadlines()`.
Status: done. 30 tests pass.
Next: task 2, state.schema.json + state.fixture.json.

## 2026-10-17 00:50 · shared town file · branch aryaman/shared-town-state · commit (this PR)
What: the world is committed as engine/data/town.json.gz; every ember command unpacks it to data/town.json when missing (and warns if a local rebuild differs). `ember pin-town` updates it.
Files: engine/data/town.json.gz, engine/ember_engine/cli.py
Run: rm data/town.json; uv run --project engine ember validate-scenario contracts/fixtures/scenario.fixture.json
Interfaces: everyone's household/asset/edge ids now come from the same town (D29). Don't run `ember build` unless you mean to change the world.
Status: done.
Next: task 2, state.schema.json + fixture.

## 2026-10-17 01:40 · state contract v0.1 + validate-state · branch aryaman/state-schema · commit (this PR)
What: `contracts/state.schema.json` (+ `assignment.schema.json`, `report.schema.json`) and `ember validate-state <path> [--scenario]`. `contracts/fixtures/state.fixture.json` is a computed snapshot at 80 min of the example scenario: 122 closed edges, substation down → hospital on backup (8.9 h left), generator pre-positioned at Cottage Farm, 3 vans at pickups with follow-up trips, 11 households cut off by water, judge's needs unknown with a question queued. Also `World.route()` (point-to-point routing under closures) and the first facility/wastewater logic (tests: unpowered station overflows at ~154 min; a generator prevents it).
Files: contracts/{state,assignment,report}.schema.json, contracts/fixtures/state.fixture.json, contracts/README.md, engine/ember_engine/{state,world,scenario,cli}.py, engine/tests/test_state.py
Run: uv run --project engine ember validate-state contracts/fixtures/state.fixture.json --scenario contracts/fixtures/scenario.fixture.json
Interfaces: produces state v0.1, assignment v0.1, report v0.1 (D30). Arnav: render the state fixture (households by status, facilities by state, resources, assignment routes, flood polygon, closures over town edges). Soham: GET /state returns this shape; POST /reports takes a report; run validate-state on your output.
Status: done. 41 tests pass.
Next: task 3/4: move facility + wastewater logic into models/, resource movement, then the plan simulator.

## 2026-10-17 03:00 · models + plan simulator · branch aryaman/models-sim · commit (this PR)
What: `models/` (facility state machine with dependencies/backup/generators, wastewater storage+overflow, resource movement with re-route/turn-back/stall/fuel) and `sim/` (plan simulator: executes assignments per resource, applies flood closures + dated reports + perturbations, returns §3.4 metrics, per-assignment outcomes, events, a per-tick replay, and `state_at(t)` snapshots). `example_plan` (dependency-first protect + deadline-ordered greedy) is the stand-in planner. `ember simulate`. State fixture is now simulator output.
Files: engine/ember_engine/models/*, engine/ember_engine/sim/*, engine/ember_engine/{state,world,cli}.py, engine/tests/test_models_sim.py, contracts/fixtures/state.fixture.json, contracts/README.md
Run: uv run --project engine ember simulate --scenario contracts/fixtures/scenario.fixture.json --state-at 4800
Interfaces: state fixture values changed (schema unchanged, v0.1; D32). Soham: `from ember_engine.sim import simulate, example_plan`; `simulate(world, scenario, plan, reports=[report.schema objects]).state_at(t)` gives GET /state for any clock. Reports in report.schema shape are applied at observed_at_t_s.
Status: done. 55 tests pass; example scenario simulates in 0.09 s. On allston_flood_v1 (PR #4): 67 people reached before deadline, 20 unreached, generator connected at 23 min, 0 m³ overflow.
Next: task 6 baseline, task 7 allocator, task 8 compare.

## 2026-10-17 09:10 · fix keyframes_file validation · branch aryaman/fix-keyframes-file · commit (this PR)
What: `load_scenario` now removes `keyframes_file` after inlining it, so scenarios that keep keyframes in keyframes.geojson validate (bug reported by Anshuman). Regression test added.
Files: engine/ember_engine/scenario.py, engine/tests/test_scenario.py
Run: uv run --project engine pytest -q engine/tests/test_scenario.py
Interfaces: none changed. Anshuman: `"keyframes_file": "keyframes.geojson"` works now.
Status: done.
Next: baseline, allocator, compare.

## 2026-10-17 11:30 · baseline + allocator + compare · branch aryaman/allocator · commit (this PR)
What: `baseline.py` (incident-by-incident), `allocator/` (candidate plans + local search scored by the simulator; replan with carry-over, cancellation, generator re-targeting; computed rationale, unmet needs, info requests, diff), `allocator/rolling.py` (plan at t=0 + replan at every report), `compare.py` (paired perturbation seeds). CLI: `ember allocate`, `ember replan`, `ember compare`, `ember simulate --plan ember|baseline|example`. Simulator: `not_before_t_s`, `cancelled_at_t_s`, `record=False`, cached routing + flood masks (10 ms/sim).
Files: engine/ember_engine/{baseline,compare,cli}.py, engine/ember_engine/allocator/*, engine/ember_engine/sim/{plan_sim,snapshot}.py, engine/ember_engine/world.py, engine/tests/test_allocator.py, contracts/{state,assignment,comparison}.schema.json, contracts/fixtures/{state,comparison}.fixture.json
Run: uv run --project engine ember allocate --scenario scenarios/allston_flood_v1/scenario.json && uv run --project engine ember compare --scenario scenarios/allston_flood_v1/scenario.json --seeds 5
Interfaces: state v0.2 (D35: plan.reserved, plan.search, assignment.not_before_t_s / cancelled_at_t_s; all optional). New comparison v0.1 + fixture. Soham: `from ember_engine.allocator import allocate` → `allocate(world, scn, reports=all_reports, t_now=now, prev=current_plan, prev_reports=reports_before)`; ~0.5 s. Arnav: render `contracts/fixtures/comparison.fixture.json` (rows + headline) and `plan.changes` for the version timeline.
Status: done. 65 tests. allston_flood_v1: EMBER 87 people before deadline / 0 unreached vs baseline 31 / 56; 5 seeds: +55 people, −21 min critical-service outage, overflow 0 for both, +81 vehicle-km (EMBER drives more).
Notes for Anshuman (scenario tuning, not engine bugs):
  - Judge loop: the judge's need (accessible) at 60–90 min can't be served — one accessible van, 7 mobility households all due by 165 min; the allocator says so ("every eligible vehicle is committed to earlier deadlines"). For the demo beat, give the judge an earlier deadline than other mobility households, or a reserve accessible vehicle the report can release. The generator only reacts to the judge if they share a road or a vehicle; today they don't.
  - Overflow: the baseline also ends at 0 m³ because storage doesn't fill before 180 min even with a reactive generator. Smaller storage_max_m3 or higher inflow makes the dependency-first story show up in the comparison.
  - Infrastructure beat that already works (test): an operator report "10 min of backup left" at 50 min moves the generator from the pumping station to the hospital; hospital outage 15 min → 0, overflow 0 → 2,000 m³, stated in the rationale.
Next: task 9 Daytona fan-out.

## 2026-10-17 12:10 · ws-events contract moved to contracts/ + scatter_point proposal · branch aryaman/ws-events · commit (this PR)
What: Soham's `residents/ws-events.schema.json` copied to `contracts/ws-events.schema.json` (envelope + event shapes unchanged); `scatter_point` filled in from the engine side; one example envelope per type in `contracts/fixtures/ws-events.fixture.json`; `compare.scatter_points()` emits the shape; test validates every example.
Files: contracts/ws-events.schema.json, contracts/fixtures/ws-events.fixture.json, contracts/README.md, engine/ember_engine/{compare,cli}.py, engine/tests/test_contracts.py
Run: uv run --project engine pytest -q engine/tests/test_contracts.py
Interfaces: ws-events v (D38, proposed). Soham: please review scatter_point; after this merges, drop residents/ws-events.schema.json in your PR and renumber your D33/D34 to D36/D37 (main already has D33–D35). Arnav: build the WS client against contracts/ws-events.schema.json + the example fixture.
Status: PR open, waiting on Soham's OK on scatter_point.
Next: task 9 Daytona fan-out (emits these scatter points).

## 2026-10-17 13:00 · robustness fan-out (Daytona + local pool) · branch aryaman/daytona · commit (this PR, stacked on #11)
What: `daytona/` — jobs (candidate × perturbed world → scatter_point; full §3.7 perturbation sampler), pools (`DaytonaPool`: long-lived sandboxes from a content-hashed snapshot, stateful code_interpreter, results via return value, timeouts, retry, local fallback; `LocalPool`: processes), robust selection (best worst-20%). `ember robust`, `ember daytona-snapshot`. Allocator split into `search()` + `finalize()` so robustness can publish a non-nominal winner.
Files: engine/ember_engine/daytona/*, engine/ember_engine/allocator/search.py, engine/ember_engine/cli.py, engine/tests/test_daytona.py, engine/.env.example
Run: uv run --project engine ember robust --scenario scenarios/allston_flood_v1/scenario.json --points-out data/points.jsonl
Interfaces: emits ws-events `scatter_point` (PR #11 shape) via `robust_plan(..., on_point=...)`; Soham: call it from POST /optimize and broadcast each point; plan.search.robust carries the ranking table. Daytona needs DAYTONA_API_KEY in engine/.env (nobody has added one yet).
Status: done locally (100 runs, 1.5 s, chooses c03 over nominal c00); Daytona path wire-tested with stand-in sandboxes, not yet run against real Daytona (no key on this machine).
Next: get a Daytona key + Tier 2, run `ember daytona-snapshot` and a live 100-job batch; scenario tuning with Anshuman.

## 2026-10-17 14:10 · Daytona live (Tier 1) + backend bridge + Allston seed · branch aryaman/daytona · commit (PR #12)
What: Daytona verified live: snapshot `ember-engine-1b735d7199` built (77 s), `ember robust --pool daytona` ran 100 runs on 8 Tier-1 sandboxes in 29 s, identical to the local pool, 0 fallbacks, sandboxes deleted after. `ember_engine.api.EngineSession` = the backend's calls (start, add_report(s), close_road, state_at, compare, optimize, resume, edges_at_household / edges_by_name). `ember seed-state` → `engine/data/allston_flood_v1.seed_state.json` (plan v1 at t=0; 37 assignments; validates; round-trips through residents' Store).
Files: engine/ember_engine/{api,cli}.py, engine/ember_engine/daytona/pool.py, engine/data/allston_flood_v1.seed_state.json, engine/tests/test_api.py
Run: uv run --project engine ember seed-state ; uv run --project engine ember robust --scenario scenarios/allston_flood_v1/scenario.json --pool daytona
Interfaces: D42. Soham: `SEED_STATE=../engine/data/allston_flood_v1.seed_state.json`; `from ember_engine.api import EngineSession` (add `ember-engine = { path = "../engine", editable = true }` to residents' deps); call methods in a threadpool; `out["assignment_events"]` are ready-to-send WS `assignment` payloads. Daytona key lives only in engine/.env (gitignored) on Aryaman's laptop; Tier 2 tomorrow → set EMBER_DAYTONA_WORKERS≈90.
Status: done. 79 tests.
Next: judge-beat tuning with Anshuman; help Soham wire the endpoints.

## 2026-10-17 15:20 · demo beats: scenario tuning + regression tests · branch aryaman/scenario-tuning · commit (this PR)
What: at Aryaman's request, tuned Anshuman's allston_flood_v1 (synthetic values only, each recorded in assumptions.md): generators + truck stage at EMS Station 14, towed speed 0.25×, Cottage Farm hookup 30 min. Both beats now land: nominal overflow baseline 2,317 m³ vs EMBER 0; judge reply at minute 5 → Accessible Van 3 (pickup 132 vs deadline 165 min) + gen-1 rerouted (ETA 14 → 25 min, rationale says why). Kept assignments whose ETA moves now say so in their rationale. Regenerated engine/data/allston_flood_v1.seed_state.json. New tests pin both beats on the real scenario.
Files: scenarios/allston_flood_v1/{scenario.json,assumptions.md}, engine/ember_engine/allocator/explain.py, engine/tests/test_demo_beats.py, engine/data/allston_flood_v1.seed_state.json
Run: uv run --project engine pytest -q engine/tests/test_demo_beats.py ; uv run --project engine ember compare --scenario scenarios/allston_flood_v1/scenario.json --seeds 5
Interfaces: scenario values changed (no contract change, D47). Anshuman: your scenario was edited; please review the 6 changed values + assumptions rows, and put "judge replies within the first ~8 sim-minutes" in DEMO.md. Soham: reseed (`POST /dev/reset`) to pick up the new seed; 92 residents tests pass on it. "River St" near the judge → `EngineSession.edges_by_name("River Street", near_household=10296, radius_m=150)` = [523, 833, 952].
Status: done. 81 engine tests. 5-seed compare: +50.6 people before deadline, −44 min critical-service outage, −2,165 m³ overflow, +75 vehicle-km.
Next: perf/edge cases; help with the 5 PM integration.

## 2026-10-17 15:50 · Daytona: no implicit snapshot builds · branch aryaman/scenario-tuning · commit (same PR)
What: a missing snapshot now means "run locally and say so", not "build for minutes"; snapshot name hashes exactly the modules sandbox jobs import (16 files + town). Rebuilt the snapshot for the current code. Tests for both.
Files: engine/ember_engine/daytona/{pool,robust}.py, engine/ember_engine/cli.py, engine/tests/test_daytona.py
Run: uv run --project engine ember daytona-snapshot   # after any change to sim/models/allocator search/world/scenario
Interfaces: D48. Soham: set `EMBER_LOCAL_POOL=1` in residents' tests (conftest) — otherwise `test_optimize_streams_points_then_plan` starts 8 real Daytona sandboxes on every run (or, before this fix, built a snapshot and hung). 101 residents tests pass with it.
Status: done.

## 2026-10-17 16:10 · taking over the web and scenario/demo lanes · branch aryaman/take-over-lanes · commit (this PR)
What: added `web/`, `scenarios/`, `docs/DEMO.md`, `docs/QA.md`, `docs/devpost/` to Aryaman's lane in `.github/OWNERS.json` (and Cursor Agent's email to his authors so Arnav's commits can be brought in); CLAUDE.md ownership updated. Arnav's and Anshuman's lanes stay active.
Files: .github/OWNERS.json, CLAUDE.md, docs/DECISIONS.md, docs/HANDOFF.md, docs/log/aryaman.md
Run: AUTHOR=aryamangoenka BASE=origin/main HEAD=HEAD HEAD_REF=aryaman/x python3 .github/ownership.py
Interfaces: none (process only, D49). Arnav/Anshuman: you can still push to your lanes; tell Aryaman before you do so we don't collide.
Status: done.
Next: bring Arnav's website (arnav/operator-ui) to main and fix it against the contracts; DEMO.md, QA.md, Devpost.

## 2026-10-17 16:40 · 2.5D view decision + web visual style brief · branch aryaman/view-2-5d · commit (this PR)
What: D50 amends D8/hard rule 7 to "2D simulation, 2.5D view" (tilted camera, extruded buildings, lighting, dark basemap, clock tint; still no Three.js, no z in engine/contracts). Added § Visual style + task 10 to the web brief, mapping each Physical Realities visual to a deck.gl/MapLibre option. Fixed the clone URL (arnav-k-sinha → soham-k-sinha).
Files: docs/DECISIONS.md, CLAUDE.md, docs/TECHNICAL.md, docs/HANDOFF.md, docs/team/arnav.md, docs/log/aryaman.md
Run: n/a (docs only)
Interfaces: none changed (D50).
Status: done.
Next: whoever has web/ (Aryaman per D49, or Arnav) does the style pass after tasks 1–8; first check whether CARTO tiles carry building heights.

## 2026-10-17 16:30 · HANDOFF rewritten for a fresh session · branch aryaman/handoff-sat · commit (this PR)
What: docs/HANDOFF.md now reflects Saturday afternoon: what's on main per part, lanes (D49), how to run backend + web + the judge beat by hand, the four demo beats with numbers and the judge-timing rule, Daytona state (key local, snapshot, Tier 2 tomorrow), ordered open issues, gotchas, and an opening prompt. Merged Arnav's #21 (squash) after a live end-to-end test.
Files: docs/HANDOFF.md, docs/log/aryaman.md
Status: done.
Next: HANDOFF "Open issues / next steps" 1–5 (state broadcast check, EngineSession moves=, DEMO.md, QA.md, Devpost).

## 2026-10-17 01:40 · web: refetch state after every plan · branch aryaman/web-refetch-state · commit (this PR)
What: HANDOFF issue 1. The backend's `_publish()` still broadcasts `plan`/`assignment`/`metrics` but no `state` after a replan, so closed roads and ETAs stayed stale until reload. The web client now refetches `GET /state` 300 ms after each `plan` event (cancelled if a `state` event lands first), so it works with or without Soham's one-line fix.
Files: web/src/App.tsx, docs/log/aryaman.md
Run: backend + web per HANDOFF, press Live, run the three judge-beat curls → "Roads closed" goes to 4 (edges 523, 833, 951, 952) on plan v3 without reload (verified).
Interfaces: none. Soham: the `state` broadcast at the end of `planner._publish()` is still worth adding (one fewer round trip); the web handles both.
Status: done.
Next: EngineSession(..., moves=).

## 2026-10-17 01:55 · EngineSession(..., moves=) · branch aryaman/session-moves · commit (this PR)
What: HANDOFF issue 2 (Soham's request: his tests went 18 s → 56 s). `EngineSession(scenario, world=, seed=, moves=None)` passes `moves` to every `allocate()` (start, add_report(s), close_road) and to `robust_plan()` → `search()` for `optimize()`. None = allocator default (112 moves scored on the fixture); `moves=5` → 5.
Files: engine/ember_engine/api.py, engine/ember_engine/daytona/robust.py, engine/tests/test_api.py, docs/log/aryaman.md
Run: uv run --project engine pytest -q engine/tests/test_api.py
Interfaces: new optional kwarg only. Soham: `EngineSession(path, world=..., seed=..., moves=int(os.getenv("EMBER_MOVES")) if ... else None)` in engine_bridge.py, e.g. moves=10 in your conftest. Neither file is in the Daytona snapshot hash (still ember-engine-489b50f1ea), so no snapshot rebuild.
Status: done. 84 engine tests; smoke OK.
Next: docs/DEMO.md.

## 2026-10-17 02:25 · facility on reported backup now runs out · branch aryaman/facility-backup-countdown · commit (this PR)
What: found while re-checking the infrastructure beat on allston. A `facility_status` with `state: "backup"` (the extraction sets it for "we're on backup") left the facility on backup forever while the grid was up; it only went down when its substation did. `FacilityModel._resolve` now counts endurance down for a reported backup too. Operator at 15 min "on backup, 10 min left": rationale now "grid power lost at 15 min, down at 25 min … connected 42 min" (was "down at 120 min").
Files: engine/ember_engine/models/facilities.py, engine/tests/test_models_sim.py, docs/log/aryaman.md
Run: uv run --project engine pytest -q engine/tests/test_models_sim.py
Interfaces: none. Daytona snapshot rebuilt → `ember-engine-34d49a132c` (facilities.py is in the hash); live check: `ember robust --pool daytona` 100 runs on 8 sandboxes, 10.4 s fan-out, chose c03 over c00. Seed state unchanged.
Status: done. 85 engine tests; smoke OK.
Next: docs/DEMO.md (infra beat timing: operator must text before ~minute 30; see DEMO.md).

## 2026-10-17 02:50 · docs/DEMO.md + operator-beat test · branch aryaman/demo-md · commit (this PR)
What: HANDOFF issue 3. DEMO.md: who holds which phone, the judge-timing rule (clock paused at 5:00 until the judge's plan lands; operator at 15:00, never after 25:00), pre-stage checklist (one machine needs both engine/.env and residents/.env), six beats with timings and live-measured numbers, sponsor lines, fallbacks, a curl replay of every beat, "if asked" answers. Measured order matters: the comparison beat goes before the operator beat (after the judge: overflow EMBER 0 vs baseline 5,244 m³, 5 seeds; after the operator both overflow 8,769 m³ and EMBER's win is hospital outage 19 vs 28 min). Infrastructure beat re-checked on allston: works at 15–25 min (gen-1 → Mount Auburn, outage 16 min, overflow 0 → 9,600 m³ shown); from 30 min the plan keeps gen-1 at Cottage Farm (people outrank the hospital; the truck also carries people) and lists the hospital as unresolved. /optimize after the operator beat chooses c03 over c00 (worst-20% unreached 31 vs 42; forecast 14 vs 9). New test pins the operator beat.
Files: docs/DEMO.md, engine/tests/test_demo_beats.py, docs/log/aryaman.md
Run: uv run --project engine pytest -q engine/tests/test_demo_beats.py ; DEMO.md § Replay against a running backend
Interfaces: none. Soham: please confirm (a) the operator text extracts to facility_status mt-auburn {state: backup, backup_endurance_s: 600}, (b) the resident phone gets q-10296 on startup without a /replan; both are on the QA list.
Status: done. 86 engine tests.
Next: docs/QA.md.

## 2026-10-17 03:05 · docs/QA.md · branch aryaman/qa-md · commit (this PR)
What: HANDOFF issue 4. Row-per-action checklist for the 8 PM run-through, following DEMO.md: setup (tests, keys by name, snapshot, health, phones opted in, Live, clock 5:00, judge's opening question), then every click/text in beats 1–6 with the measured expected value, owner, blocker/fallback and a ✓ column; reset between rehearsals. DEMO.md beat 3 now says "Run comparison" (the web already fetches GET /comparison live, ~3 s).
Files: docs/QA.md, docs/DEMO.md, docs/log/aryaman.md
Run: print docs/QA.md at 8 PM.
Interfaces: none.
Status: done. Gap found: the web has no Optimize button (beat 5 uses the curl until HANDOFF issue 6 adds it).
Next: Devpost draft (docs/devpost/).

## 2026-10-17 03:30 · web: layout fix, projected KPIs, Optimize button, readable scatter · branch aryaman/web-optimize-layout · commit (this PR)
What: HANDOFF issue 6. (1) The "big empty area": `.app` had five fixed grid rows, so without the banner the footer took the 1fr row; and `section.kpis` inherited `flex-direction: column` from the global `section` rule, so the KPIs stacked. Now 4 rows, KPIs in one row, the clock banner is an overlay on the map. (2) KPIs show the current plan's projection (reached by deadline, not reached, unresolved, overflow m³, hospital outage min, roads closed, vehicle-km) with "so far" sub-lines; before they showed state.metrics (outcome at the clock: 0/0 at t=0). (3) Scatter tab: Optimize button → POST /optimize, polls GET /optimize, refreshes state, notice says pool/workers/time and which candidate won over the nominal best. (4) Scatter colours by candidate (chosen from plan.search.robust.chosen, other candidates, baseline), axes + key, ranking table (worst-20%/mean/max unreached, overflow). Before, "chosen" was `candidate === "ember"`, which the engine never emits, so nothing was highlighted.
Files: web/src/{App.tsx,live.ts,types.ts,styles.css}, web/src/components/Panels.tsx, docs/log/aryaman.md
Run: backend + web, Live → Scatter → Optimize (verified: 100 runs local in 1.5 s, c03 over c00, chart + ranking render).
Interfaces: none (reads existing plan.search.robust).
Status: done. `npm run build` OK.
Next: D50 visual pass (tilted camera, dark basemap, extruded buildings).

## 2026-10-17 04:20 · allocator: generators re-targeted under every rescue rule + computed trade-off text · branch aryaman/generator-retarget-search · commit (this PR)
What: found while checking the infrastructure beat. From minute 30 the plan left Mount Auburn without power (190 min outage) although moving Generator 1 there changed no rescue — strictly better under the lexicographic objective. Cause: the "re-target committed generators" variant existed only for the two previous-order policies and critical_first, whose rescue schedules are worse, so it never won on people. Now every generator-protecting rule gets a re-target variant (≈+16 candidates, replan 0.55 → 0.7 s). Explanations: an unprotected at-risk facility's `blocked_by` now carries a counterfactual sim ("sending Generator 1 here instead (rest of the plan unchanged, simulated): hospital outage 13 → 215 min, overflow 9,600 → 0 m³" + the ranking rule); a newly chosen protect rationale says "chosen over X: …"; a generator re-planned onto the same facility says "re-routed" / "replaces …, ETA 14 → 25 min (route changed: road reported closed)" instead of "re-targeted to cottage-farm". Judge beat: gen-1 now ETA 14 → 25 (was 32). Compare numbers unchanged (+50.6 people, −2,165 m³, −44 min).
Files: engine/ember_engine/allocator/{search,explain}.py, engine/tests/test_demo_beats.py, docs/DEMO.md, docs/QA.md (corrected claims this makes false), docs/log/aryaman.md
Run: uv run --project engine pytest -q engine/tests/test_demo_beats.py
Interfaces: none (unresolved.blocked_by and rationale are free text). Daytona snapshot rebuilt → ember-engine-6a73b6188a; live robust: 100 runs, 8 sandboxes, 13.5 s.
Status: done. 87 engine tests (new one fails on the old search); smoke OK; seed state unchanged.
Next: more engine/product correctness (web lane is with the web-street-level session).

## 2026-10-17 05:30 · engine: declines are constraints, confirmations keep their place, nearest drop-off, honest reasons · branch aryaman/engine-declines-dropoffs · commit (this PR)
What: Soham's engine asks 1, 3, 4 (reason text), 5, 6 (D58). Declines: `rejected` → history + `cancelled_at_t_s`, banned pair in `ctx.eligible`/generator choice/local search; `cut_at()` in the simulator (cancel only counts while cancelled/rejected, so a YES that undoes a decline revives it); unresolved says "declined Accessible Van 3; no other wheelchair-accessible vehicle". Confirmed rescues pinned to their vehicle but placed in deadline order (was: put first). Drop-off: nearest shelter/response base by drive time (Treehouse for all 40 here), capacity spill-over, vehicle continues from the drop-off; baseline uses the same rule. Unthreatened households: reason "outside the forecast flood…" + "stay where you are" instead of "committed to earlier deadlines" (couldn't reproduce the served/not-served flip: served in solo and crowded on old and new code — Soham, send a household id + time if it recurs). Optimize at t=0 tags points with the returned version. Not done yet: shared trips (ask 2), next.
Files: engine/ember_engine/allocator/{context,search,explain}.py, engine/ember_engine/sim/{plan_sim,snapshot}.py, engine/ember_engine/{baseline,api}.py, engine/ember_engine/daytona/robust.py, engine/tests/{test_replan_rules,test_api}.py, engine/data/allston_flood_v1.seed_state.json, docs/DECISIONS.md, docs/log/aryaman.md
Run: uv run --project engine pytest -q engine/tests/test_replan_rules.py
Interfaces: no contract change (uses existing status + cancelled_at_t_s). Soham: nothing to change; your workaround (keep re-proposed pairs `rejected`) becomes a no-op. Reseed (`POST /dev/reset`) for the new v1 (drop-offs at the Treehouse). `tests/test_listener.py::test_poll_once_hands_texts_over_and_advances` fails on main too (wall-clock dependent), not from this. Daytona snapshot → ember-engine-ce3bb66393 (live: 100 runs, 8 sandboxes, 11.6 s).
Status: done. 93 engine tests (decline + confirm-order tests fail on the old engine); smoke OK; residents 128/129 (the unrelated listener test).
Next: shared trips (several households per van trip).

## 2026-10-17 06:10 · engine: shared trips (several households per van trip) · branch aryaman/shared-trips · commit (this PR)
What: Soham's ask 2 (D59). Simulator: after a pickup the vehicle collects the next household on its queue first if ≤ 3 min by road, seats + accessibility fit and the drop-off is the same; one drop-off unloads everyone; failed/stalled chained pickups release the people aboard to the drop-off. Outcome gets `shared_after`; rationale says "shares the trip with household #…". Sim still ≈6 ms.
Files: engine/ember_engine/sim/plan_sim.py, engine/ember_engine/allocator/explain.py, engine/tests/test_replan_rules.py, engine/data/allston_flood_v1.seed_state.json, docs/DECISIONS.md, docs/log/aryaman.md
Run: uv run --project engine pytest -q engine/tests/test_replan_rules.py
Interfaces: none (no contract change). Soham: a shared pickup is an ordinary assignment; its rationale names the household it shares with. Reseed for the new v1. Daytona snapshot → ember-engine-9634de9e37 (live: 100 runs, 8 sandboxes, 9.1 s).
Status: done. 14 shared pickups in v1, vehicle-km 76 → 51. 5-seed compare: EMBER 86.2 vs baseline 56.4 (+29.8), −2,165 m³, −44 min, +19 vehicle-km. DEMO.md numbers need re-measuring (all four beats).
Next: planner-side pooling estimate in construct (today only the simulator and local search know about it).

## 2026-10-17 07:20 · end-to-end integration test + Daytona in the backend · branch aryaman/e2e-integration · commit (this PR)
What: merged Soham's #42 (closed #38/#39 as superseded) after his 198 + my 95 tests passed on it. New `engine/scripts/e2e.py`: drives a live backend over HTTP + WS through the whole story (reset → v1, judge need + River St, confirm/decline, hospital backup at 15 min, comparison, simulate, optimize, texting endpoints, clock to 240 min), validating every state against the contracts: 62/62 pass. Found and fixed an integration bug: the backend's venv never had the Daytona SDK (an optional engine extra residents didn't request), so every `/optimize` from the backend silently ran locally. `daytona` is now a core engine dependency; a fallback now records `search.robust.fallback_reason`. After the fix the backend's /optimize runs on Daytona (8 sandboxes, 12.2 s). Website on main checked against the live backend: Live mode KPIs match, judge beat updates the map without reload (v3, 4 roads closed), Optimize button → "100 runs on daytona", scatter 100/100, Run comparison live.
Files: engine/scripts/e2e.py, engine/pyproject.toml, engine/uv.lock, engine/ember_engine/daytona/robust.py, docs/log/aryaman.md
Run: cd residents && RESET_ON_START=1 PHOTON_ENABLED=0 uv run uvicorn residents.app:app --port 8000 ; cd residents && uv run python ../engine/scripts/e2e.py
Interfaces: none. Soham: run `uv sync` (or any `uv run`) in residents/ after pulling; it re-locks to pick up the engine's new `daytona` dependency; please commit that residents/uv.lock refresh. Not covered here (no keys on this laptop): real Photon delivery and the LLM extraction; run the same script on the machine with residents/.env.
Status: done.
Next: re-run e2e.py on the merged web-street-level branch; real-phone run on the keyed machine; re-measure DEMO.md.

## 2026-10-17 07:50 · DEMO/QA numbers re-measured + HANDOFF rewritten · branch aryaman/demo-numbers · commit (this PR)
What: re-measured every demo beat on main against the live backend (Daytona on): v1 78/9/0 m³/51 km; judge → Van 3 pickup 130 vs 165, gen ETA 14 → 25; comparison after the judge 89 vs 52.6 (+36.4), 0 vs 5,244 m³, +27 km; hospital beat outage 13 min, overflow 0 → 9,600 m³; optimize c02 over c00 (worst-20% 16.8 vs 29), 8 sandboxes ~10 s. Updated DEMO.md, QA.md (QA 0.1 now runs e2e.py), snapshot name. HANDOFF.md rewritten for the evening state and open items.
Files: docs/DEMO.md, docs/QA.md, docs/HANDOFF.md, docs/log/aryaman.md
Status: done.
Next: merge the 2.5D website when its session pushes it; real-phone run on the keyed machine.

## 2026-10-17 08:30 · positioning + plan changes in the docs (D63–D69) · branch aryaman/positioning-docs · commit (this PR)
What: docs only, from Aryaman's planning chat. D63 positioning ("Flood response is our first demonstration. Adaptive coordination is the product."; no claim beyond the flood), D64 two incident types / one engine, D65 sustainability anchored to the real 2024 Cottage Farm event (21.33 MG ≈ 80,700 m³ in 13 h; drill: baseline 2,317 vs EMBER 0 m³, re-checked on main), people first, D66 multiplayer (stretch; Photon phone limit first), D67 Chalk gateway + simulator-graded eval (stretch), D68 skip SpaceXAI, D69 sim-realism order and the "nothing in the inner loop" rule. HANDOFF: new one-breath line, the LANDFALL competition note, priorities, open questions (Photon phone limit, Chalk account). DEMO.md: framing section; beats 2 and 4 labelled as the two incident types (beat 3 is the comparison); optional multiplayer beat 2b with the one-judge fallback; sustainability line anchored to real data. docs/team/soham.md: tasks 10–12 with acceptance and the direct paths as fallback. New docs/devpost/README.md outline. Numbered D63–D69 because open PR #45 (Soham, voice) holds D61–D62.
Files: docs/DECISIONS.md, docs/HANDOFF.md, docs/DEMO.md, docs/team/soham.md, docs/devpost/README.md, docs/log/aryaman.md
Interfaces: none.
Status: done.
## 2026-10-17 17:30 · web: the stage at Physical Realities quality (people motion, sharp ground, daylight, water) · branch aryaman/web-street-level · commits ee6961c..c33ceb6
What: (1) People rebuilt the way Physical Realities does it, reimplemented from reading their renderer: pooled sprite per person with a stable identity, stride phase from displayed distance (capped per second), facing from screen-horizontal motion with hysteresis, standing people face the van/street, critically damped spring for small jumps, state shape under each figure (diamond needs help, dashed unknown, ring assigned, square safe, triangle turned back), 9.5 px minimum, click a person → their household, pulsing ring + head marker. (2) Occlusion-aware depth against real footprints (no more "always on top"); hidden key people drawn see-through. (3) Households wait on the pavement of their street side (spread along the façade), walk to the parked van one by one and board at the engine's pickup time (from the status timeline; events are end-of-tick), get out at the shelter; Treehouse plaza crowd = drop-offs + neighbours who walked (illustrative, mills, some sit). (4) Ground tiles at 8 px/m (+4 px/m shadows) baked on demand when zoomed in, LRU 28. (5) Clock 2–6 pm: daylight with light sky and haze into dusk. (6) Flood water: per-keyframe 10-min fade-in, deeper where flooded longer, ripples, foam edge (visual only). (7) District preset fits the stage. Merged main; playback fixtures regenerated (drop-offs now at the Treehouse: 87).
Files: web/src/iso/{crowd,agents,tiles,water}.ts (new), web/src/iso/{IsoView.tsx,scene,ground,atlas,lighting,project}.ts, web/src/App.tsx (dev clock hook), contracts/fixtures/playback*.json, docs/DECISIONS.md (D70, D71), CLAUDE.md rule 7
Run: npm --prefix web run build; open the stage, Judge's corner, play at 10×
Interfaces: playback v0.1 unchanged. Frame ≈1 ms logic zoomed in; first sharp tile ≈0.4 s (textures), then ≈30 ms each, one per frame.
Status: done, not pushed. Engine 100/100 (allocator `replan_latency_s < 2.0` is wall-clock and flaked once under load).
Next: background traffic (precompute OK at ~0.5 s; needs a departure-rule decision), flood from ground height (MassGIS LiDAR), vehicle sprites, why-cards, landmarks.

## 2026-10-17 19:10 · web: the Boston side of the stage made real (wider stage, Stadium, car parks, construction site, trees) · branch aryaman/web-street-level
What: The stage's west half looked empty: partly real (Harvard's Allston land is lawns, car parks and the ERC construction site), partly data (Boston's tree inventory covers parks only, 25 trees here; campus trees are private) and partly rendering (university land was painted as paving). (1) Stage extended 300 m west (`ember diorama --name stage --half-w 710 --half-h 610 --dx 125 --dy 180`): Harvard Stadium (named by location; Boston LiDAR footprint), the full Science & Engineering Complex. (2) OSM via Overpass (mirrors + retry): mapped trees and surface car parks; parking aisles kept from Overture. (3) Trees *placed* (flag 3) on lawns no inventory covers, along lawn edges only (fields stay open), never on car parks, construction or inside big-building hulls; attribution says so. (4) Ground: campus = lawn, construction = graded earth, car parks = asphalt with bay lines. (5) Props: parked cars in bays (≈70 % full, illustrative), construction fence, cabins, piles and tower cranes (illustrative dressing of a real site). (6) Raw cache now keyed by rectangle. (7) People: depth cached until ~0.8 m of movement; passers-by thinned when zoomed out. District frame ≈1 ms logic, ≈10 ms render.
Files: engine/ember_engine/{diorama,cli}.py, web/public/diorama/stage.json, web/src/iso/{props.ts (new),scene,ground,palette,agents,crowd,data}.ts, web/src/iso/IsoView.tsx
Status: done, not pushed. Engine tests pass.

## 2026-10-17 13:15 · web: more close-up passers-by within a frame budget · branch aryaman/web-street-level
What: Raised the close-up decorative crowd cap 700 → 1,400, preserving the overview target. Cached route choices/phases, filtered passers-by to the viewport before flood tests/agent allocation, and culled all figures before sprite allocation/animation/depth work. Stable ids/pooling and explicit household picking retained. Frame budget grows only with spare time, drops under sustained stalls, recovers afterward, ignores one-off background gaps.
Files: web/src/iso/{density,agents,crowd}.ts, web/src/iso/IsoView.tsx, web/scripts/check-crowd.ts, web/package.json, docs/DECISIONS.md
Run: cd web && npm run check:crowd && npm run build
Interfaces: no contract/engine changes; decorative crowd only (D72).
Status: done locally. Budget/viewport checks and production build pass. CPU-only close-up benchmark: ~28 → ~58 visible passers-by while generation 0.472 → 0.399 ms at t=0, 1.562 → 0.371 ms at 90 min. Real Pixi container check: 1,400 offscreen + one visible creates one figure container (old path created 1,401). No full GPU FPS claim: existing blank-stage behavior persists in the in-app browser, with no new JS errors. Benchmark evidence: /private/tmp/ember-sim-review/crowd-performance.json.
Next: verify GPU frame times in the working native preview under playback and pan/zoom; the adaptive budget protects load but cannot guarantee zero performance impact on every device.

## 2026-10-17 21:40 · engine + web: background traffic as a staged evacuation (D73) · branch aryaman/web-street-level · commit ecc450c
What: `engine/ember_engine/traffic_bg.py`: staged order keyed to flood keyframes (600 m zones, 15 min lead, 85 % compliance, 30 % shadow, mobilisation median 8 min), one queue_traffic run per scenario (≈0.35 s), cached on the world. Mover drives and routes on the per-bin multiplier (World.route gained a cached `weight_key`), plan_sim sets `mv.t_now`, shared-trip detours use congested times, allocator Context estimates at t_now. Playback 0.2 `traffic` (3,000 cars, only in EMBER's replay; the web reuses it for baseline). Stage: TrafficCars, 16 headings × 8 colours pre-rendered, 0.3 ms per frame for ~200 cars. Scenario 0.2 + schema; seed state regenerated.
Files: engine/ember_engine/{traffic_bg (new),playback,cli,world}.py, engine/ember_engine/{sim/plan_sim,models/resources,allocator/context}.py, contracts/{scenario,playback}.schema.json, contracts/fixtures/{scenario,playback,playback.baseline}.fixture.json, scenarios/allston_flood_v1/scenario.json, engine/data/allston_flood_v1.seed_state.json, web/src/{playback.ts,iso/traffic.ts,iso/props.ts,components/MapView.tsx}; web/src/iso/IsoView.tsx (uncommitted: shares the file with the crowd-density session's D72 edits)
Run: uv run --project engine pytest -q; npm --prefix web run build
Interfaces: scenario 0.2 adds optional `background_traffic`; playback 0.2 adds optional `traffic`. Soham: reseed (`POST /dev/reset`) for the new v1; a Daytona snapshot rebuild is needed for robust runs to include traffic. Residents 128/129 (the known wall-clock listener test).
Status: done. Engine 100/100. Plan v1 reaches 78 with and without traffic; DEMO.md numbers should be re-measured anyway (routes changed).

## 2026-10-17 09:40 · verified + merged the PixiJS website (#47); demo numbers re-measured · branch aryaman/demo-numbers-2 · commit (this PR)
What: verified the web chat's #47 independently before merging (Aryaman OK'd the hard-rule-7 amendment, D71): CI pass, engine 100/100, smoke OK, e2e.py 62/62 with /optimize on Daytona (8 sandboxes, 11 s), judge replan 0.67 s, browser: Fixtures + Live, judge beat updates the stage without reload, Optimize "100 runs on daytona", ranking. Merged. Re-measured on merged main (background traffic D73 shifts ETAs): v1 78/9/0 m³/46 km, 18 shared pickups; judge pickup 122 vs 165 min; comparison after the judge 89 vs 51.6 (+37.4), 0 vs 5,244 m³, +33 km; hospital 13 min, 0 → 9,600 m³; optimize after the hospital beat chooses c02 over c00 (worst-20% 13.5 vs 14.5, baseline 53.5); at 5:00 it keeps c00. Updated DEMO.md, QA.md, devpost outline, HANDOFF (website status, playback gap, uv sync --extra dev gotcha, snapshot ember-engine-1b76fade79).
Files: docs/DEMO.md, docs/QA.md, docs/devpost/README.md, docs/HANDOFF.md, docs/log/aryaman.md
Interfaces: none. Soham: please add `GET /playback?planner=ember|baseline` → `EngineSession.playback(planner)` (contracts/playback.schema.json); the website's Live mode calls it.
Status: done.

## 2026-10-17 23:30 · residents: multiplayer join by text + GET /playback (D78–D79) · branch aryaman/multiplayer
What: Photon docs checked (read-only): a shared iMessage line only delivers assigned handles; the SMS number delivers `message.received` from any sender, so it is the join line (replies there need the line's SMS campaign). Unknown phone texts "JOIN EMBER" → Player N (cap MAX_PLAYERS=30, else "drill is full") → a free flood-zone town building chosen by us (deadline > now + 20 min, emptiest corner first, earliest flood) labelled "Player N", needs unknown; joins < 2 s apart share one replan; /dev/reset places players again. GET /phones adds `player`, `household_id`; GET /health adds `join_number`. GET /playback?which=ember|baseline, cached per plan version. Cleanups: `Messenger._route` replaces the 4× delivery chain; removed `PhotonClient.list_assignments`, `EngineSession.edges_at_household`.
Files: residents/residents/{messaging,locate,engine_bridge,planner,app,config,photon,threads,db}.py, residents/tests/{test_drill,test_engine,test_api,conftest}.py, residents/README.md, engine/ember_engine/api.py, engine/tests/test_api.py, docs/DECISIONS.md
Run: cd residents && uv run pytest -q; cd engine && uv run pytest -q
Interfaces: GET /playback?which=…; GET /phones items gain `player`, `household_id`; env JOIN_NUMBER, MAX_PLAYERS. No contract change.
Status: done, pushed, not merged.

## 2026-10-18 00:20 · Daytona Tier 2 at scale: warm pool, chunked jobs, honest startup (D82) · branch aryaman/daytona-tier2
What: the backend keeps one DaytonaPool warm (started in the background at startup, reused by every /optimize, closed on shutdown); jobs go to sandboxes in chunks of ⌈jobs ÷ sandboxes⌉ per run_code; `search.robust.startup_s` separate from `fanout_wall_s`; orphaned ember sandboxes (idle > 3 min) deleted at start; a dead warm pool restarts; shortfalls logged. EMBER_DAYTONA_WORKERS=90 in engine/.env; seeds default 50, max 200. Snapshot rebuilt: ember-engine-c1810d2a07.
Files: engine/ember_engine/daytona/{pool,jobs,robust}.py, engine/ember_engine/{api,cli}.py, engine/scripts/e2e.py, engine/tests/test_daytona.py, residents/residents/{engine_bridge,planner,app}.py, web/src/App.tsx, docs/{DECISIONS,HANDOFF}.md
Run: cd engine && uv run ember robust --scenario ../scenarios/allston_flood_v1/scenario.json --seeds 200
Interfaces: plan.search.robust gains `startup_s`; POST /optimize seeds 1..200 (default 50).
Status: done. Engine 101 passed, residents 259 passed. Live: warm 1,000 runs in 0.9 s (local 3.6 s); backend /optimize 1.6–2.7 s; web scatter shows 1,000 points. No sandboxes left running.
Next: rebuild the snapshot after merging any change to a sandbox-imported module; the web could show `startup_s` next to the fan-out time.

## 2026-10-17 23:30 · residents: EMBER calls the most at-risk first; simulated calls; spoken wording (D80) · branch aryaman/voice
What: `Voice.check` on the plan and clock hooks calls opted-in residents (a real number, no call on, not mid-text) for no reply to an open offer/step/question for ≥ 180 sim-s within 45 sim-min of their deadline, an unconfirmed wheelchair/medical need, or a pickup changed in the last 30 sim-min; earliest deadline first, `VOICE_MAX_CONCURRENT` (2), one call per wait and per change, 15 sim-min cooldown per (phone, reason) in kv `call:` (cleared on reset); only when ElevenLabs is configured. Calls end when ElevenLabs reports the conversation done (`reap`) and the plan follows by text. `GET /calls` → `{live, recent}` with reason/outcome/turns. `scripts/sim_calls.py` runs six people end to end (fake ElevenLabs via MockTransport, turns through the Custom-LLM endpoint, keyword parser instead of the LLM) and prints timed transcripts; read them and fixed what a judge would wince at: opening = who + why in one sentence then one thing; "hello?"/"sorry, what?"/"who is this?"/"thanks, bye" handled by the call; "I'll text you this too."; calls skip examples, out-by time and the plan's reasons; "oh, yes please" = yes, "okay, what changed?" = question, "we're ready" = done, caring decline, shelter answer, pets.
Files: residents/residents/{voice,outbound,speech,fallback,guide,intake,briefing,locate,app,config,db,drill}.py, residents/scripts/sim_calls.py (new), residents/tests/{test_voice,test_fallback,test_questions,test_drill,conftest}.py, residents/{README.md,.env.example}, docs/voice_transcripts.md (new), docs/DECISIONS.md
Run: cd residents && uv run python scripts/sim_calls.py --out ../docs/voice_transcripts.md; uv run pytest -q
Interfaces: GET /calls is now `{live: [{handle, household_id, reason, started_t_s, turns}], recent: [{handle, household_id, reason, outcome, turns, ended_t_s}]}` (was `{calls, live}`); POST /calls reason "console". configure_agent also sets the agent's first message for calls in. Tests blank ELEVENLABS_API_KEY in conftest so no test can dial.
Status: done. Residents 269/269, engine 100/100. Sim: 7 calls (6 people; Sam twice, one per pickup change), every turn answered in < 1 s (replans 0.7–0.8 s); 5 end confirmed, 2 informed.
Next: web: show live calls (badge + reason) from GET /calls; a live check with a real phone once the tunnel is up (VOICE_MAX_CONCURRENT=0 turns proactive calls off for the stage if needed).

## 2026-10-17 · residents: simulator-graded eval of the text → fact step, Chalk router seam (D83) · branch aryaman/sim-eval
What: `residents/scripts/eval_sim.py` plans and simulates the gold and the extracted reading of every samples.json message from one seeded plan. It scores each one on reached-before-deadline with an eligible vehicle, regret (unreached / hospital outage / overflow) and asked-instead-of-guessing, and prints a table and a pass rate (`--extractor fallback` by default, `--extractor llm` not run). The eval found two D75 parser bugs ("my house and I" read as 2 people with no mobility need; "accessible vehicle" dropped); both are fixed with test cases. The Chalk AI Router is an opt-in seam (`anthropic_client` in extract.py, used by both model calls) with a fake-transport test. samples.json: `gold` for #32.
Files: residents/scripts/eval_sim.py (new), residents/tests/test_eval_sim.py (new), residents/residents/{extract,reply,fallback}.py, residents/tests/{test_extract,test_fallback}.py, residents/tests/samples.json, docs/eval.md (new), docs/DECISIONS.md
Run: cd residents && uv run python scripts/eval_sim.py; uv run pytest -q
Interfaces: env CHALK_ROUTER_KEY + CHALK_ENV_ID (optional). No contract change.
Status: done. Fallback parser 46/51 pass, 4 ask, 1 fail (#32 "Welch's"), 98 % safe. The live Chalk router hasn't been called.

## 2026-10-17 23:30 · web: judge-facing declutter, proof on screen, multiplayer QR + roster, live replay, clock off React (D81) · branch aryaman/frontend-clean
What: Rebuilt the website shell around one story. Thin top bar + ⚙ settings; floating score card (4 numbers with deltas vs baseline, "plan vN · replanned in X s"); 3 tabs Feed / Plan / Proof with an inspector drawer; toasts (plan-diff toast on every new live version); Proof shows the comparison (or the forecast world from the two replays) and the Daytona throughput + chosen/forecast-best/baseline worst-20 %; Sources & what-is-synthetic dialog (OSM, City of Boston/Cambridge, MWRA 2024 Cottage Farm 21.33 MG ≈ 80,700 m³, Climate Ready Boston, synthetic labels). Multiplayer: QR card from VITE_JOIN_NUMBER, roster from GET /phones, player pins + on-call ring from GET /calls. Live replay via GET /playback?which=… with abort + keep-last-good. Clock is an external store: only the stage re-renders per frame; MapLibre/deck.gl lazy-loaded; scatter as 3 paths with per-frame batching. Deleted the no-op toggles, legend modes, KPIs strip, banner, notice and the dead code listed in the audit.
Files: web/src/{App.tsx,clock.ts (new),fixtures.ts,format.ts,layers.ts,live.ts,model.ts,people.ts,playback.ts,styles.css,types.ts,vite-env.d.ts}, web/src/components/{FlatMap.tsx (new),Hud.tsx (new),MapView.tsx,Panels.tsx}, web/src/iso/{IsoView.tsx,agents.ts}, web/package.json, docs/{DECISIONS.md,QA.md,DEMO.md}
Run: cd web && npm run build && npm run check:closures && npm run check:crowd; VITE_JOIN_NUMBER=+1… npm run dev → /?live for Live
Interfaces: consumes the shared interface (GET /playback?which, /phones player + household_id, /calls live/recent, plan.search.robust.startup_s); all optional, older backends degrade quietly. No contract change.
Status: done, pushed. Checked in the browser at 1440×900: Fixtures (t=0, 1h30, baseline switch, flat map, drawer, all tabs) and Live against a local backend on :8001 (no keys, Photon/extraction off): plan v1 → v2 → v3 toasts and score card update; /phones, /calls, /playback mocked in-page to check the roster, player pins, on-call ring and live replay.
Next: re-measure DEMO beat 5 at 50 seeds; set VITE_JOIN_NUMBER (and JOIN_NUMBER on the backend) for the table QR.

## 2026-10-18 00:30 · integration: five branches together, e2e 71/71 with Daytona, pool stays at 90 (D84) · branch aryaman/integration
What: Finished the integration of daytona-tier2, multiplayer, voice, sim-eval and frontend-clean. The dev console joins unknown phones that text "join ember"; validate_state accepts player households; /health reports max_players. e2e.py now checks playback in both modes against the contract, /calls {live, recent}, 250 Daytona runs as scatter_points with startup_s, and three JOIN EMBER phones → Players 1–3 on distinct flood-zone households with one replan, a 4th refused. Found and fixed the warm pool shrinking on every /optimize (dropped setup connections deleted sandboxes): compressed batch setup + retries (D84). CLAUDE.md rule 2 now says the AI talks and the planner decides (D76); HANDOFF rewritten; DEMO beat 5 re-measured at 50 seeds; residents/VOICE_PLAN.md deleted (README covers calls); residents/HANDOFF.md trimmed to current facts.
Files: engine/ember_engine/{state.py,daytona/pool.py,daytona/jobs.py}, engine/scripts/e2e.py, engine/tests/test_daytona.py, residents/residents/{app.py,messaging.py}, residents/tests/{test_api.py,test_drill.py}, CLAUDE.md, docs/{HANDOFF.md,DEMO.md,DECISIONS.md}, residents/{HANDOFF.md,VOICE_PLAN.md (deleted)}
Run: cd engine && uv run pytest -q && uv run ember smoke; cd residents && uv run pytest -q; backend with the e2e docstring's env on a fresh DB, then uv run python ../engine/scripts/e2e.py
Interfaces: /health gains max_players. No contract change. Snapshot ember-engine-0f3cf261d7.
Status: done, pushed to aryaman/integration (not merged). engine 102, residents 279, web tsc + build, smoke OK, e2e 71/71, sim_calls 7 calls, eval_sim 46/51.
Next: merge to main after review; live checks of the SMS join reply (campaign), Chalk router and the LLM eval column.

## 2026-10-18 03:00 · engine: distinct robust candidates, laptop vs Daytona measured, Utility truck, ruff (D86) · branch aryaman/fix-engine
What: `robust_plan` runs each distinct candidate once (`distinct`: live assignments; the "generators re-targeted" variants were clones) and keeps the forecast-best unless the most robust plan saves ≥ 1 person in the worst 20 % (`choose`, `MIN_GAIN`). Measured `ember robust` laptop (8 processes) vs Daytona (90 warm sandboxes) at 250 / 1,000 / 5,000 / 10,000 worlds: 2.3 / 4.5 / 13.7 / 24.3 s vs 2.1 / 2.6 / 4.0 / 5.3 s, identical results. Tried re-seeded and stress-scored local search for diversity: same forecast score, 2–12 people worse in the worst 20 %, so not shipped. Renamed the passenger truck to Utility truck. Engine ruff config (E9/F/B, B905 off) with every hit fixed; dead `diorama.bbox_mapping` removed; `geo.metres_per_deg` / `geo.local_metres` replace the degree literals in diorama.py and playback.py.
Files: engine/ember_engine/{daytona/robust.py,geo.py,diorama.py,playback.py,build_town.py,cli.py,scenario.py,world.py,allocator/search.py,engines/noop.py,engines/queue_traffic.py}, engine/tests/{test_daytona.py,test_playback.py,test_scenario.py}, engine/pyproject.toml, engine/data/allston_flood_v1.seed_state.json, scenarios/allston_flood_v1/scenario.json, contracts/fixtures/playback{,.baseline}.fixture.json, docs/{DECISIONS.md,HANDOFF.md}
Run: cd engine && uvx ruff check . && uv run pytest -q && uv run ember smoke; uv run ember robust --scenario ../scenarios/allston_flood_v1/scenario.json --seeds 2000 --workers 90
Interfaces: `plan.search.robust.rule` text mentions the 1-person bar; `chosen` may now differ from `ranking[0]` (when the gain is under 1 person). No contract change. Snapshot ember-engine-87ccf09179.
Status: done, pushed. engine 103 + smoke, residents 279, web tsc + build; live Daytona runs at all four sizes, 0 sandboxes left.
Next: raise the backend's `/optimize` cap (seeds ≤ 200) to 2,000 so the demo can show 10,000 worlds; reword the web's "also the most robust" line to "within 1 person of the most robust" when `chosen != ranking[0]`.

## 2026-10-18 · residents: texts work without a model, readable triggers, LAN CORS, shorter calls (D85) · branch aryaman/fix-backend
What: with no ANTHROPIC_API_KEY or EXTRACT_ENABLED=0 the Intake still runs and texts go straight to the keyword parser → to_outcome → replan. Planner._trigger names the reporter and the fact without ids (operator wording for facility news; closure reports carry the sender's household); joins read "Players 1, 2, 3 joined". CORS by regex (localhost / 127.0.0.1 / 192.168.x / 10.x, any port). /optimize seeds ≤ 1000. Calls: a short re-greeting on "hello?" / "sorry, what?", no step labels / packing lists / destination / doubled ETA on a call, the reason a confirmed pickup moved (blocked roads), stay-put → safety advice, a calm line for panic. Settings is the only os.environ reader; make_llm / make_writer / anthropic_client take Settings. The drill fixtures moved to conftest; ruff F clean.
Files: residents/residents/{app,config,drill,extract,fallback,intake,locate,outbound,planner,reply,speech,threads,voice}.py, residents/scripts/{eval_extract,eval_sim,sim_calls}.py, residents/tests/{conftest,test_api,test_drill,test_engine,test_extract,test_fallback,test_listener,test_operator_simulate,test_outbound,test_questions,test_reply,test_voice}.py, residents/{README.md,HANDOFF.md,.env.example}, docs/{voice_transcripts.md,DECISIONS.md}
Run: cd residents && uv run pytest -q && uv run python scripts/sim_calls.py --out ../docs/voice_transcripts.md
Interfaces: env CORS_ORIGINS → CORS_ORIGIN_REGEX; /health `extraction` = whether a model reads texts; POST /optimize seeds 1..1000. No contract change.
Status: done, pushed, not merged. Residents 287 passed, engine 102 + smoke, web tsc + build; e2e 70/71 on a keyless backend (the one fail is the expected local pool); eval_sim 46/51 unchanged; sim_calls longest turn 21 s (was 29 s).
Next: the engine renames truck-1 to "Utility truck" (other workspace); re-run sim_calls after it lands.

## 2026-10-18 · web: judge fixes — correct plan toasts, latest-change strip, honest latency, sewage kept, projector type (D87) · branch aryaman/fix-web
What: Fixed the off-by-one plan-diff toast (the `assignment` reducer spread the old plan's metrics and changes into the new version; now it only patches the current version and toasts fire from full plans), so toast count = feed count. Live is the default when `VITE_API_BASE` is set; a pinned strip at the top of the map says what came in, what the plan did and how fast ("Judge: 2 people · mobility need · accessible vehicle → 3 vehicles rerouted · … · v3 replanned in 0.8 s"; texted quotes when a message carries the report). Feed plan rows use the same plain-language cause (no report ids) and messages upsert by id (the backend re-sends them with `report_id`). Score card: robust timing after Optimize, "People still at home now", "Kept out of the Charles" frozen before the hospital trade-off plus the stated trade, a synthetic chip that opens Sources. Proof keeps the last robust result from `GET /optimize`. Projector typography and a ×1.2 presenter scale at ≥ 1600 px; cyan flood with an edge; stage label cleanup; household dots until zoomed in. Join card from `/health`, Android-safe QR, "Reply needed". Deleted dead exports (assignmentsOf, positionForTarget, isSameSelection, VEHICLE_KINDS, FloodFeature) and the unused `deck.gl` / `@deck.gl/react` deps; declared `@deck.gl/extensions`; `npm test` runs check:ws, check:closures, check:crowd.
Files: web/src/{App.tsx,format.ts,model.ts,types.ts,sprites.ts,layers.ts,styles.css}, web/src/components/{Hud.tsx,Panels.tsx}, web/src/iso/{IsoView.tsx,water.ts}, web/{package.json,package-lock.json}, docs/DECISIONS.md
Run: cd web && npx tsc --noEmit && npm run build && npm test; VITE_API_BASE=http://127.0.0.1:8000 npm run dev (Live by default, ?fixtures for fixtures)
Interfaces: reads GET /health join_number + max_players and GET /optimize last.robust (both exist). No contract change.
Status: done, pushed. Engine 102, residents 279, web tsc + build + npm test. Checked against a local backend on :8011 (EMBER_LOCAL_POOL=1, no keys) at 1440×900 and 1920×1080 (headless Chrome over CDP; the in-app pane was hidden): first load (v1 strip), judge need + River St (toasts v1→v2 "5 households reassigned", v2→v3 "11 households reassigned", same as the feed), 3 JOIN EMBER phones (3/30, Reply needed), hospital (kept 5,167 m³ + stated trade, 13 min −14 vs baseline), Optimize (robust pick · 250 worlds · 3.8 s on 8 local workers), then a closure (replanned in 0.8 s, Proof still shows the robust result).
Next: residents should drop report ids from `plan.trigger` (the web already falls back to the trigger text when no report id is in it); after a page reload past the hospital beat the tile falls back to "Sewage overflow" (the pre-trade value lives only in the open page).

## 2026-10-18 02:00 · docs + repo hygiene for judging (D88) · branch aryaman/fix-docs
What: Root README rewritten as the judge landing page: the loop, four-line architecture, a measured results table (88.6 vs 51.6 reached, hospital outage 11 vs 28 min, 0 vs 2,317 m³ at plan v1 against the real 80,700 m³ Cottage Farm anchor, 0.66 s replan, worst-20 % 15.7 vs 55.2), where Daytona / Photon (iMessage, SMS join, voice) / the AI are used, how we evaluate (eval 46/51, e2e 71/71, unit tests), real vs synthetic, what is not verified live, climate adaptation, run it; screenshot placeholder for docs/img/. DEMO.md cut to 3:00 (framing, household rescue, power loss, multiplayer QR, Daytona, 15 s proactive call) with changeable numbers marked †; QA.md follows the 3-tab UI and QR card; HANDOFF says integration is on main; Devpost outline gets "Who built what" with blank lessons and its stale sponsor numbers corrected. Removed the root duplicate plan, the internal track memo and the unused web/public/diorama/test.json (nothing loads it); .claude/ gitignored. New CI: engine and residents tests, web build.
Files: README.md, .gitignore, .github/workflows/ci.yml (new), docs/{HANDOFF.md,DEMO.md,QA.md,DECISIONS.md,devpost/README.md}, EMBER-hackharvard-2026-plan.md + EMBER-track-ratings-and-improvements.md + web/public/diorama/test.json (deleted)
Run: cd engine && uv sync --extra dev && uv run pytest -q; cd residents && EMBER_LOCAL_POOL=1 GEOCODE=0 uv run pytest -q; cd web && npm ci && npm run build
Interfaces: none changed.
Status: done, pushed. engine 102, residents 279, web tsc + build pass locally; CI not yet seen green on GitHub.
Next: every † number in DEMO/QA/README re-measured after the fix round; screenshots into docs/img/; each teammate writes their Lesson line in docs/devpost/README.md.

## 2026-10-18 00:30 · round 2: fix branches merged, register-then-text join, call-back fallback, re-measured (D89, D90) · branch aryaman/round2
What: Merged fix-engine, fix-backend, fix-web and fix-docs (--no-ff; DECISIONS D85–D88 in order, every log entry kept). New join flow on the shared iMessage line: `POST /join` (Photon assignment, Player N, idempotent, 409 over MAX_PLAYERS=25), the first text places the phone as before; the SMS unknown-sender join and JOIN_NUMBER are gone. Web join card: number → Join → QR `sms:<line>?&body=JOIN%20EMBER`, roster "waiting for text". A text Photon refuses after its retries triggers a call (reason undelivered, D80 rules). `/optimize` seeds up to 2000 (10,000 worlds). Verdict/toast say "Kept the forecast plan: no candidate beats it by ≥ 1 person in the worst 20%" and show the most robust candidate when it differs. Residents tests say Utility truck; sim_calls re-run into docs/voice_transcripts.md. e2e registers then texts and has `--big` (10,000 worlds). README/DEMO/QA/HANDOFF numbers re-measured, † marks dropped, snapshot ember-engine-87ccf09179 (unchanged, no rebuild).
Files: residents/residents/{app,config,db,locate,messaging,voice}.py, residents/tests/{conftest,test_api,test_drill,test_outbound,test_reply,test_conversation}.py, residents/{README.md,HANDOFF.md,.env.example}, web/src/{App.tsx,components/Hud.tsx,components/Panels.tsx,fixtures.ts,styles.css,vite-env.d.ts}, engine/scripts/e2e.py, README.md, docs/{DEMO.md,QA.md,HANDOFF.md,DECISIONS.md,voice_transcripts.md,devpost/README.md}
Run: cd residents && uv run pytest -q; backend on :8020 (e2e.py docstring env, MAX_PLAYERS=3, engine/.env for Daytona) then `uv run python ../engine/scripts/e2e.py --base http://127.0.0.1:8020 --big`
Interfaces: new POST /join {handle} → {handle, player, assigned_number, dev, household_id, texted}; /health drops join_number, adds players; MAX_PLAYERS default 25; POST /optimize seeds 1..2000; env JOIN_NUMBER and VITE_JOIN_NUMBER removed. No contract change.
Status: engine 103 + smoke, residents 290, web tsc + build + npm test, e2e 79/79 with real Daytona (250 runs 3.15 s fan-out; 10,000 runs 4.1 s fan-out). Measured: v1 78 vs 58 reached, 0 vs 2,317 m³; judge v2 0.61 s; River St 0.79 s; hospital 0.81 s, outage 13 vs 27 min; 5-world comparison 88.6 vs 51.6, outage 11 vs 28 min; worst-20 % 15.7 vs 55.2 (250 worlds), 18.0 vs 54.0 (10,000). 0 Daytona sandboxes left.
Next: run-through with real phones (join card → iMessage, one call); screenshots; Devpost lessons.

## 2026-10-18 00:25 · Chalk for real + pitch sheet · branch aryaman/chalk-eval · commit (this PR)
What: Chalk Model Gateway set up (connection `ember`, prefix anthropic/, env mbrx0d03eb41, router key in residents/.env only). One real extraction call through Chalk: correct structured reading in 2.5 s. Simulator-graded eval with the real model through Chalk: 50/51 pass, 1 ask (#32 "Welch's" → asks), 0 fail, 100 % safe (D91). docs/eval.md, README updated; docs/PITCH.md (3-minute pitch + judge Q&A) added.
Files: docs/eval.md, README.md, docs/PITCH.md, docs/DECISIONS.md, docs/log/aryaman.md
Status: done.

## 2026-10-18 · round 3 backend: sewage number, voice wording, join hardening, urgent texts, pool owners, cleanup (D92) · branch aryaman/r3-backend
What: Planner records `plan.search.kept_before_tradeoff_m3` (baseline − EMBER overflow, frozen once a plan trades sewage for a facility) so the web tile reads one stable number from state. Calls disclose "an automated assistant", ask "Can you be ready?" / "Tell me when you're outside.", give a reason on every pickup change, read ETAs from the simulated view like the texts; sim_calls re-run into docs/voice_transcripts.md. `/join` counts every Photon assignment toward the cap, releases players who never texted within 10 min (Photon DELETE, new idempotency generation on re-join) and says iPhone-only. Urgent texts (water at the door, trapped, hurry, help) → `urgent` fact → replan + reassurance + current ETA. Daytona pool: per-process owner label, sweep only own or expired. One `_send_or_call`; ruff in residents + CI; raw_status/unplace_phone deleted; tests/helpers.py; replan latency timed as CPU time.
Files: engine/ember_engine/daytona/pool.py, engine/tests/{test_daytona,test_allocator}.py, residents/residents/{planner,voice,speech,outbound,briefing,messaging,photon,db,fallback,extract,intake,drill,config}.py, residents/scripts/{sim_calls,eval_sim}.py, residents/tests/* (helpers.py new), residents/{pyproject.toml,README.md}, .github/workflows/ci.yml, docs/{DECISIONS.md,HANDOFF.md,voice_transcripts.md}
Run: cd engine && uv sync --extra dev && uv run pytest -q && uvx ruff check .; cd residents && uv run pytest -q && uvx ruff check .; uv run python scripts/sim_calls.py --out ../docs/voice_transcripts.md
Interfaces: plan.search.kept_before_tradeoff_m3 (number or null) on every plan; POST /join adds `note`; seats = every Photon assignment (team phones count); fact kind `urgent` (extraction schema); PhotonClient.release_assignment, create_assignment(handle, generation). No contract version change.
Status: done, pushed (no PR). Measured on the judge beats: kept 2,316.7 m³ at v1, 5,166.7 at v2, still 5,166.7 at v3 after the hospital call (9,600 vs 9,600). Release endpoint taken from api.photon.codes/openapi.json; not exercised live.
Next: web tile reads plan.search.kept_before_tradeoff_m3 (web session); show `note` on the join card; one real call and three real joins.

## 2026-10-18 · web round 3: Daytona stress test, pre-season pick, reporter-first diffs, join confirm (D93) · branch aryaman/r3-web
What: Proof gets "Stress test 10,000 worlds" next to Optimize (Pre-season stress test at clock 0), a throughput tile (live pool/workers/fan-out/startup; on Daytona "laptop ~24 s measured" from `robust.laptop_s` or the D86 constants), the heading names the pool, "n / N worlds back", a pre-season verdict (robust pick vs forecast plan) and a per-pixel-deduplicated scatter for 10,000 runs; the robust result now comes from any plan carrying it. Plan diffs lead with the reporter's own job ("Judge → Accessible Van 3, pickup in 95 min · 3 vehicles rerouted"), the strip shows it with the trigger after, the duplicate plan toast is gone, `planCause` (report-id regex) removed. Sewage tile and Proof row read `kept_before_tradeoff_m3` from the plan (fallback: plain overflow tile). Join card confirms "Player 2 joined: you're household #6748 on Soldiers Field Road" for 5 s, then resets; "iPhone (iMessage) only"; sentence-case pills. 31 file-local exports un-exported.
Files: web/src/{App.tsx,format.ts,model.ts,types.ts,live.ts,geo.ts,layers.ts,people.ts,playback.ts,sprites.ts,styles.css}, web/src/components/{Panels.tsx,Hud.tsx}, docs/DECISIONS.md
Run: cd web && npm run build && npm test; backend on :8041 (EMBER_LOCAL_POOL=1, keys off) + VITE_API_BASE=http://127.0.0.1:8041 npx vite --port 43141 --strictPort
Interfaces: reads plan.metrics.kept_before_tradeoff_m3 ?? plan.search.kept_before_tradeoff_m3 and plan.search.robust.laptop_s (both optional, from the backend workspace); POST /optimize?seeds=2000 (exists). No contract change.
Status: done, pushed. Engine 103 + smoke, residents 290, web tsc + build + npm test. Checked in headless Chrome (CDP; the in-app pane was hidden) at 1440×900 and 1920×1080 on a local-pool backend: Pre-season stress test at 0:00 → c03 12.0 vs c00 27.8 (250 worlds, 3.3 s, 8 local workers); 10,000 worlds streamed with progress, c03 15.9 vs c00 30.7, 42 s on this laptop (loaded); judge need → "Judge → Accessible Van 3, pickup in 95 min · 3 vehicles rerouted"; River St → judge's van first, then Generator 1 → Cottage Farm; hospital → "Mount Auburn Hospital → Generator 1, on site in 8 min"; Optimize at 15:00 keeps the D86 wording (c04 14.9 vs c00 15.9); join card QR → confirmation → reset. Daytona tile not seen live (no Daytona in this run).
Next: backend workspace adds kept_before_tradeoff_m3 (and laptop_s if wanted); during the local 10,000-run stress test the page kept the old robust result (most likely a GET /optimize poll timed out under load; not confirmed, and the plan event now covers it); the optimize plan at t=0 has an empty `changes` list, so the strip says "no assignment changed" for a pre-season pick.

## 2026-10-18 · round 3: second hazard on the same engine, overflow separates robust candidates (D94) · branch aryaman/r3-hazard
What: Scenario contract 0.3 adds `hazard.type: "ellipse"`; `load_scenario` samples `GrowingEllipseHazard` (now built from an origin lon/lat, `ellipse_from`) every 5 min into keyframes. New `scenarios/allston_plume_v1` (synthetic chemical plume south of the Treehouse, 22 households, 3 vans; scenario.json + assumptions.md): compare 50.8 vs 28.6 reached. Robustness sampler perturbs sewage inflow 0.8–1.3× and storm timing (≤ 30 min early, `Wastewater.lead_s`); `robust_plan` adds `c00-trip` (forecast-best, generator sent at the forecast grid trip): at t=0 it ties c00 on people and spills 3,995 vs 77 m³ in the worst 20 % (0 vs 0 on the forecast). README gets "Same engine, second hazard"; README/DEMO/QA/HANDOFF/devpost robust numbers re-measured (e2e on the local pool, deterministic).
Files: contracts/scenario.schema.json, engine/ember_engine/{hazards,scenario}.py, engine/ember_engine/daytona/{jobs,robust}.py, engine/ember_engine/models/wastewater.py, engine/ember_engine/sim/plan_sim.py, engine/tests/{test_engine,test_scenario,test_daytona}.py, scenarios/{README.md,allston_plume_v1/}, README.md, docs/{DECISIONS,TECHNICAL,DEMO,QA,HANDOFF}.md, docs/devpost/README.md
Run: cd engine && uv run ember validate-scenario ../scenarios/allston_plume_v1/scenario.json && uv run ember compare --scenario ../scenarios/allston_plume_v1/scenario.json --seeds 5; uv run ember robust --scenario ../scenarios/allston_flood_v1/scenario.json --seeds 50
Interfaces: scenario 0.3 (optional ellipse hazard; 0.2 files unchanged). Robust ranking gains a `c00-trip` row when the forecast-best has a generator not yet dispatched (t=0, not 15:00). New perturbation key `storm_lead_s`. No web change.
Status: engine 104 + smoke; snapshot rebuilt → ember-engine-d9ea4508c1; live `ember robust` on 50 Daytona sandboxes (300 runs, 1.7 s fan-out, identical to local) with the orphan sweep bypassed so other sessions' sandboxes were safe, 0 left. e2e --big on the local pool 76/78 (the 2 Daytona-only checks).
Next: Optimize at 15:00 now publishes c04 and moves the judge's confirmed Van 3 pickup 85 → 111 min (deadline 165): rehearse the beat or narrate it; a "pre-season" view in the web could show the c00-trip overflow line.

## 2026-10-18 · round 3 integration: backend + web + hazard, pre-season Daytona beat, re-measured (D95) · branch aryaman/round3
What: Merged r3-backend, r3-web, r3-hazard (--no-ff; DECISIONS D92–D94 in order, every log entry kept). Web reads the sewage number from plan.search only (dropped the metrics fallback). e2e.py: plume scenario validates, kept_before_tradeoff_m3 at v1 and frozen after the hospital trade, /join iPhone note. DEMO.md reordered: the Daytona pre-season stress test (10,000 worlds) is beat 1 at 0:00, every resident /dev/inbound fallback names household_id 10296; QA.md, README results, HANDOFF, PITCH re-measured.
Files: engine/scripts/e2e.py, web/src/{format,types}.ts, docs/{DEMO,QA,HANDOFF,PITCH,DECISIONS}.md, README.md, docs/log/aryaman.md
Run: cd residents && DB_PATH=<fresh> RESET_ON_START=1 PHOTON_ENABLED=0 EXTRACT_ENABLED=0 MAX_PLAYERS=3 (empty model/voice/Chalk keys) uv run uvicorn residents.app:app --port 8050; uv run python ../engine/scripts/e2e.py --base http://127.0.0.1:8050 --big
Interfaces: none changed.
Status: engine 106 + smoke + ruff, residents 301 + ruff, web build + npm test, e2e --big 83/83 with real Daytona (250 runs 1.8 s fan-out, 10,000 runs 4.9 s; pre-season 10,000 at 0:00 3.2–4.0 s, c03 15.74 vs c00 30.34, baseline 40.84). Snapshot unchanged (ember-engine-d9ea4508c1). No sandboxes left.
Next: run-through with real phones (join, release, urgent text, one call); re-run the Chalk eval with the urgent kind; the backend's t=0 robust run lacks the c00-trip row (HANDOFF open issues).
## 2026-10-18 06:30 · web: stage readability and a living, fast city (D96, D97) · branch aryaman/stage-polish
What: Terrain-following flood water (USGS 3DEP 4 m grid baked in stage.json; visual only), label priorities + collision culling + projector sizes, overlay-safe camera fit with refit on resize, modelled fleet, 35 real traffic signals (OSM), passers-by 1,200 → 3,200 adaptive, district-zoom static snapshot + small-prop LOD + idle-only tile baking, `?perf` readout. Live mode verified against a keyless backend: the stage draws the backend's /playback traffic (2,893 cars), not the fixture. Folded in judge round-2 asks (safe-rect fit, 13–14 px labels, no km suffixes, Treehouse once).
Files: engine/ember_engine/diorama.py, web/public/diorama/stage.json, web/src/iso/{water,fleet,signals,snapshot,props,scene,tiles,density,crowd,data}.ts, web/src/iso/IsoView.tsx, web/scripts/check-crowd.ts
Run: cd web && npm run build && npm test; open /?perf (fps readout), /?live for the backend
Interfaces: no contract change (stage.json gains elev and signals; web is its only consumer).
Status: web tsc + build + npm test pass; engine 103; residents 290; e2e 75/75 (keyless backend). Steady state under 16.7 ms at every zoom measured at 1440×900 and 1920×1080 on an M3 Pro (hidden-pane timings are noisy; ?perf is the check on a visible screen).
Next: verify fps with ?perf on the projector machine; vehicle sprites stop for nothing (the traffic run has no signals).

## 2026-10-18 · Everyday traffic and readable traffic lights (D98)
What: the roads were empty until the evacuation's first car (t = 2,800 s) and the signals were hidden below zoom 0.7 and tiny above it. Added `web/src/iso/ambient.ts`: illustrative everyday cars on the OSM road graph that follow each other, stop at the real signalised junctions' red and amber, turn back at the flood and thin out as the evacuation runs. Signals keep a minimum on-screen size, one per junction from afar, with a mast arm up close. Cars keep a minimum size and get brake lights and headlights. Sources panel line added; `FloodWater.wetAt`.
Interfaces: no contract change.
Status: web tsc + build + npm test (ws, closures, crowd, traffic) pass; `ambient.step` about 0.2 ms; checked in headless Chromium at district, mid and close zoom and late in the flood (no cars in water).
Next: push/PR on approval.

## 2026-10-18 · Cars no longer pass through each other (D99)
What: engine trails follow road geometry (every tick + vertices + 1.5 m simplification); the evacuation cars keep to the right-hand lane with queue gaps on screen; everyday cars take turns through junctions; the stage carries one-way flags; the `ember diorama` math import is restored.
Interfaces: playback fixture regenerated (same schema, denser traffic paths); stage.json roads gain optional `ow`.
Status: web tsc + build + npm test pass; engine pytest 103/103. Measured overlaps between evacuation cars at t = 4,200 s: 49 → 0.
Next: push/PR on approval. Visual polish paused at the user's request.

## 2026-10-18 · No "drill" wording in the web, player labels stack instead of overlapping
What: the header reads "Allston flood · live simulation", the join card reads "Join the flood", and the full-roster error, Feed placeholder, QR label, Sources line and QA.md drop "drill" (the backend wording changes on aryaman/call-first). Labels that never yield (players, the judge, the selection) now lift above a label already placed instead of drawing on top of it (Player 1 and Player 3 overlapped at district zoom).
Interfaces: none.
Status: web tsc + build + npm test pass. Label stacking not yet seen with live players. PR #55 open.
Next: merge once CI is green and the user approves; confirm fps in real Chrome with ?perf.

## 2026-10-18 · Calls-first takeover, integration and delivery fixes (D100–D101) · branch codex/call-first-takeover
What: at Aryaman's request, Codex preserved the unfinished aryaman/call-first diff, applied it onto main c0ca991, kept the latest stage/traffic work, and renumbered the colliding D99 voice decision to D100. Calls first, one retry, clock-driven guidance without required YES/DONE, first-contact disclosure and speech revision guards are integrated. Reproduced and fixed duplicate concurrent dials, updates lost during dialing, discarded first caller needs, idle calls without follow-ups, and obsolete queued arrival warnings; six regression tests include retry with a paused clock. Aligned engine/fixture questions and rehearsal docs.
Files: residents/ (call flow + tests), engine/ember_engine/{allocator/explain,state}.py (wording only), contracts/fixtures + state schema description, scenario facility names, web join/feed copy, docs/CALLS_FIRST_HANDOFF.md, docs/{DEMO,QA,HANDOFF,voice_transcripts,DECISIONS}.md, README.md.
Run: full residents suite 307 passed; full engine suite 106 passed + smoke; web build + all four npm checks; e2e.py --skip-optimize 74/74 against an isolated keyless backend; sim_calls.py five-person scenario completed; ruff + diff check clean.
Interfaces: no contract shape change; state schema description corrected. D100 adds VOICE_POLL_S (5 wall-s) and defaults VOICE_MAX_CONCURRENT to 3. Snapshot remains ember-engine-d9ea4508c1.
Status: done locally on the takeover branch; original Claude worktrees and main untouched. No real calls/texts, provider reconfiguration, paid model calls or Daytona runs.
Next: docs/CALLS_FIRST_HANDOFF.md lists the precise real-phone/provider checks; resume from this worktree rather than the older unfinished branches.

### 2026-10-18 — Codex product polish (D102–D103)

Scoped negative needs, explicit corrections, urgency and unknown-assistance clarification in the fallback; expanded the simulator eval to 56 messages with explicit urgency checks and honest clarification scoring. Fixed the voice-only goodbye, rejected clock-stale optimization results, paused the UI for stress tests and retried transient status failures. Added district loading/error/retry/flat-map recovery, retryable asset caching, phone layouts, bounded map labels, and web behavior checks in CI. Browser exercised the local 250-world batch and both district recovery paths; the expanded fallback eval reports 50 pass, 6 clarification, 0 fail and 56/56 urgency matches. Full verification and live limitations are in `docs/POLISH_QA.md`.

### 2026-10-18 — Codex optimization, reset and live preflight (D104–D106)

Fixed fresh-optimization assignment versions and restored the delayed-generator comparison online. Large stress-test labels and e2e counts now follow paired worlds × actual plans; historical timing claims are kept separate. Guarded confirmations against stale optimization, and state/WS reads against reset’s empty interval. Added explicit local-pool e2e mode: the full large replay passed 82/82 checks (cap skipped at MAX_PLAYERS=25), with 10,000 local runs streamed; engine suite 107 passed. Photon live preflight reproduced ASSIGNMENT_EXISTS for previously registered phones; registration now recovers their live assignments with paginated lookup and leaves unrelated seats untouched. Private live-call data stays outside the repo.

### 2026-10-18 04:40 · Calls that end, short and safe (D107)
What: took over Codex's calls-first branch (D100–D106) as `aryaman/calls-first`; replayed the 4 real ElevenLabs calls from 03:26–03:45 and fixed what they showed: okay/silence/voicemail end the call, the police/911 line, a one-line off-topic answer, a shorter opening question.
Interfaces: needs question text changed in engine explain, seed state and contract fixtures (same schema).
Status: residents 359+ pass, engine 107, web build + checks, ruff clean; sim_calls re-run (docs/voice_transcripts.md).
Next: Daytona snapshot, e2e --big, merge, live call test.

### 2026-10-18 06:10 · Ambulance for medical needs (D114)
What: `ambulance` resource kind (scenario 0.4, state 0.3) and "Ambulance 1" in allston_flood_v1 at EMS Station 14; allocator gives medical needs the ambulance when it is on time (eligibility + construction preference + an objective term after churn), rationale names it; residents' `briefing.fits` mirrors the eligibility.
Interfaces: state schema version 0.3 (residents' `load_seed` follows it; seed state and fixtures regenerated); web needs an `ambulance` sprite/colour (web/src/opening.ts still writes state "0.2").
Status: engine 108 pass, ruff clean, smoke OK, residents full suite green; plan v1 78 vs 58 reached, 0 vs 2,316.7 m³ (unchanged). New snapshot `ember-engine-3884c8eb34`, not built.
Next: integrator builds the snapshot, web draws the ambulance, DEMO.md can mention it.
