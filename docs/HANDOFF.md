# HANDOFF — read this first in a fresh session

Calls-first continuation (D100): see `docs/CALLS_FIRST_HANDOFF.md`. That branch adds proactive calls and clock-driven steps without required YES/DONE; the round-3 measurements below are the earlier main-branch integration.

Last updated: **Sun 2026-10-18, round 3** (backend D92, web D93 and the second hazard D94 merged and checked together on `aryaman/round3`, D95). Submission: **Sunday 8:00 AM** on Devpost.
Then read: `README.md` (judge landing page), `CLAUDE.md`, `docs/DECISIONS.md`, all of `docs/log/*.md`, `docs/TECHNICAL.md` (the plan), `residents/README.md` (backend, API, drill, calls).

## The product in one breath
**Flood response is our first demonstration. Adaptive coordination is the product** (D63). People report by text or phone call over Photon → the AI turns each message into a structured fact → a simulator-scored planner replans in ~0.7 s → everyone gets a personal instruction (worded by the AI, decided by the planner, D76), on a live map. Demonstrated on a Charles River flood around the David Rubenstein Treehouse with **two incident types on one engine** (D64): household rescue (the judge) and critical-infrastructure power loss (Mount Auburn Hospital, Cottage Farm sewage station). It beats an incident-by-incident baseline on people reached and on untreated sewage overflow (the real 2024 Cottage Farm storm released ≈80,700 m³), and stress-tests plans on Daytona.

**Line against plan-once tools:** "Forecasts are wrong by minute 10; EMBER keeps the plan right once real people start texting." Closest rival: LANDFALL (`ezou1/hh26-landfall`), a Hurricane Ian replay that plans once with no people in the loop.

## What's on `main`
All five build branches, merged and checked together (D78–D84), then the fix round (D85–D88), the register-then-text join (D89), the call-back fallback (D90), Chalk (D91) and round 3: one sewage number, calls that say they're automated, join hardening, urgent texts, pool owner labels (D92), the Daytona stress test, pre-season verdict and reporter-first plan diffs in the web (D93), a second hazard and an overflow-separating robust sampler (D94), integrated in D95. Aryaman is sole owner (D77). CI (`.github/workflows/ci.yml`) runs the engine and residents tests, ruff on both, and the web build on every push to `main` and every PR.
| Part | State |
|---|---|
| Engine (`engine/`): town, flood, models, plan simulator, allocator + replans, baseline, compare, Daytona robustness, `EngineSession`, a second scenario (`allston_plume_v1`, ellipse hazard, D94) | 106 tests, ruff clean. Snapshot **`ember-engine-d9ea4508c1`**. Warm 90-sandbox pool in the backend, chunked jobs, compressed batch setup retried on dropped connections (D82, D84), owner-labelled so two backends can't sweep each other (D92); distinct candidates, forecast-best kept unless the robust pick saves ≥ 1 person (D86). |
| Backend (`residents/`): SQLite state, HTTP + WS, Photon threads, extraction + reply writer + keyword fallback (D75–D76), calls via ElevenLabs with EMBER calling the most at-risk first and calling back undelivered texts (D74, D80, D90), multiplayer join by `POST /join` then a text (D89; every seat counted, stale seats released, iPhone-only `note`, D92), urgent texts → immediate replan (D92), `plan.search.kept_before_tradeoff_m3` (D92), `GET /playback` (D79), simulator-graded eval through Chalk (D83, D91) | 301 tests, ruff clean. |
| Website (`web/`): judge-facing shell (D81): score card vs baseline (sewage kept out read from the plan), Feed / Plan / Proof, a latest-change strip that leads with the reporter's own outcome, Proof with Pre-season stress test / Optimize, Stress test 10,000 worlds and a throughput tile (D93), join card (number → `POST /join` → QR → "Player N joined") + roster, player pins and on-call ring, live replay | `tsc` + build pass; main chunk 2.94 MB (480 KB gzip), flat map lazy. |
| **End-to-end** `engine/scripts/e2e.py --big` | **83/83** against a live backend with real Daytona: the plume scenario validates, every beat, `kept_before_tradeoff_m3` at v1 and frozen through the hospital trade, playback in both modes, `/calls` shape, 250 and 10,000 runs streamed, three phones `POST /join` (idempotent) (each answer says iPhone (iMessage) only) then text `JOIN EMBER` → Players 1–3 on distinct flood-zone households with one replan, an unregistered text refused, a 4th `/join` → 409 over `MAX_PLAYERS`. |

