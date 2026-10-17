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
