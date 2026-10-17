# DEMO — EMBER, live judging (≈3:30) and video (<3:00)

Owner: Aryaman (D49). Numbers below were measured on `main` on Sat 2026-10-17 against the live backend
(allston_flood_v1, engine mode); every one is reproducible with the curls in § Replay. Re-measure after any
engine or scenario change and fix this page; `engine/tests/test_demo_beats.py` pins the engine side of beats 2–4.

## Who holds what
| Who | Holds | Does |
|---|---|---|
| **Aryaman** | demo laptop (website full-screen at 1920×1080, terminal with § Replay in a second window) | drives the clock and the map, narrates |
| **Judge** | **resident phone**: one of our two opted-in team phones, handed over unlocked on the EMBER thread | is household **#10296** (River St, near Memorial Dr); answers EMBER's question |
| **Soham** | **operator phone** (the other opted-in phone) = Mount Auburn Hospital facilities | sends the operator text in beat 4; watches the backend log |
| Arnav / Anshuman | second laptop | runs the Replay curls if a phone or the LLM fails; times the talk |

Photon shared lines only work after the tester texts first, and no group chats. Both phones were opted in on Saturday.
Re-check with `GET /phones` (both `opted_in`) before going on stage. Never hand the judge a phone that isn't opted in.

## The judge-timing rule
The judge is #10296 and Generator 1's first route passes their corner at about sim-minute 12. **The judge must reply
while the sim clock is before ~8 min.** The clock only moves when we press Play or scrub, so keep it **paused at
5:00** until the judge's reply has produced a new plan. Do the operator beat at **15:00, and never after 25:00**. From
30:00 the scripted household #7464 arrives, and the plan keeps the generator at Cottage Farm because people outrank
the hospital in the objective (§ If asked).

