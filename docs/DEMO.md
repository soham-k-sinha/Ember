# DEMO — EMBER, live judging and video (3:00)

Owner: Aryaman (D49). Numbers were re-measured on round 3 (2026-10-18, branch `aryaman/round3`, allston_flood_v1,
engine mode, keyless backend, real Daytona on 90 sandboxes, e2e 83/83), in this page's order: the pre-season stress test
at 0:00 first, then the judge, the hospital and a join. If the code changes, re-measure with § Replay and update this
page, `docs/QA.md` and `README.md` together. `engine/tests/test_demo_beats.py` pins the engine side of beats 2–3.

D104 fixes an online staging-comparison omission. **Large stress test** now requests 2,000 paired worlds per plan, including the delayed-generator variant when available: up to 12,000 total runs. The round-3 timings and verdicts below are historical reference values; rehearse the current batch and read its actual total and timing.

## Who holds what
| Who | Holds | Does |
|---|---|---|
| **Aryaman** | demo laptop: website `/?live` full-screen at 1920×1080; terminal running `ember-drill` (below) | drives the clock, narrates |
| **Judges** | their own phones | call the number on the join card and become households |
| **Soham** | **operator phone** (opted in) = Mount Auburn Hospital facilities | sends the operator text |
| Arnav / Anshuman | second laptop | § Replay if a phone or the model fails; times the talk |

## Before going on stage (T−15 min)
1. ElevenLabs has credits (a call stops mid-sentence with "exceeds your quota limit" otherwise). Both key files present:
   `engine/.env` (Daytona, `EMBER_DAYTONA_WORKERS=90`), `residents/.env` (Photon, Anthropic/Chalk, ElevenLabs). Never commit them.
2. Quit everything else on the laptop (a busy Mac makes the 10,000-world run take 30 s instead of ~6 s).
3. `cd engine && uv run ember daytona-snapshot` prints "ready".
4. Start the backend with calls (one process: API on :8000 for the web, the voice endpoint behind a cloudflared tunnel, the ElevenLabs agent pointed at it):
   `cd residents && PHOTON_ENABLED=1 EXTRACT_ENABLED=1 VOICE_MAX_CONCURRENT=3 MAX_PLAYERS=25 uv run ember-drill --voice --crowded --operator <soham>@mt-auburn`
   It prints "voice: residents can call +13465660512". Then the web: `cd web && VITE_API_BASE=http://127.0.0.1:8000 npm run dev`.
5. `curl localhost:8000/health` → `mode: engine`, `extraction: on`, `voice_number: "+13465660512"`. The join card shows **Call (346) 566-0512** and its QR.
6. One test call from a team phone (`call r1` in the console, or dial the number) and hang up: confirms the tunnel, the agent and the credits.

## The beats (3:00)
| # | Time | Clock | What we do | What the room sees | Say |
|---|---|---|---|---|---|
| 0 | 0:00–0:15 | 0:00 paused | The stage: the Treehouse, the river, Mount Auburn, Cottage Farm, the score card. | Plan v1 vs handling calls one at a time: **78 reached before the water (baseline 58)**, 2,317 m³ of sewage kept out of the Charles. | "In a flood the plan is made once and it's wrong in ten minutes. Watch what happens when the people in it can talk back. The streets are real; households and timings are synthetic." |
| 1 | 0:15–0:30 | 0:00 → **5:00**, paused | **Everyone joins.** Point at the join card: "Call this number." Judges scan the QR or dial **(346) 566-0512**. | Each caller becomes Player N on a real flood-zone home; the roster fills; one replan per join (~0.8 s). | "Any phone. You're now a household in this flood, and the plan has to save you." |
| 2 | 0:30–1:30 | 5:00 paused | **Live agents (the wow).** EMBER talks to up to 3 judges at once: where the water reaches them and "How many people are with you, and does anyone need a wheelchair or medical help?" One says *"4 of us, my mom's in a wheelchair"*; another *"River St is flooded"*. | Answers in ~1 s. The wheelchair household gets **Accessible Van 3** while still on the line; River St turns red; another player's pickup changes and EMBER calls them with why ("Your pickup changed: …"). Feed: words → fact → new plan; each call ends "I'll text you all of this now. Take care." and a text follows. | "The AI only understands; a simulator decides. Your words just moved a stranger's rescue." |
| 3 | 1:30–2:00 | scrub to **15:00** | **The hospital loses power.** Soham texts: *"Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left."* | New plan in ~0.8 s: **Generator 1 → Mount Auburn**, outage 13 min vs 27 for the baseline; the rationale states the cost: **Cottage Farm overflow 0 → 9,600 m³**. | "People first, and EMBER says what it costs instead of hiding it. Cottage Farm really released 80,700 m³ into the Charles in one storm in 2024." |
| 4 | 2:00–2:35 | 15:00 | **Is it still safe? (Daytona).** Proof tab → **Large stress test**. | 10,000 worlds (2,000 per plan) on **90 Daytona sandboxes, ~5 s fan-out**; the throughput tile shows the laptop's ~24 s; the worst-20 % verdict. | "We changed the plan five times in two minutes. Daytona replays tonight 10,000 ways in five seconds and keeps the plan that holds up when things go wrong." |
| 5 | 2:35–3:00 | | Close. | | "Photon carries the calls and texts, ElevenLabs the voices, Chalk routes the model that reads them, Daytona stress-tests the plan. Every decision on screen has a computed reason." |

Video: the same beats; record after the run-through.

## Fallbacks (decide in 5 s)
| Fails | Do |
|---|---|
| Photon (no text in ~10 s) | Second laptop: `POST /dev/inbound` with the same text and `household_id` 10296 (§ Replay). "The phone line is slow; here's the same text." |
| Model (no plan change after an inbound) | Structured report (§ Replay 2c / 3c): same replan, no model. |
| Daytona (`pool: local-fallback`, heading says "this laptop") | Press **Pre-season stress test** (50 worlds per plan) instead of the large batch. Read the actual worker pool and measured timing; do not present a local run as Daytona. |
| Stress test says "superseded" | A text or join replanned during the run; press it again. |
| Join (no one gets through on the number) | Console `call r1` to a team phone on speaker; or the iMessage join under the QR; or § Replay 4. |
| Call (no ring in 10 s, or it stops mid-sentence) | ElevenLabs credits or the tunnel: read Maria's call from `docs/voice_transcripts.md`. |
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
