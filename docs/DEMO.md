# DEMO — EMBER, live judging and video (3:00)

Owner: Aryaman (D49). Numbers were re-measured after the fix round (2026-10-17 night, branch `aryaman/round2`,
allston_flood_v1, engine mode, real Daytona, e2e 79/79). If the code changes, re-measure with § Replay and update this
page, `docs/QA.md` and `README.md` together. `engine/tests/test_demo_beats.py` pins the engine side of beats 1–2.

## Who holds what
| Who | Holds | Does |
|---|---|---|
| **Aryaman** | demo laptop (website `/?live` full-screen at 1920×1080; terminal with § Replay) | drives the clock, narrates |
| **Judge** | **resident phone**: an opted-in team phone, unlocked on the EMBER thread | is household **#10296** (River St at Memorial Dr) |
| **Soham** | **operator phone** (opted in) = Mount Auburn Hospital facilities | sends the operator text; watches the backend log |
| Arnav / Anshuman | second laptop + a phone for the call beat | runs § Replay if a phone or the model fails; times the talk |

Photon shared lines work only after the tester texts first; no group chats. Check `GET /phones` (both `opted_in`) before going on.
**Judge timing:** keep the clock **paused at 5:00** until the judge's reply has produced a new plan (Generator 1 passes their corner at about minute 12).

## Before going on stage (T−15 min)
1. The backend machine has both key files: `engine/.env` (Daytona, `EMBER_DAYTONA_WORKERS=90`) and `residents/.env`
   (Photon, Anthropic, ElevenLabs). Never commit them.
2. `cd engine && uv run ember daytona-snapshot` prints "ready" (current: `ember-engine-d9ea4508c1`).
3. Start (HANDOFF § Run, Photon on, `VOICE_MAX_CONCURRENT=1`, `MAX_PLAYERS=25`); the join card registers phones itself (`POST /join`).
4. `curl localhost:8000/health` → `mode: engine`, `extraction: on`, `photon: enabled`, listener connected.
5. `POST /clock {"t_s":300}` (5:00, paused). The resident phone shows EMBER's question for #10296; if not, `POST /replan` once.

