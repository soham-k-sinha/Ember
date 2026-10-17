# HANDOFF — read this first in a fresh session

Last updated: **Sat 2026-10-17, evening** (after the end-to-end integration pass). Submission: **Sunday 8:00 AM** on Devpost.
Then read: `CLAUDE.md`, `docs/DECISIONS.md` (D1–D60), all of `docs/log/*.md`, `docs/TECHNICAL.md` (the plan), `residents/HANDOFF.md` (backend detail).

## The product in one breath
A Charles River flood around the David Rubenstein Treehouse. EMBER keeps one shared picture (water, roads, 40 households that need help, a hospital, a sewage pumping station, vans, generators), plans who goes where with a simulator-scored allocator, replans in ~0.7 s when a person texts a fact (Photon iMessage → one LLM extraction → report), and shows it on a map. It beats an incident-by-incident baseline on people reached and on untreated sewage overflow (m³), and stress-tests plans on Daytona.

## What's on `main` (integrated and tested end to end)
| Part | Owner | State |
|---|---|---|
| Engine (`engine/`): town, flood, facility/wastewater/vehicle models, plan simulator (shared trips, D59), allocator + replans (declines are constraints, confirmed jobs keep queue order, nearest drop-off, generator re-targeting with stated trade-offs; D58), baseline, compare, Daytona robustness, `EngineSession` | Aryaman | 95 tests. Daytona snapshot `ember-engine-9634de9e37`. |
| Contracts (`contracts/`): town, scenario, state v0.2, assignment, report, comparison, ws-events + fixtures | Aryaman | Every fixture validates in pytest. |
| Scenario (`scenarios/allston_flood_v1/`) | Aryaman (D49) | Tuned for the demo beats. |
| Backend (`residents/`): SQLite state, HTTP + WS, Photon threads, LLM extraction, outbound texts, confirm/reject, `/optimize` on Daytona, `/simulate`, `/ask`, questions queue (D60), text-driven drill (D56) | Soham | 198 tests. |
| Website (`web/`) on main: map + panels, Fixtures/Live, live KPIs, Optimize button, scatter, live comparison | Aryaman | Works live against the backend (checked in the browser). |
| **End-to-end check** `engine/scripts/e2e.py` | Aryaman | **62/62** against a live backend (v1, judge beat, confirm/decline, hospital beat, comparison, simulate, Daytona optimize, texting endpoints, clock to 240 min, every state contract-valid). |

**Not on main yet:** the 2.5D/3D website from the "web street-level" session (branch `aryaman/web-street-level` in worktree `.claude/worktrees/web-street-level`, not pushed). When it merges: re-run `e2e.py` (backend side is unchanged) and the browser checks in `docs/QA.md`.

## Run the whole thing locally
```bash
# backend (engine mode on allston_flood_v1, phones off; Daytona if engine/.env has a key)
cd residents && RESET_ON_START=1 PHOTON_ENABLED=0 uv run uvicorn residents.app:app --port 8000
# website → http://localhost:43123, press "Live"
cd web && npm install && VITE_API_BASE=http://127.0.0.1:8000 npm run dev
# end-to-end check (all checks must pass)
cd residents && uv run python ../engine/scripts/e2e.py
```
Demo beats by hand: `docs/DEMO.md` § Replay. Every step with expected values: `docs/QA.md`.

## Measured (after D58/D59)
- Plan v1: 78 reached before deadline, 9 not, 0 m³, 51 vehicle-km, 14 shared pickups, all drop-offs at the Treehouse.
- Judge at 5 min: Accessible Van 3, pickup 130 vs deadline 165 min; Generator 1 re-routed, ETA 14 → 25 min.
- Comparison after the judge beat (5 seeds): EMBER 89 vs baseline 52.6 reached (+36.4), overflow 0 vs 5,244 m³, EMBER +27 vehicle-km.
- Hospital at 15 min ("on backup, 10 min left"): Generator 1 → Mount Auburn, outage 13 min, overflow 0 → 9,600 m³ (stated with simulated numbers).
- `/optimize` from the backend: Daytona, 8 sandboxes, ~10 s; chooses c02 over c00 (worst-20% unreached 16.8 vs 29).

## Open, in order
1. Merge the 2.5D website branch, re-run `e2e.py` + QA browser rows. If it uses Google 3D tiles: a DECISIONS line amending D50 (no 3D models), key in `.env`, Google attribution, flat CARTO fallback.
2. Real-phone run on the machine with **both** `engine/.env` (Daytona) and `residents/.env` (Photon + Anthropic): `e2e.py`, then `docs/QA.md` with the two opted-in phones.
3. Soham: commit the `residents/uv.lock` refresh (`uv sync` picks up the engine's new `daytona` dependency).
4. Tier 2 Daytona → `EMBER_DAYTONA_WORKERS≈90`.
5. Run-through ×3, then Devpost (≥900 words, ≥8 screenshots, video < 3 min), README, ASUS post. Decide voice (Soham's `residents/VOICE_PLAN.md`) and the name.
6. Engine, low priority: planner-side shared-trip estimate in `construct` (today the simulator and local search find shared trips); hand-curated exits; walk network.

## Gotchas learned the hard way
- **Decision numbers collide**: check main *and* open PRs before taking a number (D58 was taken because open PRs held D55–D57).
- **Merges:** rebase-merge for linear branches. Never chain "delete branch" after `gh pr merge`; check `state == MERGED`.
- **Ownership CI** fails a PR that touches another lane (e.g. `residents/uv.lock`); keep such files out and ask the owner.
- **Daytona in the backend:** the backend imports the engine, so engine dependencies must be core, not extras (the SDK was missing and `/optimize` silently ran locally until #43). A fallback now records `search.robust.fallback_reason`.
- After changing any module a sandbox imports (sim, models, allocator search/context, world, scenario, daytona/jobs): `cd engine && uv run ember daytona-snapshot` (~70 s).
- zsh mangles `$B:path`; use `${B}:path` or quote the ref in `git show`.
- Tests that hit `/optimize` must set `EMBER_LOCAL_POOL=1`.

## Opening prompt for a new session
```
Read CLAUDE.md, docs/HANDOFF.md, docs/DECISIONS.md and all of docs/log/*.md. I'm Aryaman; I own engine/, contracts/, web/, scenarios/ and the demo/QA/Devpost docs (D49); Soham owns residents/. Pull main, check open PRs and what changed since HANDOFF's timestamp, then continue with HANDOFF "Open, in order". Rebase before every push, open a PR, check decision numbers (main and open PRs), append to docs/log/aryaman.md after each feature, and re-run engine/scripts/e2e.py after every merge.
```
