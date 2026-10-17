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
