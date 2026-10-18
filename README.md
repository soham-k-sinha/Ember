# EMBER

**People text what is happening; a simulator-scored planner replans the whole district in under a second and tells each person what to do.** Shown on a Charles River flood around the David Rubenstein Treehouse (HackHarvard 2026).

```
text or call (Photon) → structured fact (AI) → simulator-scored replan (~0.7 s, no AI) → personal text or call
```

_Screenshots: `docs/img/` (added after the final run-through)._

Flood response is the first demonstration; adaptive coordination is the product. One engine handles two incident types: household rescue and critical-infrastructure power loss (Mount Auburn Hospital, the Cottage Farm sewage station). Forecasts are wrong by minute 10; EMBER keeps the plan right once real people start reporting.

## Architecture
- **`engine/`** (numpy): a deterministic simulator of the real district (roads, flood, vehicles, facilities, sewage) and a planner that scores every candidate with it. Objective, in order: people not reached, hospital outage, sewage overflow.
- **`residents/`** (FastAPI, SQLite): the source of truth; Photon iMessage/SMS threads, ElevenLabs voice on the Photon number, the replan loop, HTTP + WebSocket.
- **`web/`** (React, PixiJS): an isometric stage built from city data, a score card against the baseline, Feed / Plan / Proof tabs, a QR card to join.
- **Daytona**: stress-tests candidate plans across perturbed worlds and keeps the one that holds up worst-case.

Interfaces are versioned JSON Schemas with fixtures (`contracts/`); every decision is logged in `docs/DECISIONS.md`.

## Results (simulated drill, measured on 2026-10-17)
| | EMBER | Incident-by-incident baseline |
|---|---|---|
| People reached before the water, after the judge's text (5 perturbed worlds) | **88.6** | 51.6 |
| Hospital outage (same run) | **11 min** | 28 min |
| Untreated sewage into the Charles, plan v1 | **0 m³** | 2,317 m³ |
| Text → new plan (judge's wheelchair need) | **0.66 s** | — |
| People not reached in the worst 20 % of 50 worlds, at 15:00 | **15.7** | 55.2 |

For scale, the real Cottage Farm station released ≈ **80,700 m³** of untreated overflow into the Charles in one 13-hour storm on 2024-01-10 (MWRA, `scenarios/allston_flood_v1/sources.md`). When the hospital loses grid power at minute 15, EMBER moves the only compatible generator there (outage 13 min instead of 215) and states the cost: Cottage Farm overflow 0 → 9,600 m³. People first, and the plan says so in m³. EMBER also drives more vehicle-km than the baseline.

## Where Daytona is used
`POST /optimize` runs the top candidate plans and the baseline in 50 perturbed worlds (travel times, flood timing, backup endurance, a vehicle failing) on a warm pool of **90 sandboxes** the backend starts at boot (`engine/ember_engine/daytona/`). Code and data are baked into a snapshot; results return as `run_code` values. Measured: 250 runs in 3.2–3.4 s wall, 1,000 runs in 3.7 s. EMBER keeps the plan with the best worst-20 % outcome, which is not always the nominal best (at t = 0 it picks c03 over c00).

## Where Photon is used
- **iMessage** (Photon 2.0): residents and the hospital operator each have one thread; questions, offers, confirm/decline and step-by-step directions all happen there (`residents/residents/photon.py`, `messaging.py`).
- **SMS join line**: the QR card pre-fills `JOIN EMBER`; each phone becomes Player N on a real flood-zone household.
- **Voice**: ElevenLabs runs calls on the Photon number with EMBER's backend as the agent's LLM, so a call says what the thread would text (`voice.py`, `speech.py`). EMBER calls the most at-risk first, e.g. no reply while the water is close. Simulated calls: `docs/voice_transcripts.md`.

## Where the AI is, and isn't
One call reads each text in context (`extract.py`); one words the reply, and a deterministic guard rejects any number, vehicle, street or facility the planner didn't compute (`reply.py`). If the model is down, a keyword parser takes over (`fallback.py`). Routes, times and assignments are always computed.

## How we evaluate
- **Simulator-graded eval** (`docs/eval.md`): 51 sample messages; a reading passes only if, after the replan, the household still gets out in time with no regret. Keyword parser: **46/51 pass, 4 ask, 1 fail**. The LLM column is not run yet.
- **End to end** (`engine/scripts/e2e.py`): **71/71 checks** against a live backend with real Daytona: every demo beat, contracts, WebSocket, playback, joins.
- **Unit tests**: engine 102, residents 279; CI runs them and the web build (`.github/workflows/ci.yml`).

## Real vs synthetic
**Real:** OSM streets, City of Boston/Cambridge buildings, the venue, Mount Auburn Hospital, Cottage Farm CSO and outfall MWR201, Boston EMS Station 14, MWRA 2024 overflow figures. **Synthetic, labelled in the app:** the 40 assisted households and their needs, flood timing, backup endurance, sewage inflow, the fleet, perturbation ranges (`scenarios/allston_flood_v1/assumptions.md`). Only the flood is built.

**Not yet verified live:** replies on the SMS join line (needs a Photon campaign), ElevenLabs' call-ended status read, the optional Chalk router for the model calls.

## Climate adaptation
Climate Ready Boston lists Allston/Brighton among the Charles River neighbourhoods exposed to flooding. The same `/optimize` run at t = 0 answers a pre-season question: where should generators be staged so the plan holds up across 50 versions of the storm? Sewage overflow is in the planner's objective, so keeping raw sewage out of the Charles is optimized, never at the expense of people.

## Run it
```bash
# backend, no keys (Daytona is used when engine/.env has DAYTONA_API_KEY; real phones need residents/.env)
cd residents && DB_PATH=/tmp/ember.db RESET_ON_START=1 PHOTON_ENABLED=0 EXTRACT_ENABLED=0 \
    uv run uvicorn residents.app:app --port 8000
# website → http://localhost:43123/?live
cd web && npm install && VITE_API_BASE=http://127.0.0.1:8000 npm run dev
# end-to-end check (exact backend env in its docstring)
cd residents && uv run python ../engine/scripts/e2e.py
# tests
cd engine && uv sync --extra dev && uv run pytest -q
cd residents && EMBER_LOCAL_POOL=1 GEOCODE=0 uv run pytest -q
```
Demo: `docs/DEMO.md` · run-through checklist: `docs/QA.md` · current state: `docs/HANDOFF.md` · who built what: `docs/devpost/README.md`.
