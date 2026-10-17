# Ember

A city-scale disaster simulation around Harvard's Allston campus: real roads, real buildings, thousands of households, hazards that close roads over time, and a planner that turns the city's plan into a message for every household.

HackHarvard 2026 (Oct 16–18). Submissions due Sunday 8:00 AM on Devpost.

## Layout

```
contracts/   JSON schemas + fixtures. The interface between engine, residents and web. Frozen; bump the version to change.
engine/      Python. Builds the world from OpenStreetMap, runs the tick simulation, hazards, engines, job runner (Daytona).
residents/   Python (FastAPI). Household state, Photon 2.0 threads, need extraction, assignments.
web/         TypeScript. deck.gl + MapLibre map, live WebSocket, panels.
docs/        Plan, decision log, sim-env plan, research notes.
data/        Generated artifacts (gitignored). `uv run ember build` regenerates them.
```

## Quickstart (engine)

```bash
cd engine
uv sync
uv run ember build            # OSM → data/town.json (needs network, ~1–2 min first time)
uv run ember smoke            # runs a hazard + traffic sim for 1 simulated hour, prints metrics
uv run ember render           # data/town.png with roads, households, assets, venue, hazard
```

See `docs/SIM_ENV_PLAN.md` for how the simulated environment is built and `docs/DECISIONS.md` for every decision taken so far.