## Run the whole thing locally
```bash
# backend (engine mode on allston_flood_v1). Keys in residents/.env (Photon, Anthropic, ElevenLabs) and engine/.env (Daytona, EMBER_DAYTONA_WORKERS=90)
cd residents && RESET_ON_START=1 PHOTON_ENABLED=1 MAX_PLAYERS=25 VOICE_MAX_CONCURRENT=2 \
    uv run uvicorn residents.app:app --port 8000
# website → http://localhost:43123/?live (the join card asks for a number, POST /join returns the iMessage line for the QR)
cd web && npm install && VITE_API_BASE=http://127.0.0.1:8000 npm run dev
# end-to-end check, no phones/LLM/calls (command with the empty-key overrides in e2e.py's docstring; Daytona is real)
cd residents && uv run python ../engine/scripts/e2e.py
# six calls end to end (mocked ElevenLabs, keyword parser) · the text → fact eval graded by the simulator
cd residents && uv run python scripts/sim_calls.py && uv run python scripts/eval_sim.py
```
`VOICE_MAX_CONCURRENT=0` stops EMBER from calling first. Demo beats: `docs/DEMO.md`; every step with expected values: `docs/QA.md`.

## Measured (round 3 on `aryaman/round3`, 2026-10-18, keyless backend on :8050 with real Daytona, e2e 83/83)
- Plan v1: 78 reached before deadline (baseline 58), 9 not, 0 m³ (baseline 2,317, so `kept_before_tradeoff_m3` 2,316.7), 46 vehicle-km.
- DEMO order (pre-season stress test first, fresh DB, `MAX_PLAYERS=25`): `?seeds=2000` at 0:00 = 10,000 runs on 90 sandboxes, 3.2–4.0 s fan-out (4.8–8.1 s wall), publishes c03 (worst-20 % unreached 15.74; c02 20.71, c01 22.2, forecast-best c00 30.34; baseline 40.84; overflow 404 vs 8,453 m³), still 78 reached on the forecast. Then judge need at 5:00 → planner 0.63–0.89 s (0.74–1.04 s HTTP), Accessible Van 3 at 100 min (deadline 165), reached 80; River St closed → 0.69–0.91 s, Van 3 at 85 min, Generator 1 ETA 14 → 25 min, kept 5,166.7 m³. Hospital at 15:00 → 0.69–0.87 s, Generator 1 → Mount Auburn (on site in 8 min), outage 13 min, overflow 0 → 9,600 m³ (stated), kept stays 5,166.7. A join (`/join` + `JOIN EMBER`) → one replan (0.78–0.87 s); the judge's "the water is at our door, please hurry" → trigger "Judge: urgent, asked us to hurry", a replan in 0.84–0.89 s. The pre-season pick leaves the judge and hospital beats unchanged.
- e2e order (optimize at 15:00, after the beats): 250 runs 1.8 s fan-out (5.1 s wall), picks c04 (18.7; c06 21.1, c00 21.4, c02 22.3; baseline 54.8); 10,000 runs 4.9 s fan-out (7.5 s wall), all streamed, keeps c00 (c01 18.23, c00 18.45; baseline 53.42). End of horizon: 37/40 households safe, outage 13 min.
- At 0:00 on 250 worlds (50 seeds): c03 14.6 vs c00 33.7 (baseline 38.4), 2.1 s fan-out. The backend's run has no `c00-trip` row (see Open issues).
- Comparison (5 seeds, after the hospital beat): EMBER 88.6 vs baseline 51.6 reached (+37.0); hospital outage 11 vs 28 min; EMBER +31 vehicle-km.
- Laptop vs Daytona (D86, `ember robust` at 0:00, 4 candidates + baseline, fan-out wall, identical results; laptop = 8 processes, load ≈ 10; Daytona = 90 warm sandboxes, 7–12 s startup not counted):

  | worlds | laptop | Daytona | speed-up |
  |---|---|---|---|
  | 250 | 2.3 s | 2.1 s | 1.1× |
  | 1,000 | 4.5 s | 2.6 s | 1.7× |
  | 5,000 | 13.7 s | 4.0 s | 3.4× |
  | 10,000 | 24.3 s | 5.3 s | 4.6× |

  At 250 worlds (the demo's 50 seeds) the laptop keeps up; Daytona is load-bearing from ~1,000 worlds. The backend allows `/optimize` up to 2,000 seeds (10,000 worlds). Robust picks (D94 sampler): 0:00 → c03 (worst-20 % unreached 14.6 vs forecast-best c00 33.7, baseline 38.4; c00 with Generator 1 sent at the grid trip: same people, 3,995 vs 77 m³ overflow); 15:00 → c04 over c00 (18.7 vs 21.4; baseline 54.8).
- Three joins (`POST /join` ×3, then each texts): one shared replan. Playback ≈4 s on first call, then cached.
- `sim_calls.py`: 7 calls (Sam twice), 5 confirmed, 2 informed; every reply < 1 s. `eval_sim.py` (keyword parser): 46/51 pass, 4 asked, 1 fail (#32 "Welch's"), 98 % safe.

## Priorities, in order
1. **Run-through** with `docs/QA.md` on the machine with both `.env` files: one real phone through the join card (`POST /join`, then `JOIN EMBER` to the shared iMessage line) and one real call.
2. Screenshots into `docs/img/`; each teammate writes their "Lesson:" line in `docs/devpost/README.md`.
3. **Devpost** (≥900 words, ≥8 screenshots; outline in `docs/devpost/README.md`) + **video < 3 min**.
4. One paid run: `eval_sim.py --extractor llm` through Chalk again, now that extraction has the `urgent` kind (D91 measured 50/51 before it).

## Open issues
- **The backend's pre-season run has no `c00-trip` row:** `staged_at_trip` only delays generators dispatched by the new version (`plan_version == s.version`), and in the backend the t = 0 generator comes from plan v1, so the "sent at the grid trip" overflow line (3,995 vs 77 m³) appears only in `ember robust` (no previous plan). Docs cite it as an `ember robust` number.
- **Photon seat release (D92)** uses `DELETE /platforms/imessage/assignments/{id}` from Photon's openapi.json, tested only against the fake; seats are released only on the next join, so the roster can show a stale "waiting for text" player until then. No per-IP rate limit on `/join`.
- **Real-model eval predates `urgent`:** the D91 Chalk run (50/51) used the extraction schema before the `urgent` fact kind; `eval_sim` has no urgent rows yet.
- A stress test that overlaps any replan (a text, a join burst, the replan that re-places players right after `/dev/reset`) is dropped as "superseded": wait ~5 s after a reset, press again if it happens.
- **Join on the shared iMessage line (D89), not verified with real phones:** Photon advised against SMS campaigns, so players register first (`POST /join` → Photon assignment, one seat each; the free plan has 25 = `MAX_PLAYERS`) and then text the line. A phone that registers but never texts is never placed; its seat is released at the next join after 10 min (D92). If a text to a resident fails after Photon's retries and ElevenLabs is configured, EMBER calls them with it (D90).
- ElevenLabs: the call-over status read (`GET /v1/convai/conversations/{id}`) and the agent's `first_message` setup are untested against the live API; a call that never reports done ends after `SESSION_IDLE_S` without the follow-up text.
- Daytona's `last_activity_at` ignores `run_code`, so the orphan sweep deletes only this process's own sandboxes (owner label) or ones past the TTL (D92); a second backend or `ember robust` on the same key no longer kills the demo pool, but shares the vCPU quota.
- Web: real frame rate unmeasured on the demo machine; the stage labels need one look on the projector (D87).

## Gotchas learned the hard way
- After changing any module a sandbox imports (sim, models, allocator, world, scenario, daytona/jobs, docstrings included): `cd engine && uv run ember daytona-snapshot` (~75–100 s). Check with `uv run python -c "from ember_engine.daytona import pool; print(pool.snapshot_name())"`.
- The backend warms 90 sandboxes on every engine-mode start when `engine/.env` has a key; they're deleted on clean shutdown. 100-vCPU quota: a second pool gets ~10.
- Players (D89) survive resets: use a fresh `DB_PATH` for `e2e.py`, and `MAX_PLAYERS=3` to run its cap check.
- `uv sync` drops the engine's `dev` extra (pytest): use `uv sync --extra dev` in `engine/`. Tests that hit `/optimize` must set `EMBER_LOCAL_POOL=1`.
- Decision numbers collide across branches: check main and open branches before taking one.
- zsh mangles `$B:path`; use `${B}:path`.

## Opening prompt for a new session
```
Read CLAUDE.md, docs/HANDOFF.md, docs/DECISIONS.md and all of docs/log/*.md. I'm Aryaman, sole owner (D77). Pull main, check what changed since HANDOFF's timestamp, then continue with HANDOFF "Priorities, in order". Append to docs/log/aryaman.md after each feature, and re-run engine/scripts/e2e.py after every merge.
```
