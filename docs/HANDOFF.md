# HANDOFF — read this first in a fresh session

Last updated: **Sun 2026-10-18, early morning** (integration merged to `main` at aaf3a31; docs fix round D88). Submission: **Sunday 8:00 AM** on Devpost.
Then read: `README.md` (judge landing page), `CLAUDE.md`, `docs/DECISIONS.md`, all of `docs/log/*.md`, `docs/TECHNICAL.md` (the plan), `residents/README.md` (backend, API, drill, calls).

## The product in one breath
**Flood response is our first demonstration. Adaptive coordination is the product** (D63). People report by text or phone call over Photon → the AI turns each message into a structured fact → a simulator-scored planner replans in ~0.7 s → everyone gets a personal instruction (worded by the AI, decided by the planner, D76), on a live map. Demonstrated on a Charles River flood around the David Rubenstein Treehouse with **two incident types on one engine** (D64): household rescue (the judge) and critical-infrastructure power loss (Mount Auburn Hospital, Cottage Farm sewage station). It beats an incident-by-incident baseline on people reached and on untreated sewage overflow (the real 2024 Cottage Farm storm released ≈80,700 m³), and stress-tests plans on Daytona.

**Line against plan-once tools:** "Forecasts are wrong by minute 10; EMBER keeps the plan right once real people start texting." Closest rival: LANDFALL (`ezou1/hh26-landfall`), a Hurricane Ian replay that plans once with no people in the loop.

## What's on `main`
All five build branches, merged and checked together (D78–D84). Aryaman is sole owner (D77). CI (`.github/workflows/ci.yml`) runs the engine and residents tests and the web build on every push to `main` and every PR.
| Part | State |
|---|---|
| Engine (`engine/`): town, flood, models, plan simulator, allocator + replans, baseline, compare, Daytona robustness, `EngineSession` | 103 tests, ruff clean. Snapshot **`ember-engine-87ccf09179`**. Warm 90-sandbox pool in the backend, chunked jobs, compressed batch setup retried on dropped connections (D82, D84); distinct candidates, forecast-best kept unless the robust pick saves ≥ 1 person (D86). |
| Backend (`residents/`): SQLite state, HTTP + WS, Photon threads, extraction + reply writer + keyword fallback (D75–D76), calls via ElevenLabs with EMBER calling the most at-risk first (D74, D80), multiplayer join (D78), `GET /playback` (D79), simulator-graded eval and Chalk seam (D83) | 279 tests. |
| Website (`web/`): judge-facing shell (D81): score card vs baseline, Feed / Plan / Proof, plan-diff toasts, Daytona proof, QR join card + roster, player pins and on-call ring, live replay | `tsc` + build pass; main chunk 2.94 MB (480 KB gzip), flat map lazy. |
| **End-to-end** `engine/scripts/e2e.py` | **71/71** against a live backend with real Daytona: every beat, playback in both modes, `/calls` shape, 250 runs streamed, three `JOIN EMBER` phones → Players 1–3 on distinct flood-zone households with one replan, a 4th refused over `MAX_PLAYERS`. |

## Run the whole thing locally
```bash
# backend (engine mode on allston_flood_v1). Keys in residents/.env (Photon, Anthropic, ElevenLabs) and engine/.env (Daytona, EMBER_DAYTONA_WORKERS=90)
cd residents && RESET_ON_START=1 PHOTON_ENABLED=1 JOIN_NUMBER=+1… MAX_PLAYERS=30 VOICE_MAX_CONCURRENT=2 \
    uv run uvicorn residents.app:app --port 8000
# website → http://localhost:43123/?live (the QR needs the same SMS number as JOIN_NUMBER)
cd web && npm install && VITE_API_BASE=http://127.0.0.1:8000 VITE_JOIN_NUMBER=+1… npm run dev
# end-to-end check, no phones/LLM/calls (command with the empty-key overrides in e2e.py's docstring; Daytona is real)
cd residents && uv run python ../engine/scripts/e2e.py
# six calls end to end (mocked ElevenLabs, keyword parser) · the text → fact eval graded by the simulator
cd residents && uv run python scripts/sim_calls.py && uv run python scripts/eval_sim.py
```
`VOICE_MAX_CONCURRENT=0` stops EMBER from calling first. Demo beats: `docs/DEMO.md`; every step with expected values: `docs/QA.md`.

