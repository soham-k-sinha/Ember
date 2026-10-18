# DEMO — EMBER, live judging and video (3:00)

Owner: Aryaman (D49). Numbers were re-measured on round 3 (2026-10-18, branch `aryaman/round3`, allston_flood_v1,
engine mode, keyless backend, real Daytona on 90 sandboxes, e2e 83/83), in this page's order: the pre-season stress test
at 0:00 first, then the judge, the hospital and a join. If the code changes, re-measure with § Replay and update this
page, `docs/QA.md` and `README.md` together. `engine/tests/test_demo_beats.py` pins the engine side of beats 2–3.

D104 fixes an online staging-comparison omission. **Large stress test** now requests 2,000 paired worlds per plan, including the delayed-generator variant when available: up to 12,000 total runs. The round-3 timings and verdicts below are historical reference values; rehearse the current batch and read its actual total and timing.

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
2. `cd engine && uv run ember daytona-snapshot` prints "ready" (current code: `ember-engine-1892f8194d`; this snapshot has not yet been rebuilt during the takeover).
3. Start (HANDOFF § Run, Photon on, `VOICE_MAX_CONCURRENT=1`, `MAX_PLAYERS=25`); the join card registers phones itself (`POST /join`).
4. `curl localhost:8000/health` → `mode: engine`, `extraction: on`, `photon: enabled`, listener connected.
5. Leave the clock at **0:00** for the pre-season beat. The resident phone shows EMBER's question for #10296 (plan v1 asks it); if not, `POST /replan` once.
   After any `/dev/reset`, wait ~5 s: players who already texted are placed again with their own replan, and a stress test
   that overlaps a replan is dropped as "superseded" (press it again).

