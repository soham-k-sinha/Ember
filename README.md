# EMBER

**People text what is happening; a simulator-scored planner replans the whole district in under a second and tells each person what to do.** Shown on a Charles River flood around the David Rubenstein Treehouse (HackHarvard 2026).

```
text or call (Photon) → structured fact (AI) → simulator-scored replan (~0.7 s, no AI) → personal text or call
```

_Screenshots: `docs/img/` (added after the final run-through)._

Flood response is the first demonstration; adaptive coordination is the product. One engine handles two incident types: household rescue and critical-infrastructure power loss (Mount Auburn Hospital, the Cottage Farm sewage station). Forecasts are wrong by minute 10; EMBER keeps the plan right once real people start reporting.

## Architecture
- **`engine/`** (numpy): a deterministic simulator of the real district (roads, flood, vehicles, facilities, sewage) and a planner that scores every candidate with it. Objective, in order: people not reached, hospital outage, sewage overflow.
- **`residents/`** (FastAPI, SQLite): the source of truth; Photon iMessage threads, ElevenLabs voice on the Photon number, the replan loop, HTTP + WebSocket.
- **`web/`** (React, PixiJS): an isometric stage built from city data, a score card against the baseline, Feed / Plan / Proof tabs, a join card (your number, then a QR that texts the line).
- **Daytona**: stress-tests candidate plans across perturbed worlds and keeps the one that holds up worst-case.

Interfaces are versioned JSON Schemas with fixtures (`contracts/`); every decision is logged in `docs/DECISIONS.md`.

