# contracts/

The interface between `engine/`, `web/` and `residents/`. Build against the fixtures; nobody blocks on anybody.

| Contract | Schema | Fixture | Produced by | Consumed by |
|---|---|---|---|---|
| Town (roads, footways, households, assets, exits, zones, venue) | `town.schema.json` | `fixtures/town.fixture.json` (a ~150-edge slice) | `ember build` → `data/town.json` | engine, web (map), residents (households → phones) |
| Plan (what the planner controls) | `plan.schema.json` | `fixtures/plan.fixture.json` | planner / web | engine (`run_job`) |
| Job = plan + scenario (hazard, compliance, seed, horizon) | `job.schema.json` | `fixtures/job.fixture.json` | planner / Daytona fan-out | engine (`run_job`) |
| Metrics (one run's outcome) | `metrics.schema.json` | `fixtures/metrics.fixture.json` | `run_job` (return value; Daytona returns it as `run_code` output) | web (scatter / comparison), residents |
| Scenario (district, flood keyframes, facilities, resources, assisted households, judge, reserve, scripted reports) | `scenario.schema.json` | `fixtures/scenario.fixture.json` (engine-generated example; placeholder numbers) | Anshuman → `scenarios/<name>/scenario.json` | engine (hazard, deadlines, simulator, allocator), backend, web |
| **State v0.2** (snapshot at sim time `t_s`: flood extent, closed edges, assisted households + status, facilities + state + wastewater, resources + position, current plan with assignments / unresolved / info requests, reports, messages, metrics) | `state.schema.json` | `fixtures/state.fixture.json` (example snapshot at 80 min of the example scenario) | backend `GET /state` / WS `state`; engine simulator | web (map + panels), backend |
| Assignment (one resource → one target in a plan version, with ETA, deadline, rationale, route) | `assignment.schema.json` | inside `state.fixture.json` → `plan.assignments` | allocator / example planner | backend (offers, confirmations), web |
| Report (a structured fact from a person or the scenario script) | `report.schema.json` | inside `state.fixture.json` → `reports` | backend (after LLM extraction), scenario `scripted_reports` | engine (replan), web |
| **Comparison** (baseline vs EMBER on paired perturbation seeds: per-metric means, B−A range, wins/ties/losses, computed sentences, plan-version timeline) | `comparison.schema.json` | `fixtures/comparison.fixture.json` (example scenario, 3 seeds) | `ember compare` | web (comparison panel), Devpost |
| **WS events** (every message on `WS /ws`: envelope `{type, seq, t_s, data}`; `seq` gap → re-fetch `GET /state`; types state, plan, assignment, message, report, scatter_point, metrics, arrival; version 0.2, D112) | `ws-events.schema.json` (authored by Soham) | `fixtures/ws-events.fixture.json` (one example envelope per type, built from the other fixtures) | backend `WS /ws` | web (live updates, scatter) |
| Trajectories (sampled vehicles for TripsLayer) | `trajectories.schema.json` | `fixtures/trajectories.fixture.json` (200 trips) | `ember smoke` → `data/trajectories.json` | web (deck.gl `TripsLayer`) |

## Conventions (same as CLAUDE.md)
- Coordinates are `[lon, lat]` (GeoJSON order) everywhere. Separate `lon`/`lat` fields where an object is a point.
- Time is `t_s`: seconds since simulation start (float32-safe for deck.gl). No wall-clock timestamps in the sim.
- Distances in meters, speeds in m/s inside the engine (`speed_kph` only on town edges, as OSM gives it).
- Node and edge references: `edges[].u/v`, `households[].node`, `exits[]`, `venue.node` are **OSM node ids**. `edges[].id` is a dense `0..E-1` index; closures (`metrics.closure_order`, `plan.closed_edges`) use it.
- Edges are directed; a two-way street is two edges.
- Anything listed in `town.meta.synthetic` is generated (household counts, vehicles, flags, imputed lanes, capacities, exits). Say so in the UI.

## Checking a scenario
```bash
uv run --project engine ember validate-scenario scenarios/allston_flood_v1/scenario.json [--deadlines] [--town data/town.json]
```
Schema errors, then referential checks against `town.json` (household / asset / node / edge ids exist, depends_on targets exist and have no cycles, exactly one judge with needs `unknown`, generators have kw + connector, reserve ≤ fleet, keyframes sorted), then warnings (district misses the venue, households outside the district, no generator fits a facility, flood recedes). Prints a one-line summary; exit 1 on errors. `--deadlines` lists each household's deadline (first keyframe that covers its node − `deadline_margin_s`).

Household ids come from **your** `data/town.json`; validate against the same town the engine runs on.

## Checking a state snapshot
```bash
uv run --project engine ember validate-state contracts/fixtures/state.fixture.json --scenario contracts/fixtures/scenario.fixture.json
```
Schema (state + embedded assignment/report) then references: closed edges, households, facilities, resources and assignment ids all exist and agree with each other and with the scenario. Soham: run it on your `GET /state` output.

The state fixture is simulator output (D32): the example planner's plan run through the plan simulator to 80 min, then snapshotted. `plan.planner = "example"` until the allocator lands; `synthetic[]` lists what's illustrative. Any time: `uv run --project engine ember simulate --scenario <scenario.json> --state-at <t_s>` writes `data/state.json`.

## Vehicle states (`trajectories.trips[].final`, engine snapshots)
`0 waiting · 1 moving · 2 queued · 3 exited · 4 exposed · 5 stuck`

## Changing a contract
Bump `version`, regenerate the fixture (`cd engine && uv run ember fixtures`), add a line to `docs/DECISIONS.md`, tell the team.
`cd engine && uv run pytest -q` validates every fixture against its schema.
