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
6. Start the backend once, here, and don't restart it on stage (a new tunnel takes up to 90 s). At most 3 judges call at once (ElevenLabs concurrency and credits).
7. One test call from a team phone (`call r1` in the console, or dial the number) and hang up: confirms the tunnel, the agent and the credits.

## The beats (3:00) — keys 1–4 switch views: 1 Live · 2 Photon · 3 Impact · 4 Daytona
| # | Time | View | What we do | What the room sees | Say |
|---|---|---|---|---|---|
| 0 | 0:00–0:15 | **1 Live**, clock 0:00 | The stage: Treehouse, river, Mount Auburn, Cottage Farm. | Score card: 78 reached before the water (baseline 58). | "In a flood the plan is made once and it's wrong in ten minutes. Watch what happens when the people in it can talk back." |
| 1 | 0:15–0:35 | **2 Photon**, scrub to 5:00 | Judges scan the QR / dial **(346) 566-0512** (max 3 at once). | Each phone becomes a node and a Player card; the flow phones → Photon → AI reads → planner → told pulses on every message. | "Any phone. You're now a household in this flood." |
| 2 | 0:35–1:25 | **2 Photon** → **1 Live** | Live agents. One judge: *"4 of us, my mom's in a wheelchair."* Another: *"I fell and hurt my leg, I can't walk."* | Answers in ~1 s; each card shows their words and EMBER's reply. Accessible Van 3 → the wheelchair home; **Ambulance 1** → the hurt judge. | "The AI only understands; a simulator decides. Your words just moved a stranger's rescue." |
| 3 | 1:25–1:45 | **1 Live** | Press play. A vehicle reaches a player: the clock stops, gold alert **"Van 3 reached Player 1 · Show"** and their phone rings ("outside now"). Click **Show**. | Close-up of the home and the vehicle at the door. Resume after the call. | "The vehicle is at your door, and EMBER calls you that second." |
| 4 | 1:45–2:10 | **3 Impact** | Soham texts as Mount Auburn: *"we lost grid power, on backup, about 10 minutes left."* | Hospital outage vs baseline; sewage into the Charles drawn to scale against Cottage Farm's real 80,700 m³ and the trade-off stated. | "People first, and EMBER says what it costs instead of hiding it." |
| 5 | 2:10–2:40 | **4 Daytona** | **Large stress test**. | Laptop → 90 sandbox cells lighting up → verdict; big numbers: worlds, sandboxes, seconds vs the laptop. | "Daytona replays tonight thousands of ways in seconds and keeps the plan that holds up." |
| 6 | 2:40–3:00 | **1 Live** | Close. | | "Photon carries the calls, ElevenLabs the voices, Claude via Chalk reads them, Daytona stress-tests the plan. Every decision has a computed reason." |

Everyone hangs up before beat 5 (a replan during the stress test drops it as "superseded"). Video: the same beats; record after the run-through.

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