## The beats (3:00)
| # | Time | Clock | What we do | What the room sees | Say |
|---|---|---|---|---|---|
| 0 | 0:00–0:20 | 0:00 paused | Framing on the stage view: the Treehouse, the water, Mount Auburn, Cottage Farm, the score card. | Plan v1 vs the incident-by-incident baseline on the score card: 78 reached before the water (baseline 58), 0 m³ sewage, **2,317 m³ kept out of the Charles**. | "Flood response is our first demonstration; adaptive coordination is the product. People report, the AI reads, a simulator-scored planner decides, everyone gets their own instruction. Households and timings are synthetic; the streets are real." |
| 1 | 0:20–0:50 | 0:00 paused | **Pre-season stress test (Daytona).** Proof tab → **Large stress test**. | The clock pauses, the heading identifies the pool, and all runs stream into the scatter. Read the actual total (2,000 paired worlds per plan, up to 12,000 runs), timing and worst-20% verdict. Keep the forecast plan unless an alternative gains at least one person. | "Before storm season, we test each candidate on the same thousands of perturbed storms: slower roads, an earlier flood, a van failing. We stage the plan that holds up when things go wrong." |
| 2 | 0:50–1:30 | scrub to **5:00**, paused | **Household rescue by text.** The judge replies on the resident phone, e.g. *"2 of us, one is in a wheelchair, River St is blocked"*. | Feed: text in → fact → new plan in ~0.7 s (plus the model's read); River St replans in ~0.7 s. The latest-change strip leads with the judge: **Judge → Accessible Van 3, pickup in 95 min**; River St turns red, **Generator 1 rerouted, ETA 14 → 25 min**. The judge's phone gets its instruction; the score card moves (reached 80, **5,167 m³ kept out**). | "The AI only reads your text. The van, the route and the time come from the simulator. You got the only accessible van, and the generator three streets away was rerouted because of your road." |
| 3 | 1:30–2:00 | scrub to **15:00** | **Infrastructure power loss.** Soham texts: *"Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left."* | New plan in ~0.7 s: **Mount Auburn Hospital → Generator 1**, outage 13 min vs 27 for the baseline; the rationale states the cost: **Cottage Farm overflow 0 → 9,600 m³**; the sewage tile keeps **5,167 m³ kept out, before the hospital call**. | "The hospital outranks sewage, and EMBER says what that costs in m³ instead of hiding it. People first. For scale, Cottage Farm really released 80,700 m³ into the Charles in one storm in January 2024." |
| 4 | 2:00–2:30 | 15:00 | **Multiplayer.** A judge types their number into the join card (iPhone only) → **Join** → scans the QR it shows → iMessage opens with `JOIN EMBER` to the shared line → send. | Each phone becomes Player N on a flood-zone household; the card confirms "Player N joined: you're household #… on <street>", the roster fills and one replan places a burst of joins (~0.8 s). EMBER calls new players with the head-count and care-needs question. Cap 25 (Photon free-plan seats). | "Every one of you is now a household in this flood, and the plan has to save you." **Skip if no phone joins within 15 s.** |
| 5 | 2:30–2:55 | 15:00 | **EMBER calls first.** Live: `POST /calls` to the second-laptop phone on speaker, or a player's phone shows the **on call** pill. Fallback: read Maria's first-contact excerpt from `docs/voice_transcripts.md`. | On the first call, ElevenLabs opens "This is EMBER, an automated assistant in a live flood simulation.", asks the combined head-count and care-needs question, and says the computed instruction. A "From our call:" text follows. | "EMBER calls at the moments that matter: first contact, a changed pickup, and two minutes before the vehicle arrives. Nobody has to keep replying yes or done." |
| 6 | 2:55–3:00 | | Close. | | "Every decision on screen has a computed reason." |

Video: the same beats; record after the run-through. Beat 4 becomes a pre-recorded phone scan.
We do not press Optimize at 15:00 on stage: there it picks c04 over c00 (18.7 vs 21.4 in the worst 20 % of 250 worlds) and
moves the judge's Van 3 pickup 85 → 111 min (deadline 165), which is correct but costs a sentence to explain.

## Fallbacks (decide in 5 s)
| Fails | Do |
|---|---|
| Photon (no text in ~10 s) | Second laptop: `POST /dev/inbound` with the same text and `household_id` 10296 (§ Replay). "The phone line is slow; here's the same text." |
| Model (no plan change after an inbound) | Structured report (§ Replay 2c / 3c): same replan, no model. |
| Daytona (`pool: local-fallback`, heading says "this laptop") | Press **Pre-season stress test** (50 worlds per plan) instead of the large batch. Read the actual worker pool and measured timing; do not present a local run as Daytona. |
| Stress test says "superseded" | A text or join replanned during the run; press it again. |
| Join (no player appears) | `POST /join` then `POST /dev/inbound` with that `handle` and `JOIN EMBER` (§ Replay 4), or skip beat 4. A phone that never texts the line is never placed. |
| Call (no ring in 10 s) | Read the transcript excerpt. |
| Website stops updating | Reload `/?live`. Backend crash: restart with `RESET_ON_START=1`, then § Replay. |

## Replay (every beat by curl; also the QA script)
Players exist (D89), so every resident `/dev/inbound` names the judge's household; without it the text can land on a player's thread.
```bash
B=localhost:8000; H='content-type: application/json'
curl -X POST $B/dev/reset; sleep 5                                                # 0: plan v1 at 0:00
curl -X POST "$B/optimize?seeds=2000"; sleep 10; curl $B/optimize                 # 1: pre-season, 2,000 paired worlds per plan
curl -X POST $B/clock -H "$H" -d '{"t_s":300}'                                    # 2: 5:00
# 2b typed text (Photon down) | 2c structured (model down): use one, not both
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"resident","household_id":10296,"text":"2 of us, one is in a wheelchair, River St is blocked"}'
curl -X POST $B/reports -H "$H" -d '{"source":"judge","kind":"need","household_id":10296,"payload":{"people":2,"mobility":true,"accessible_vehicle":true}}'
curl -X POST $B/disruption -H "$H" -d '{"close_edges":[523,833,952],"note":"River St blocked at Memorial Dr"}'
curl -X POST $B/clock -H "$H" -d '{"t_s":900}'                                    # 3: 15:00
# 3b typed text | 3c structured
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"operator","facility_id":"mt-auburn","text":"Mount Auburn facilities: we lost grid power, we are on backup and it has about 10 minutes left"}'
curl -X POST $B/disruption -H "$H" -d '{"facility_id":"mt-auburn","set":{"state":"backup","backup_endurance_s":600},"note":"Mount Auburn: on backup, 10 min left"}'
curl -X POST $B/join -H "$H" -d '{"handle":"+16175550101"}'                                              # 4: register …
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"resident","handle":"+16175550101","text":"JOIN EMBER"}'   # … then its first text places it
curl -X POST $B/calls -H "$H" -d '{"handle":"<opted-in phone>"}'                  # 5
curl -X POST $B/dev/inbound -H "$H" -d '{"role":"resident","household_id":10296,"text":"the water is at our door, please hurry"}'   # urgent, if asked
curl "$B/comparison?seeds=5"                                                      # baseline vs EMBER, if asked
```

## If asked
- **"Is the AI planning?"** No. The AI reads a text into a structured fact and words the reply; a guard rejects any number, vehicle or street the planner didn't compute. Routes, times and assignments come from numpy simulation and local search in about 0.7 s.
- **"Hospital or sewage?"** Lexicographic: people not reached, then hospital outage, then overflow. The plan states the trade-off with simulated numbers.
- **"What if someone texts that the water is at the door?"** That reads as urgent: an immediate replan (a vehicle that can come sooner does), then "We hear you, and we're on it.", what to do meanwhile and their current ETA.
- **"Why does EMBER drive more?"** It pre-positions the generator and reaches more households; the extra vehicle-km are on the Proof tab.
- **"Is it only floods?"** No: `scenarios/allston_plume_v1` runs a synthetic chemical plume on the same engine (50.8 vs 28.6 people reached, 5 worlds).
- **"What's real?"** OSM streets, city building data, the venue, Mount Auburn, Cottage Farm CSO, MWRA outfall MWR201 and its 2024 figures. Synthetic: households and needs, flood timing, backup endurance, inflow (`scenarios/allston_flood_v1/assumptions.md`).
