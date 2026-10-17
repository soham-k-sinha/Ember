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
