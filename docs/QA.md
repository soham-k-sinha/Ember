# QA — demo run-through checklist

Owner: Aryaman (D49). Run it top to bottom at the run-through and again right before judging. It follows `docs/DEMO.md`
beat for beat; values were re-measured on round 3 (2026-10-18, `aryaman/round3`, real Daytona on 90 sandboxes, e2e 83/83).
Write ✅/❌ + initials in the last column of a printed copy. A ❌ on a **blocker** row means that beat uses its fallback.

Roles: **A** = Aryaman (laptop), **S** = Soham (backend, operator phone), **J** = whoever plays the judge,
**X** = Arnav/Anshuman (second laptop, call phone, timing).

The website: a top bar (clock, play/scrub, "vs baseline" switch, LIVE dot, Sources, ⚙ for Fixtures/Live, speed and
Stage/Flat map), the stage, a floating score card (reached before water, still waiting, hospital outage, sewage kept out
of the Charles, each vs baseline), the latest-change strip (the reporter's own outcome first), the **Join the flood**
card (number → Join → QR → "Player N joined") with the player roster, and three tabs: **Feed** (text in → fact → new plan →
text out, open needs), **Plan** (vehicles, plan versions; click anything on the stage or in a list for its inspector and
rationale) and **Proof** (Run comparison; **Pre-season stress test** at 0:00, **Optimize** later; **Stress test 10,000
worlds**; the scatter and a throughput tile).

## 0 · Setup (T−15 min)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 0.1 | A | `cd engine && uv sync --extra dev && uv run pytest -q`; `cd residents && uv run pytest -q`; `engine/scripts/e2e.py --big` against a fresh backend (HANDOFF § Run) | engine 106, residents 301 pass; e2e 83/83 | **blocker**: fix or cut the beat | |
| 0.2 | A | both `.env` files on the backend machine | `DAYTONA_API_KEY`, `EMBER_DAYTONA_WORKERS`, `PHOTON_*`, `ANTHROPIC_API_KEY`, `ELEVENLABS_*` present (names only) | Daytona missing → local pool; Photon/model missing → DEMO fallbacks | |
| 0.3 | A | `cd engine && uv run ember daytona-snapshot` | "ready" in seconds (`ember-engine-d9ea4508c1`) | build takes ~90 s; never let a stress test be first to need it | |
| 0.4 | S | start backend (DEMO § Before going on stage) | plan v1, listener connected, no pool warm-up error | | |
| 0.5 | A | `curl localhost:8000/health` | `mode: engine`, `extraction: on`, `photon: enabled`, listener connected, `max_players: 25`, `players` | **blocker** for real phones → `/dev/inbound` | |
| 0.6 | S | `curl localhost:8000/phones` | resident and operator phones opted in | not opted in → that phone texts its line first | |
| 0.7 | A | web with `VITE_API_BASE`, open `/?live` full-screen | stage on the Treehouse, LIVE dot, plan v1 on the score card, join card with a number field and "iPhone (iMessage) only" | WS fails → reload | |
| 0.8 | A | clock stays at **0:00**; wait ~5 s after any reset | judge phone has EMBER's question for #10296; Proof shows **Pre-season stress test** | missing question → `POST /replan` once | |

## 1 · Framing and pre-season stress test (0:00–0:50)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 1.1 | A | read the score card | 78 reached before water (baseline 58); **Kept out of the Charles 2,317 m³** (sewage 0 vs baseline 2,317) | different → re-measure DEMO.md | |
| 1.2 | A | Proof tab → **Stress test 10,000 worlds** | heading "Stress test · Daytona · 90 sandboxes"; "n / 10,000 worlds back"; done in 3–4 s fan-out (5–8 s wall); throughput tile with "laptop ~24 s measured" | **blocker** `local-fallback` → press **Pre-season stress test** (250 worlds) and say "local pool"; "superseded" → press again | |
| 1.3 | A | read the verdict | **Robust pick · c03 15.7 / Forecast plan · c00 30.3** (worst-20 % people not reached, baseline 40.8), 14.6 fewer; a new plan version, still 78 reached on the forecast | | |

## 2 · Household rescue (0:50–1:30)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 2.1 | A | scrub to **5:00**, paused | clock 5:00 | | |
| 2.2 | J | resident phone: "2 of us, one is in a wheelchair, River St is blocked" | Feed shows text in → fact within ~5 s | **blocker** >10 s → X sends DEMO § Replay 2b (`household_id` 10296) | |
| 2.3 | A | watch, no reload | latest-change strip: **Judge → Accessible Van 3, pickup in 95 min** (replanned in ~0.7 s); River St red (next version, ~0.7 s) | no change → Replay 2c | |
| 2.4 | A | click #10296 (inspector) | Accessible Van 3 | no van → Replay 2c | |
| 2.5 | A | Plan tab → Generator 1 (inspector) | rerouted, ETA 14 → 25 min, "route changed: road reported closed" | | |
| 2.6 | A | score card | reached 80; **Kept out of the Charles 5,167 m³** | | |
| 2.7 | J | resident phone | instruction naming Accessible Van 3 and a pickup time; Feed shows text out | no text → show the Feed | |

## 3 · Infrastructure power loss (1:30–2:00)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 3.1 | A | scrub to **15:00** | clock 15:00, state refreshes | | |
| 3.2 | S | operator phone: "Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left" | Feed text in → fact ~5 s | >10 s → Replay 3b (`/dev/inbound` operator) | |
| 3.3 | A | strip, then Plan tab → Generator 1 (inspector) | **Mount Auburn Hospital → Generator 1, on site in 8 min**; "chosen over Cottage Farm …" | rationale says "down at 120 min" → structured Replay 3c | |
| 3.4 | A | score card | hospital outage ≈ 13 min (baseline 27); sewage tile **5,167 m³ kept out · before the hospital call**; Proof overflow row 9,600 vs 9,600 m³ (stated) | | |
| 3.5 | A | Feed → open needs | Cottage Farm: "the only compatible generator is protecting mt-auburn" | | |

## 4 · Multiplayer (2:00–2:30)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 4.1 | X | type a new iPhone's number into the join card → Join; scan the QR it shows, send the pre-filled `JOIN EMBER` | card shows "Player N: text JOIN EMBER to <line>"; roster shows Player N "waiting for text", then a status pill after the text, one replan (~0.8 s); the card says "Player N joined: you're household #… on <street>" for 5 s; the phone gets its household and instruction over iMessage | no player in 15 s → Replay 4 or skip | |

## 5 · EMBER calls first (2:30–2:55)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 5.1 | X | `POST /calls {"handle": …}` to X's opted-in phone, on speaker | rings in < 10 s; roster shows **on call**; EMBER opens "Hi, this is EMBER, an automated assistant for the flood drill" and that thread's open question | no ring → read the Margaret excerpt (`docs/voice_transcripts.md`) | |
| 5.2 | X | answer "yes", hang up | "As promised" text arrives after the call | | |
| 5.3 | X | total time | ≤ 3:00 | | |

## 6 · Reset between rehearsals
| # | Who | Action | Expected | ✓ |
|---|---|---|---|---|
| 6.1 | A | `curl -X POST localhost:8000/dev/reset`, wait ~5 s | plan v1 at 0:00 (players who texted are placed again, one replan); web resets live; players stay registered | |
