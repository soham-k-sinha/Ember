# HANDOFF — read this first in a fresh session

Last updated: 2026-10-16, Friday 23:00 (hacking started ~4 PM; venue closes 8 PM nightly; submissions due **Sunday 8:00 AM** on Devpost).

## Where things stand (Fri 23:00)
- Repo: `soham-k-sinha/Ember`, branch **`aryaman/sim-env`** (pushed). `main` is still empty.
- **Sim-env works end to end** on the real town around the Treehouse (venue pinned to its OSM footprint, 20 Western Ave; see D13):
  - `ember build --no-walk` → `data/town.json`: 586 nodes, 1,196 drive edges, 17,810 households (10,187 vehicles), 11 assets, 19 exits, 10 zones. Re-runs are instant (layers cached in `engine/cache/layers/`).
  - `ember smoke --T 3600` → 0.33 s wall for 360 ticks. Heading 90°: 7,312 exited, 915 exposed, 1,817 trapped (every route cut before they left). No hazard: 10,183/10,187 out, 95% clearance 3,080 s, 0 stuck.
  - `ember render` → `data/town.png` with venue star, assets, exits, hazard ellipse, closed edges red, occupancy colored.
  - `ember gate-a` → **PASS**. 90° first closes the River St exit at 1,200 s; 180° first closes Gardner Terrace at 1,800 s; closure orders differ.
  - `uv run pytest -q` → 12 pass (7 engine tests on a synthetic grid + 5 fixture-vs-schema checks).
- **Shared world (D29):** `engine/data/town.json.gz` is the team's town. Any `ember` command unpacks it to `data/town.json` if missing; nobody needs to run `ember build`. To change the world: `ember build` → `ember pin-town` → `ember fixtures` → commit.
- `contracts/`: 5 schemas + fixtures + README are committed. **web/ and residents/ can start.**
- Known gaps:
  - **Walk network** (`paths`) is empty: Overpass timed out. Run `uv run ember build` (without `--no-walk`) when Overpass is healthy.
  - **Assets** came from the cache fallback (D26). Rebuild once Overpass answers to get the live query.
  - The venv is Python 3.13 (the pin says 3.12); everything works on 3.13.

## Immediate next steps, in order
1. **Hand-curate exits** (`build_town.py`). Several current exits are residential side streets that just cross the box edge (Gardner Terrace, President Terrace). Replace them with the real ones: Charles River bridges (River St, Western Ave, Anderson/JFK, Eliot), Soldiers Field Rd / Storrow both ways, Memorial Dr both ways, Mass Pike ramps, Cambridge St, N Harvard St, Mass Ave. Then re-run smoke + gate-a + fixtures.
2. Rebuild with walk network + live assets when Overpass recovers: `rm engine/cache/layers/assets_*; uv run ember build`.
3. Then the coordination layer per **`docs/team/aryaman.md`** (flood is locked, D17). Task 1 (`scenario.schema.json` + `ember validate-scenario`) is **done** (D28). Task 2 (`state.schema.json` + `assignment` + `report` + fixture + `ember validate-state`) is **done** (D30). Tasks 3–5 (deadlines, models, plan simulator) are **done** (D31, D32): `uv run ember simulate --scenario <path> [--plan example|plan.json] [--report r.json] [--state-at t]`. Tasks 6–8 (baseline, allocator, compare) are **done** (D33–D35): `ember allocate | replan | compare --scenario …`; `ember simulate --plan ember|baseline|example`. On allston_flood_v1: EMBER reaches 87 people before deadline (0 unreached) vs baseline 31; over 5 perturbed seeds +55 people, −21 min critical-service outage, +81 vehicle-km. Task 9 (robustness fan-out) is **done** for local processes and coded + wire-tested for Daytona (D39): `uv run ember robust --scenario <path> [--pool auto|local|daytona] --points-out points.jsonl`. **Daytona is live on Tier 1** (key in engine/.env, snapshot `ember-engine-1b735d7199`, 8 sandboxes, 100 runs ≈ 30 s). **Backend bridge:** `ember_engine.api.EngineSession` + seed `engine/data/allston_flood_v1.seed_state.json` (D42). **To run on Daytona elsewhere:** put `DAYTONA_API_KEY` in `engine/.env` (see `.env.example`), `uv sync --extra daytona`, `uv run ember daytona-snapshot` once (rebuilds when engine code or town changes), then `ember robust`. Get Tier 2 (card + $25) for ~100 sandboxes. Next: scenario tuning with Anshuman (judge loop, overflow), then perf/edge cases.
4. Trajectories are sampled every 60 s (`snapshot_every=6`), so TripsLayer cuts corners. Use `snapshot_every=1` for the demo file if it looks bad.

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
