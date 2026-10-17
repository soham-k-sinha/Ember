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