## Results (simulated drill, measured on 2026-10-18, round 3: e2e 83/83 with real Daytona)
| | EMBER | Incident-by-incident baseline |
|---|---|---|
| People reached before the water, plan v1 | **78** | 58 |
| Untreated sewage into the Charles, plan v1 | **0 m³** (2,317 m³ kept out) | 2,317 m³ |
| Text → new plan (judge's wheelchair need), planner time | **0.6–0.9 s** | — |
| Sewage kept out of the Charles before the hospital call (after the judge's text) | **5,167 m³** | — |
| People reached before the water, after the judge and hospital beats (5 perturbed worlds) | **88.6** | 51.6 |
| Hospital outage (same 5 worlds) | **11 min** | 28 min |
| Pre-season stress test at 0:00: people not reached in the worst 20 % of 10,000 worlds, on 90 Daytona sandboxes (3.2–4.0 s fan-out) | **15.7** robust pick (forecast plan 30.3) | 40.8 |
| People not reached in the worst 20 % of 250 worlds (50 seeds), at 15:00 | **18.7** | 54.8 |
| Chemical plume, a second hazard on the same engine: people reached (5 perturbed worlds) | **50.8** | 28.6 |

The worst-20 % rows use the D94 sampler (sewage inflow and storm timing perturbed too); runs are deterministic, so Daytona and the local pool give the same numbers.

For scale, the real Cottage Farm station released ≈ **80,700 m³** of untreated overflow into the Charles in one 13-hour storm on 2024-01-10 (MWRA, `scenarios/allston_flood_v1/sources.md`). When the hospital loses grid power at minute 15, EMBER moves the only compatible generator there (outage 13 min vs 27 for the baseline, replanned in 0.7–0.9 s) and states the cost: Cottage Farm overflow 0 → 9,600 m³, after keeping 5,167 m³ out of the river until that call. People first, and the plan says so in m³. EMBER also drives more vehicle-km than the baseline.

## Where Daytona is used
`POST /optimize` runs the top candidate plans and the baseline in 50 perturbed worlds (travel times, flood timing, backup endurance, sewage inflow, storm timing, a vehicle failing) on a warm pool of **90 sandboxes** the backend starts at boot (`engine/ember_engine/daytona/`). Code and data are baked into a snapshot; results return as `run_code` values. Measured from the backend (round 3): 250 runs in 1.8–2.1 s fan-out (4–5 s wall); 10,000 runs (`?seeds=2000`, the Proof tab's **Stress test 10,000 worlds**) in 3.2–4.9 s fan-out (5–8 s wall), where the laptop takes 24 s (D86). The forecast-best plan stays unless a more robust one leaves at least 1 fewer person unreached in the worst 20 % of worlds. The demo runs it **pre-season, at 0:00**: c03 over the forecast plan c00 (15.7 vs 30.3 people on 10,000 worlds; 14.6 vs 33.7 on 250). At 15:00 it picks c04 over c00 (18.7 vs 21.4).

## Where Photon is used
- **iMessage** (Photon 2.0): residents and the hospital operator each have one thread; questions, offers, confirm/decline and step-by-step directions all happen there (`residents/residents/photon.py`, `messaging.py`).
- **Join**: a judge types their number into the join card (`POST /join` registers it on the shared iMessage line, one Photon seat each, up to 25), then scans the QR, which opens iMessage with `JOIN EMBER` to that line; the first text makes them Player N on a real flood-zone household.
- **Voice**: ElevenLabs runs calls on the Photon number with EMBER's backend as the agent's LLM, so a call says what the thread would text (`voice.py`, `speech.py`). EMBER calls for first contact, pickup instructions, changed pickups, and the two-minute arrival warning, with a written follow-up. Calls queue by flood deadline; a missed call is retried once, then texted. Instructions and later steps proceed on the simulation clock without requiring YES or DONE. Simulated calls: `docs/voice_transcripts.md`.

## Where the AI is, and isn't
One call reads each text in context (`extract.py`); one words the reply, and a deterministic guard rejects any number, vehicle, street or facility the planner didn't compute (`reply.py`). If the model is down, a keyword parser takes over (`fallback.py`). Routes, times and assignments are always computed.

## How we evaluate
- **Simulator-graded eval** (`docs/eval.md`): 51 sample messages; a reading passes only if, after the replan, the household still gets out in time with no regret. Claude Sonnet 5.5 through **Chalk's Model Gateway: 50/51 pass, 1 ask, 0 fail (100 % safe)**; the keyword fallback alone: 46/51 pass, 4 ask, 1 fail.
- **End to end** (`engine/scripts/e2e.py --big`): **83/83 checks** against a live backend with real Daytona: every demo beat, contracts, WebSocket, playback, 250 and 10,000 worlds, the sewage kept out before and after the hospital trade, register-then-text joins (iPhone-only note) and the player cap, and the second scenario validating.
- **Unit tests**: engine 106, residents 301; CI runs them, ruff and the web build (`.github/workflows/ci.yml`).

## Real vs synthetic
**Real:** OSM streets, City of Boston/Cambridge buildings, the venue, Mount Auburn Hospital, Cottage Farm CSO and outfall MWR201, Boston EMS Station 14, MWRA 2024 overflow figures. **Synthetic, labelled in the app:** the 40 assisted households and their needs, flood timing, backup endurance, sewage inflow, the fleet, perturbation ranges (`scenarios/allston_flood_v1/assumptions.md`). The flood is the demo; the plume below is a smaller synthetic drill.

**Not yet verified live:** the register-then-text join with real phones on the shared iMessage line, releasing a seat that never texted (Photon's assignment DELETE, tested against a fake only), ElevenLabs' call-ended status read; the real-model eval predates the `urgent` fact kind.

## Climate adaptation
Climate Ready Boston lists Allston/Brighton among the Charles River neighbourhoods exposed to flooding. The same `/optimize` run at t = 0 (the Proof tab's **Pre-season stress test**, and the demo's opening Daytona beat on 10,000 worlds) answers a pre-season question: where should vehicles and generators be staged so the plan holds up across thousands of versions of the storm? Sewage overflow is in the planner's objective, so keeping raw sewage out of the Charles is optimized, never at the expense of people. `ember robust` at t = 0 also runs the forecast-best plan with Generator 1 sent when the substation trips instead of now. On the forecast both spill 0 m³; in the worst 20 % of 50 worlds, sending it at the trip spills **3,995 m³** against **77 m³** staged now (D94).

## Same engine, second hazard
`scenarios/allston_plume_v1` is a synthetic chemical plume from the storage tank 180 m south of the Treehouse, drifting east on a west wind: the engine's `GrowingEllipseHazard` (`hazard.type: "ellipse"`), sampled into timed extents on load. Same roads, household ids, planner, simulator and baseline; 22 carless households (54 people) and three vans. `ember compare --seeds 5`: EMBER reaches **50.8** people before the plume vs **28.6** for the baseline (better on 5/5 worlds) and drives 13.6 more vehicle-km. Release point, plume growth, fleet and needs are all synthetic (`assumptions.md`); it is not a dispersion model.

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
