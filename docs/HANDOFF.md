# HANDOFF — read this first in a fresh session

Last updated: 2026-10-16, Friday evening (hacking started ~4 PM; venue closes 8 PM nightly; submissions due **Sunday 8:00 AM** on Devpost).

## Where things stand
- Repo: `soham-k-sinha/Ember` (public, we have WRITE). Local clone at `~/Ember`, branch **`aryaman/sim-env`**. `main` is empty.
- Scaffold written and committed: `CLAUDE.md`, `README.md`, `docs/` (plan, decision log, sim-env plan, Physical Realities notes), `engine/` package, `.gitignore`.
- Python env: `engine/.venv` via `uv` (Python 3.12 pinned in `.python-version`). Deps installed. **The package itself may not be installed in the venv yet**: run `cd engine && uv sync --extra dev` (re-run after adding files).
- **Nothing in `engine/` has been executed yet.** `ember build`, `smoke`, `render`, `gate-a` are untested code. Expect small API mismatches (osmnx 2.x names, pandas NaN handling, shapely `contains_xy` reduceat) and fix them in place.
- `contracts/` is still empty (schemas + fixtures are TODO; `ember fixtures` writes fixture files once `build` + `smoke` work).
- `web/` and `residents/` are empty placeholders.
- The Physical Realities research agent is done; notes are in `docs/PHYSICAL_REALITIES_NOTES.md`.

## Immediate next steps, in order (sim-env must work first)
1. `cd engine && uv sync --extra dev && uv run python -c "import ember_engine.cli"`.
2. `uv run ember build --dist 1200` → `data/town.json`. Verify counts printed: expect roughly 1–3k drive edges, 5k–20k households, ≥ 5 assets, ≥ 6 exits, and the venue geocoded near Western Ave / N Harvard St, Allston (lat ~42.364, lon ~-71.124). If the geocoder lands somewhere wrong, set `VENUE_FALLBACK_LATLON` in `build_town.py` and re-run.
3. `uv run ember render --plain` → `data/town.png`. Open it (Read tool) and check: roads, households colored by zone, assets labeled, the venue star, exits as triangles on the boundary.
4. `uv run ember smoke --T 3600` → metrics + `data/trajectories.json`. Expect vehicles exiting, some exposed, wall time < 10 s. If slow, profile the transfer loop first.
5. `uv run ember render` (uses the last smoke state) → closed edges red, occupancy colored, hazard ellipse drawn.
6. `uv run ember gate-a` → **Gate A**: rotating the hazard heading by 90° must change the first closures. If it doesn't, the engine/hazard is wrong; fix before any UI.
7. `uv run ember fixtures` → `contracts/fixtures/*.json`. Then write `contracts/*.schema.json` matching them (town, plan, job, metrics, trajectories) and a `contracts/README.md`.
8. Commit on `aryaman/sim-env`, push, tell the team the fixtures exist so `web/` and `residents/` can start.
9. Hand-curate `exits` to the real ones (Charles River bridges, Western Ave, N Harvard St, Soldiers Field Rd, Cambridge St) in `build_town.py` once the map is visible.

## After the sim-env works (Saturday)
- Daytona: snapshot with `data/town.json` + `ember_engine` baked in; pool of N sandboxes; `run_job` over a job list (see plan §6.5 for the verified API and tier limits; get Tier 2 with a card + $25).
- `web/`: Vite + React + deck.gl 9.4 + `react-map-gl/maplibre`; render `town.fixture.json` and `trajectories.fixture.json` (TripsLayer, `t` = seconds since start).
- `residents/`: Photon 2.0 **Beta** (`api.photon.codes/v1`, Python client `photonhq-api`, $100 free credit; the `HACKWITHPHOTON` code is for the *original* Spectrum API, keep as fallback only). Testers must text the assigned number first.
- Decide the demo hazard/engine variant (flood vs fire vs crowd; evacuation vs Lifeline allocation) and log it in `docs/DECISIONS.md`.

## Gotchas already known
- Daytona Tier 1/2 sandboxes have no internet egress; results come back as `run_code` return values. `process.exec` default timeout is 10 s; always pass `timeout=`.
- deck.gl TripsLayer timestamps must be float32-safe → seconds since sim start (already the contract).
- OSM `lanes`/`maxspeed` missing on many edges; the builder imputes and labels it.
- Photon shared iMessage lines: no group chats, no calls; voice needs a bought SMS number + SIP vendor.
- Don't add 3D, LLM personas, or multi-agent orchestration. See `CLAUDE.md` hard rules.

## Team (updated Fri night)
Four people, one directory each; the idea is locked (DECISIONS D17). The execution plan is `docs/TECHNICAL.md`; each person's brief is `docs/team/<name>.md` (aryaman, soham, arnav, anshuman); feature logs are `docs/log/<name>.md`. Start every session by reading the logs and the decision log.