## Before going on stage (T−15 min)
1. One machine runs the backend with **both** key files: `engine/.env` (Daytona, Aryaman's laptop) and `residents/.env`
   (Photon + Anthropic, Soham's). Copy whichever is missing over AirDrop. Never commit them.
2. Tier 2 Daytona: `EMBER_DAYTONA_WORKERS=90` in `engine/.env`. Check the snapshot for the current code exists:
   `cd engine && uv run ember daytona-snapshot` (it prints "ready" right away if it already exists; current: `ember-engine-34d49a132c`).
3. Start (no `EMBER_LOCAL_POOL`, Photon on):
   ```bash
   cd residents && RESET_ON_START=1 uv run uvicorn residents.app:app --port 8000
   cd web && VITE_API_BASE=http://127.0.0.1:8000 npm run dev      # http://localhost:43123 → press Live
   ```
4. `curl localhost:8000/health` → `mode: engine`, `extraction: on`, `photon: enabled`, listener connected.
5. `curl -X POST localhost:8000/clock -H 'content-type: application/json' -d '{"t_s":300}'` (clock at 5:00, paused).
6. The resident phone shows EMBER's question for #10296: *"How many people are with you, and does anyone need a
   wheelchair-accessible vehicle?"* If it isn't there, `POST /replan` once.

## The six beats
| # | Time | Sim clock | What we do | What the room sees (measured) | Say |
|---|---|---|---|---|---|
| 1 | 0:00–0:30 | 5:00 paused | Map tilted on the Treehouse. Point at the venue, the water on the river edge, the 40 assisted households, Mount Auburn, Cottage Farm. | Plan v1: 78 people reached before their deadline, 9 not, 0 m³ overflow. Generator 1 en route to Cottage Farm (ETA 14 min). | "A Charles River flood around this building. One shared picture: water, roads, people who need help, a hospital, a sewage pumping station, vans and generators. Households and timings are synthetic; the streets are real." |
| 2 | 0:30–1:20 | 5:00 paused | Hand the judge the resident phone. They reply, e.g. *"2 of us, one is in a wheelchair, River St is blocked"*. | ~2–5 s later (LLM + 0.5 s replan): **Accessible Van 3 → #10296, pickup 132 min vs deadline 165 min**. River St turns red. **Generator 1 ETA 14 → 32 min, "route changed: road reported closed"**. The judge's phone gets their instruction. | "One text, one LLM call to turn it into a fact, then the planner. No LLM in the plan. You got the only accessible van, and the generator three streets away was rerouted because of your road." |
| 3 | 1:20–1:50 | 5:00 paused | Comparison tab. | Baseline (incident-by-incident) vs EMBER, 5 perturbed worlds, at this plan: **untreated overflow 5,244 m³ → 0 m³**; **59.6 → 9.4 people not reached** (+50.2); EMBER drives more (≈ +80 vehicle-km). | "The baseline sends the generator after the pumping station fails. EMBER pre-positions it, so no raw sewage goes into the Charles. Overflow in m³ is inside the objective, not a dashboard afterthought. We drive more, and we say so." |
| 4 | 1:50–2:30 | scrub to **15:00** | Soham texts from the operator phone: *"Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left."* | New plan version: **Generator 1 re-targeted to Mount Auburn: "grid power lost at 15 min, down at 25 min … connected 42 min"** → 16 min of hospital outage instead of 199. Cottage Farm goes to unresolved: "the only compatible generator is protecting mt-auburn". **Overflow 0 → 9,600 m³** on screen. | "The hospital outranks sewage, and EMBER shows the cost in m³ instead of hiding it. It also tells the operator what would unblock Cottage Farm: a second compatible generator." |
| 5 | 2:30–3:10 | 15:00 | Press **Optimize** (or Replay §5). | 100 runs (top-4 candidates + baseline × 20 perturbed worlds: travel times, flood timing, endurance, a vehicle failing) stream into the scatter. Measured: 8 sandboxes, ~10 s on Tier 1. It **chooses c03 over the nominal best c00**: worse in the forecast world (14 vs 9 not reached) but better in the worst 20% of worlds (**31 vs 42**) and on average (17.8 vs 24.2). The judge's van and the hospital generator are unchanged. | "Daytona runs every candidate plan against 20 versions of tonight. We pick the plan that holds up when things go wrong, not the one that looks best on the forecast." |
| 6 | 3:10–3:30 | Play at 60× | Let vans move for a few seconds, then stop. | Trips light up; the plan-version timeline shows every version since v1 and what changed in each. | "Every decision on screen has a computed reason. Households, timings and flood keyframes are synthetic and labelled in the app and the write-up." |

Video cut (<3:00): beats 1, 2, 3, 4, 5 at the same timings, without beat 6. Record after the 8 PM run-through.

## One line per sponsor
- **Daytona:** every replan can fan out to parallel sandboxes: top candidates × 20 perturbed worlds, results back as `run_code` return values (no internet in the sandbox), choose the best worst-20% plan. 100 runs in ~10 s on 8 Tier-1 sandboxes; ~90 workers on Tier 2.
- **Photon:** two real iMessage threads (a resident and a hospital operator) on Photon 2.0. Each thread keeps context across plan versions: one question at a time, a text only when your own instruction changed, confirm/decline by reply.
- **Sustainability:** untreated wastewater to the Charles (m³) is a term in the allocator's objective and a row in every comparison; EMBER avoids ~2,165 m³ (5-seed mean, plan v1) to ~5,244 m³ (after the River St closure) that the baseline releases.

## Fallbacks (decide in 5 s, don't debug on stage)
| Fails | Do |
|---|---|
| Photon (text doesn't arrive in ~10 s) | Second laptop: `POST /dev/inbound` with the same text (§ Replay 2b/4b). Same path after the phone, same LLM. Say "the phone line is slow, here's the same text". |
| LLM extraction (no plan change after an inbound) | Structured reports (§ Replay 2c/4c): same replan, no LLM. |
| Daytona (`/optimize` errors or `pool: local-fallback`) | Nothing to do: it runs locally on 8 processes (2–3 s) and says so. Say "local pool; on Daytona this is 90 sandboxes". |
| Website WS (map stops updating) | Reload the page and press Live. Last resort: Fixtures mode (static v1→v3 story). |
| Backend crash | Restart with `RESET_ON_START=1`, then § Replay from the top (≈10 s). |

## Replay (all beats by curl; also the QA script)
```bash
B=localhost:8000; H='content-type: application/json'
curl -X POST $B/dev/reset                                                     # fresh plan v1 at t=0
curl -X POST $B/clock -H "$H" -d '{"t_s":300}'                                # 1: clock 5:00
# 2a: real phone  | 2b: typed text (Photon down)  | 2c: structured (LLM down)
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"resident","text":"2 of us, one is in a wheelchair, River St is blocked"}'
curl -X POST $B/reports -H "$H" -d '{"source":"judge","kind":"need","household_id":10296,"payload":{"people":2,"mobility":true,"accessible_vehicle":true}}'
curl -X POST $B/disruption -H "$H" -d '{"close_edges":[523,833,952],"note":"River St blocked at Memorial Dr"}'
curl "$B/comparison?seeds=5"                                                  # 3
curl -X POST $B/clock -H "$H" -d '{"t_s":900}'                                # 4: clock 15:00
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"operator","text":"Mount Auburn facilities: we lost grid power, we are on backup and it has about 10 minutes left"}'
curl -X POST $B/disruption -H "$H" -d '{"facility_id":"mt-auburn","set":{"state":"backup","backup_endurance_s":600},"note":"Mount Auburn: on backup, 10 min left"}'
curl -X POST "$B/optimize?seeds=20&k=4"; sleep 15; curl $B/optimize           # 5
```
Use either 2b or 2c, not both (each is its own replan). River St edges come from
`EngineSession.edges_by_name("River Street", near_household=10296, radius_m=150)`.

## If asked
- **"Why not send the generator to the hospital at minute 40?"** The objective is lexicographic: people not reached,
  then hospital outage, then overflow. From minute 30 the generator truck is also carrying people. Moving it would
  strand a household, so the plan keeps it and lists the hospital as unresolved with what would unblock it.
- **"Is the LLM planning?"** No. One call turns a text into a structured report. Routes, times and assignments come
  from numpy simulation and local search, about 0.5 s per replan.
- **"Why does EMBER drive more?"** It pre-positions and chains trips; ≈ +80 vehicle-km buys +50 people and 0 m³.
- **"What's real?"** OSM streets and buildings, the venue, Mount Auburn, Cottage Farm CSO, the MWRA outfall. Synthetic:
  household counts and needs, flood timing, backup endurance, inflow rates (`scenarios/allston_flood_v1/assumptions.md`).