## The beats (3:00)
| # | Time | Clock | What we do | What the room sees | Say |
|---|---|---|---|---|---|
| 0 | 0:00–0:20 | 5:00 paused | Framing on the stage view: the Treehouse, the water, Mount Auburn, Cottage Farm, the score card. | Plan v1 vs the incident-by-incident baseline on the score card: 78 reached before the water (baseline 58), 0 m³ sewage (baseline 2,317). | "Flood response is our first demonstration; adaptive coordination is the product. People report, the AI reads, a simulator-scored planner decides, everyone gets their own instruction. Forecasts are wrong by minute 10; EMBER keeps the plan right once people start texting. Households and timings are synthetic; the streets are real." |
| 1 | 0:20–1:05 | 5:00 paused | **Household rescue by text.** The judge replies on the resident phone, e.g. *"2 of us, one is in a wheelchair, River St is blocked"*. | Feed: text in → fact → new plan in ~0.6 s (plus the model's read); River St replans in ~0.8 s. **Accessible Van 3 → #10296**, River St turns red, **Generator 1 rerouted, ETA 14 → 25 min**. The judge's phone gets its instruction; the score card moves (reached 80). | "The AI only reads your text. The van, the route and the time come from the simulator. You got the only accessible van, and the generator three streets away was rerouted because of your road." |
| 2 | 1:05–1:40 | scrub to **15:00** | **Infrastructure power loss.** Soham texts: *"Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left."* | New plan in ~0.8 s: **Generator 1 re-targeted to Mount Auburn**, outage 13 min vs 27 for the baseline; the rationale states the cost: **Cottage Farm overflow 0 → 9,600 m³**. | "The hospital outranks sewage, and EMBER says what that costs in m³ instead of hiding it. People first. For scale, Cottage Farm really released 80,700 m³ into the Charles in one storm in January 2024." |
| 3 | 1:40–2:10 | 15:00 | **Multiplayer.** A judge types their number into the join card → **Join** → scans the QR it shows → iMessage opens with `JOIN EMBER` to the shared line → send. | Each phone becomes Player N on a flood-zone household; the roster fills and one replan places a burst of joins (~0.6 s). Cap 25 (Photon free-plan seats). | "Every one of you is now a household in this flood, and the plan has to save you." **Skip if no phone joins within 15 s.** |
| 4 | 2:10–2:40 | 15:00 | **Daytona.** Proof tab → **Optimize**. | The scatter fills with 250 runs (top candidates + baseline × 50 perturbed worlds) on **90 sandboxes in ~3 s fan-out (4.6 s wall)**. Worst 20 % of worlds: 18.7 people not reached vs 54.8 for the baseline; it picks c04 over the forecast plan c00 (21.4). For scale: `POST /optimize?seeds=2000` = 10,000 worlds in 4.1 s fan-out (7.3 s wall), 18.5 vs 53.4; the laptop needs 24 s. | "Daytona runs every candidate against 50 versions of tonight in about three seconds, and we keep the plan that holds up when things go wrong. Run before storm season, the same question tells you where to stage generators." |
| 5 | 2:40–2:55 | 15:00 | **EMBER calls first.** Live: `POST /calls` to the second-laptop phone on speaker, or a player's phone shows the **on call** pill. Fallback: read the Margaret excerpt from `docs/voice_transcripts.md`. | ElevenLabs on the Photon number says exactly what the thread would text, then texts it "as promised". | "When someone at risk goes quiet, EMBER calls them, most at-risk first." |
| 6 | 2:55–3:00 | | Close. | | "Every decision on screen has a computed reason." |

Video: the same beats; record after the run-through. Beat 3 becomes a pre-recorded phone scan.

## Fallbacks (decide in 5 s)
| Fails | Do |
|---|---|
| Photon (no text in ~10 s) | Second laptop: `POST /dev/inbound` with the same text (§ Replay). "The phone line is slow; here's the same text." |
| Model (no plan change after an inbound) | Structured report (§ Replay 1c / 2c): same replan, no model. |
| Daytona (`pool: local-fallback`) | It runs on the laptop's processes and says so. "Local pool; on Daytona this is 90 sandboxes." |
| Join (no player appears) | `POST /join` then `POST /dev/inbound` with that `handle` and `JOIN EMBER` (§ Replay 3), or skip beat 3. A phone that never texts the line is never placed. |
| Call (no ring in 10 s) | Read the transcript excerpt. |
| Website stops updating | Reload `/?live`. Backend crash: restart with `RESET_ON_START=1`, then § Replay. |

## Replay (every beat by curl; also the QA script)
```bash
B=localhost:8000; H='content-type: application/json'
curl -X POST $B/dev/reset; curl -X POST $B/clock -H "$H" -d '{"t_s":300}'     # 0
# 1b typed text (Photon down) | 1c structured (model down): use one, not both
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"resident","text":"2 of us, one is in a wheelchair, River St is blocked"}'
curl -X POST $B/reports -H "$H" -d '{"source":"judge","kind":"need","household_id":10296,"payload":{"people":2,"mobility":true,"accessible_vehicle":true}}'
curl -X POST $B/disruption -H "$H" -d '{"close_edges":[523,833,952],"note":"River St blocked at Memorial Dr"}'
curl -X POST $B/clock -H "$H" -d '{"t_s":900}'                                # 2: 15:00
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"operator","text":"Mount Auburn facilities: we lost grid power, we are on backup and it has about 10 minutes left"}'
curl -X POST $B/disruption -H "$H" -d '{"facility_id":"mt-auburn","set":{"state":"backup","backup_endurance_s":600},"note":"Mount Auburn: on backup, 10 min left"}'
curl -X POST $B/join -H "$H" -d '{"handle":"+16175550101"}'                                              # 3: register …
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"resident","handle":"+16175550101","text":"JOIN EMBER"}'   # … then its first text places it
curl -X POST $B/optimize; sleep 5; curl $B/optimize                          # 4
curl -X POST $B/calls -H "$H" -d '{"handle":"<opted-in phone>"}'              # 5
curl "$B/comparison?seeds=5"                                                  # baseline vs EMBER, if asked
```

## If asked
- **"Is the AI planning?"** No. The AI reads a text into a structured fact and words the reply; a guard rejects any number, vehicle or street the planner didn't compute. Routes, times and assignments come from numpy simulation and local search in about 0.7 s.
- **"Hospital or sewage?"** Lexicographic: people not reached, then hospital outage, then overflow. The plan states the trade-off with simulated numbers.
- **"Why does EMBER drive more?"** It pre-positions the generator and reaches more households; the extra vehicle-km are on the Proof tab.
- **"What's real?"** OSM streets, city building data, the venue, Mount Auburn, Cottage Farm CSO, MWRA outfall MWR201 and its 2024 figures. Synthetic: households and needs, flood timing, backup endurance, inflow (`scenarios/allston_flood_v1/assumptions.md`).
