# HANDOFF — read this first in a fresh session

Last updated: **Sat 2026-10-17, ~4:30 PM**. Submission: **Sunday 8:00 AM** on Devpost. Venue closes 8 PM nightly.
Then read: `CLAUDE.md`, `docs/DECISIONS.md` (D1–D49), all of `docs/log/*.md`, `docs/TECHNICAL.md` (the plan).

## The product in one breath
A Charles River flood around the David Rubenstein Treehouse. EMBER keeps one shared picture (water, roads, 40 households that need help, a hospital, a sewage pumping station, vans, generators), plans who goes where with a simulator-scored allocator, replans in ~0.5 s when a person texts a fact (Photon iMessage → one LLM extraction → report), and shows it on a map. It beats an incident-by-incident baseline on people reached and on untreated sewage overflow (m³), and stress-tests plans on Daytona.

## What's on `main` (all of it works)
| Part | Owner | State |
|---|---|---|
| Engine (`engine/`): OSM town, flood hazard, facility/wastewater/vehicle models, plan simulator, baseline, allocator + replans, compare, Daytona robustness, `EngineSession` bridge | Aryaman | Done. 83 tests. |
| Contracts (`contracts/`): town, scenario, state v0.2, assignment, report, comparison, ws-events + fixtures | Aryaman | Done; every fixture validates in pytest. |
| Scenario (`scenarios/allston_flood_v1/`) | Anshuman → **Aryaman (D49)** | Done; tuned for both demo beats (D47). |
| Backend (`residents/`): SQLite state, HTTP + WS API, Photon threads (live, 2 phones opted in), LLM extraction, outbound texts, confirm/reject, `/optimize` | Soham | Done; 112 tests. |
| Website (`web/`): deck.gl map + panels, Fixtures/Live, WS client | Arnav → **Aryaman (D49)** | Merged (#21); works live against the backend. |

**Lanes (D49):** Aryaman covers `engine/`, `contracts/`, `web/`, `scenarios/`, `docs/DEMO.md`, `docs/QA.md`, `docs/devpost/`. Soham: `residents/`. Arnav's and Anshuman's lanes still work if they come back; Arnav was active Sat afternoon (ask before editing `web/` under him).

## Run the whole thing locally
```bash
# backend (engine mode on allston_flood_v1, phones off, local pool)
cd residents && EMBER_LOCAL_POOL=1 RESET_ON_START=1 PHOTON_ENABLED=0 uv run uvicorn residents.app:app --port 8000
# website → http://localhost:43123, press "Live"
cd web && npm install && VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```
Demo the judge beat by hand (keep the clock early — see below):
```bash
curl -X POST localhost:8000/clock -H 'content-type: application/json' -d '{"t_s":300}'
curl -X POST localhost:8000/reports -H 'content-type: application/json' -d '{"source":"judge","kind":"need","household_id":10296,"payload":{"people":2,"mobility":true,"accessible_vehicle":true}}'
curl -X POST localhost:8000/disruption -H 'content-type: application/json' -d '{"close_edges":[523,833,952],"note":"River St blocked at Memorial Dr"}'
```
Engine-only: `cd engine && uv run ember allocate|compare|robust|simulate --scenario ../scenarios/allston_flood_v1/scenario.json`; `uv run pytest -q`.

## The demo beats (engine-verified, pinned by `engine/tests/test_demo_beats.py`)
1. **Sustainability:** baseline sends the generator only when Cottage Farm fails → **2,317 m³** untreated overflow; EMBER pre-positions it → **0 m³**. 5-seed compare: −2,165 m³, +50.6 people before deadline, −44 min critical-service outage, +75 vehicle-km (EMBER drives more; say so).
2. **Judge:** judge texts "2 of us, one in a wheelchair, River St is blocked" → plan v2 gives them Accessible Van 3 (pickup 132 min vs deadline 165) and plan v3 reroutes Generator 1 (ETA 14 → 32 min; rationale "route changed: road reported closed"). **The judge must reply within the first ~8 sim-minutes** (the generator passes their corner at ~12 min). Keep the sim clock slow until they reply.
3. **Infrastructure:** operator texts "only 10 minutes of backup left" → the generator moves to the hospital (outage 15 → 0 min; overflow 0 → 2,000 m³, stated in the rationale) — tested on the example scenario; re-check timing on allston before demoing it.
4. **Daytona:** `POST /optimize` → 100 runs (top-4 candidates + baseline × 20 perturbed worlds) stream as `scatter_point`; picks the best worst-20% plan (chose a different plan than the nominal best). Tier 1: 8 sandboxes, ~30 s.

## Daytona
- Key lives only in **`engine/.env` on Aryaman's laptop** (gitignored): `DAYTONA_API_KEY`, `DAYTONA_API_URL`, `EMBER_DAYTONA_WORKERS=8`. **Tier 2 tomorrow → set `EMBER_DAYTONA_WORKERS≈90`.**
- Snapshot `ember-engine-489b50f1ea` is built. After changing any module a sandbox imports (sim, models, allocator search/context, world, scenario, daytona/jobs), run `uv run ember daytona-snapshot` (~70 s). Until then `/optimize` runs locally and says so (D48) — it never builds mid-request.
- Tests that hit `/optimize` must set `EMBER_LOCAL_POOL=1` or they spin up real sandboxes.

## Open issues / next steps, in order
1. **Backend: broadcast `state` after a replan** (Soham, one line at the end of `planner._publish()`, like `set_clock` does). Today the map's closed roads and vehicle ETAs stay stale until a page reload after `/reports` or `/disruption`. Sent to Soham; verify it landed.
2. **`EngineSession(..., moves=)`** — Soham's request (his tests went 18 s → 56 s): pass an optional `moves` through to `allocate()`.
3. **`docs/DEMO.md`** (now Aryaman's): six beats with timings, who holds which phone (resident = judge household #10296, operator = Mount Auburn), the judge-timing rule, one line per sponsor (Daytona: parallel sandboxes, best worst-20%; Photon: two iMessage threads, context across plan versions; sustainability: overflow m³ inside the objective), fallbacks (`POST /dev/inbound` typed texts if Photon fails; local pool if Daytona fails).
4. **`docs/QA.md`**: every click/text in the demo, expected result, owner. Run it at the **8 PM** run-through.
5. **Devpost** (`docs/devpost/`): ≥900 words, ≥8 screenshots, video <3 min after the 8 PM run-through. Pull numbers from `ember compare` / `ember robust`; label synthetic values (`scenarios/allston_flood_v1/assumptions.md`).
6. Web polish: big empty area above the map; live comparison panel (`GET /comparison`) instead of the example fixture.
7. Low priority: hand-curate exits; walk network (`paths`) is empty (Overpass was down).

## Gotchas learned the hard way
- **Decision numbers collide** — Soham and Aryaman both append to `docs/DECISIONS.md`; re-check the last number right before committing and after every rebase.
- **Merges:** rebase-merge for linear branches, squash for branches with merge commits (Arnav's). **Never chain "delete branch" after `gh pr merge` in one command** — a failed merge once deleted a branch (recovered from reflog). Check `state == MERGED` first.
- The ownership CI check is advisory (no branch protection on `main`); D49 put Arnav's/Anshuman's paths in Aryaman's lane so his PRs pass.
- zsh mangles `$B:path` — use `${B}:path` or the literal ref in `git show`.
- Daytona sandboxes have no internet on Tier 1/2; results return via `run_code`; always pass `timeout=`.
- deck.gl TripsLayer needs float32-safe times (seconds since sim start, already the contract).

## Opening prompt for a new session
```
Read CLAUDE.md, docs/HANDOFF.md, docs/DECISIONS.md and all of docs/log/*.md. I'm Aryaman; I own engine/, contracts/, web/, scenarios/ and the demo/QA/Devpost docs (D49); Soham owns residents/. Pull main, check open PRs and what changed since HANDOFF's timestamp, then continue with HANDOFF "Open issues / next steps" in order. Rebase before every push, open a PR, check decision numbers, append to docs/log/aryaman.md after each feature.
```
