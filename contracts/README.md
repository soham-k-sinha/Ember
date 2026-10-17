# contracts/

The interface between `engine/`, `web/` and `residents/`. Build against the fixtures; nobody blocks on anybody.

| Contract | Schema | Fixture | Produced by | Consumed by |
|---|---|---|---|---|
| Town (roads, footways, households, assets, exits, zones, venue) | `town.schema.json` | `fixtures/town.fixture.json` (a ~150-edge slice) | `ember build` → `data/town.json` | engine, web (map), residents (households → phones) |
| Plan (what the planner controls) | `plan.schema.json` | `fixtures/plan.fixture.json` | planner / web | engine (`run_job`) |
| Job = plan + scenario (hazard, compliance, seed, horizon) | `job.schema.json` | `fixtures/job.fixture.json` | planner / Daytona fan-out | engine (`run_job`) |
| Metrics (one run's outcome) | `metrics.schema.json` | `fixtures/metrics.fixture.json` | `run_job` (return value; Daytona returns it as `run_code` output) | web (scatter / comparison), residents |
| Trajectories (sampled vehicles for TripsLayer) | `trajectories.schema.json` | `fixtures/trajectories.fixture.json` (200 trips) | `ember smoke` → `data/trajectories.json` | web (deck.gl `TripsLayer`) |

## Conventions (same as CLAUDE.md)
- Coordinates are `[lon, lat]` (GeoJSON order) everywhere. Separate `lon`/`lat` fields where an object is a point.
- Time is `t_s`: seconds since simulation start (float32-safe for deck.gl). No wall-clock timestamps in the sim.
- Distances in meters, speeds in m/s inside the engine (`speed_kph` only on town edges, as OSM gives it).
- Node and edge references: `edges[].u/v`, `households[].node`, `exits[]`, `venue.node` are **OSM node ids**. `edges[].id` is a dense `0..E-1` index; closures (`metrics.closure_order`, `plan.closed_edges`) use it.
- Edges are directed; a two-way street is two edges.
- Anything listed in `town.meta.synthetic` is generated (household counts, vehicles, flags, imputed lanes, capacities, exits). Say so in the UI.

## Vehicle states (`trajectories.trips[].final`, engine snapshots)
`0 waiting · 1 moving · 2 queued · 3 exited · 4 exposed · 5 stuck`

## Changing a contract
Bump `version`, regenerate the fixture (`cd engine && uv run ember fixtures`), add a line to `docs/DECISIONS.md`, tell the team.
`cd engine && uv run pytest -q` validates every fixture against its schema.