## Measured (integration run, 2026-10-17 night; re-measure after the fix round)
- Plan v1: 78 reached before deadline, 9 not, 0 m³, 46 vehicle-km. Judge need → v2 in 0.66 s, Accessible Van 3; River St closed → Generator 1 ETA 14 → 25 min.
- Comparison (5 seeds, after the judge beat): EMBER 88.6 vs baseline 51.6 reached (+37.0); hospital outage 11 vs 28 min.
- Hospital at 15 min: Generator 1 → Mount Auburn, outage 13 min, overflow 0 → 9,600 m³ (stated). End of horizon: 37/40 households safe.
- `/optimize` on the warm pool, 90 sandboxes: 250 runs 2.2–2.9 s fan-out (3.2–3.4 s wall), 1,000 runs 2.7 s (3.7 s wall). At 15:00 it keeps c00 (worst-20 % unreached 15.7 vs baseline 55.2); at 0:00 it picks c03. Before D84 the same pool shrank 90 → 80 → 51 → 40 sandboxes over three runs and took 4–8 s.
- Laptop vs Daytona (D86, `ember robust` at 0:00, 4 candidates + baseline, fan-out wall, identical results; laptop = 8 processes, load ≈ 10; Daytona = 90 warm sandboxes, 7–12 s startup not counted):

  | worlds | laptop | Daytona | speed-up |
  |---|---|---|---|
  | 250 | 2.3 s | 2.1 s | 1.1× |
  | 1,000 | 4.5 s | 2.6 s | 1.7× |
  | 5,000 | 13.7 s | 4.0 s | 3.4× |
  | 10,000 | 24.3 s | 5.3 s | 4.6× |

  At 250 worlds (the demo's 50 seeds) the laptop keeps up; Daytona is load-bearing from ~1,000 worlds. The backend caps `/optimize` at 200 seeds (1,000 worlds); 2,000 seeds = 10,000 worlds. Robust picks: 0:00 → c03 (worst-20 % unreached 12.0 vs forecast-best c00 27.8, baseline 42.7); 15:00 → keeps c00 (13.4; distinct alternatives 13.3 / 16.9 / 20.8; baseline 55.2).
- Three joins: placed in ~3 ms each, one shared replan (0.64 s). Playback ≈4 s on first call, then cached.
- `sim_calls.py`: 7 calls (Sam twice), 5 confirmed, 2 informed; every reply < 1 s. `eval_sim.py` (keyword parser): 46/51 pass, 4 asked, 1 fail (#32 "Welch's"), 98 % safe.

## Priorities, in order
1. Merge the fix-round branches; re-run `e2e.py` on main and re-measure every number in `docs/DEMO.md` and `README.md`.
2. **Run-through** with `docs/QA.md` on the machine with both `.env` files: one real `JOIN EMBER` text to the SMS number and one real call.
3. **Devpost** (≥900 words, ≥8 screenshots; outline in `docs/devpost/README.md`) + **video < 3 min**.
4. One paid run: `eval_sim.py --extractor llm` (the LLM column for Devpost/Chalk).

## Open issues
- **SMS campaign:** Photon sends on the SMS number need the line's campaign unless every recipient is in-network, so replies to players may fail (`delivery: failed`, retried) until one is attached (`PUT platforms/sms/lines/{id}/campaign`). Players still appear on the map and in the plan. Not verified live.
- **Chalk router unverified:** `CHALK_ROUTER_KEY` + `CHALK_ENV_ID` route both model calls through `api.chalk.ai/v1/router`; whether structured outputs and the beta header pass through is unknown (failure → keyword parser). One live call needed; `ANTHROPIC_API_KEY` still gates extraction.
- **LLM eval column not run** (`eval_sim.py --extractor llm`).
- ElevenLabs: the call-over status read (`GET /v1/convai/conversations/{id}`) and the agent's `first_message` setup are untested against the live API; a call that never reports done ends after `SESSION_IDLE_S` without the follow-up text.
- Daytona's `last_activity_at` ignores `run_code`, so another process's pool start (e.g. `ember robust`) deletes a warm pool idle > 3 min; the backend then restarts it (~7–12 s). Don't run `ember robust` while the demo backend is up.
- Web: the settings popover doesn't close on an outside click; real frame rate unmeasured on the demo machine.

## Gotchas learned the hard way
- After changing any module a sandbox imports (sim, models, allocator, world, scenario, daytona/jobs, docstrings included): `cd engine && uv run ember daytona-snapshot` (~75–100 s). Check with `uv run python -c "from ember_engine.daytona import pool; print(pool.snapshot_name())"`.
- The backend warms 90 sandboxes on every engine-mode start when `engine/.env` has a key; they're deleted on clean shutdown. 100-vCPU quota: a second pool gets ~10.
- Players (D78) survive resets: use a fresh `DB_PATH` for `e2e.py`, and `MAX_PLAYERS=3` to run its cap check.
- `uv sync` drops the engine's `dev` extra (pytest): use `uv sync --extra dev` in `engine/`. Tests that hit `/optimize` must set `EMBER_LOCAL_POOL=1`.
- Decision numbers collide across branches: check main and open branches before taking one.
- zsh mangles `$B:path`; use `${B}:path`.

## Opening prompt for a new session
```
Read CLAUDE.md, docs/HANDOFF.md, docs/DECISIONS.md and all of docs/log/*.md. I'm Aryaman, sole owner (D77). Pull main, check what changed since HANDOFF's timestamp, then continue with HANDOFF "Priorities, in order". Append to docs/log/aryaman.md after each feature, and re-run engine/scripts/e2e.py after every merge.
```
