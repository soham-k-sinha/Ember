# QA — demo run-through checklist

Owner: Aryaman (D49). Run it top to bottom at the run-through and again right before judging. It follows `docs/DEMO.md`
beat for beat; values marked † are from the integration run (2026-10-17) and must be **re-measured after the fix round**.
Write ✅/❌ + initials in the last column of a printed copy. A ❌ on a **blocker** row means that beat uses its fallback.

Roles: **A** = Aryaman (laptop), **S** = Soham (backend, operator phone), **J** = whoever plays the judge,
**X** = Arnav/Anshuman (second laptop, call phone, timing).

The website: a top bar (clock, play/scrub, "vs baseline" switch, LIVE dot, Sources, ⚙ for Fixtures/Live, speed and
Stage/Flat map), the stage, a floating score card (reached before water, still waiting, hospital outage, sewage
overflow, each vs baseline), plan-change toasts, the **Scan to join** QR card with the player roster, and three tabs:
**Feed** (text in → fact → new plan → text out, open needs), **Plan** (vehicles, plan versions; click anything on the
stage or in a list for its inspector and rationale) and **Proof** (Run comparison, Optimize scatter).

## 0 · Setup (T−15 min)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 0.1 | A | `cd engine && uv run pytest -q`; `cd residents && uv run pytest -q`; e2e against a fresh backend (HANDOFF § Run) | all pass; e2e 71/71† | **blocker**: fix or cut the beat | |
| 0.2 | A | both `.env` files on the backend machine | `DAYTONA_API_KEY`, `EMBER_DAYTONA_WORKERS`, `PHOTON_*`, `ANTHROPIC_API_KEY`, `ELEVENLABS_*`, `JOIN_NUMBER` present (names only) | Daytona missing → local pool; Photon/model missing → DEMO fallbacks | |
| 0.3 | A | `cd engine && uv run ember daytona-snapshot` | "ready" in seconds (`ember-engine-0f3cf261d7`† or newer) | build takes ~90 s; never let `/optimize` be first to need it | |
| 0.4 | S | start backend (DEMO § Before going on stage) | plan v1, listener connected, no pool warm-up error | | |
| 0.5 | A | `curl localhost:8000/health` | `mode: engine`, `extraction: on`, `photon: enabled`, listener connected, `max_players` | **blocker** for real phones → `/dev/inbound` | |
| 0.6 | S | `curl localhost:8000/phones` | resident and operator phones opted in | not opted in → that phone texts its line first | |
| 0.7 | A | web with `VITE_API_BASE` and `VITE_JOIN_NUMBER`, open `/?live` full-screen | stage on the Treehouse, LIVE dot, plan v1 on the score card, QR card visible | WS fails → reload | |
| 0.8 | A | `POST /clock {"t_s":300}` | 5:00, paused; judge phone has EMBER's question for #10296 | missing → `POST /replan` once | |

## 1 · Framing and household rescue (0:00–1:05)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 1.1 | A | read the score card | 78 reached before water, 0 m³ sewage, vs baseline† | different → re-measure DEMO.md | |
| 1.2 | J | resident phone: "2 of us, one is in a wheelchair, River St is blocked" | Feed shows text in → fact within ~5 s | **blocker** >10 s → X sends DEMO § Replay 1b | |
| 1.3 | A | watch, no reload | plan toast "v1 → v2 in 0.7 s · …"†; River St red | no change → Replay 1c | |
| 1.4 | A | click #10296 (inspector) | Accessible Van 3 | no van → Replay 1c | |
| 1.5 | A | Plan tab → Generator 1 (inspector) | rerouted, ETA 14 → 25 min†, "route changed: road reported closed" | | |
| 1.6 | J | resident phone | instruction naming Accessible Van 3 and a pickup time; Feed shows text out | no text → show the Feed | |

## 2 · Infrastructure power loss (1:05–1:40)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 2.1 | A | scrub to **15:00** | clock 15:00, state refreshes | | |
| 2.2 | S | operator phone: "Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left" | Feed text in → fact ~5 s | >10 s → Replay 2 (`/dev/inbound` operator) | |
| 2.3 | A | Plan tab → Generator 1 (inspector) | → Mount Auburn, "chosen over Cottage Farm …" | rationale says "down at 120 min" → structured Replay 2 | |
| 2.4 | A | score card | hospital outage ≈ 13 min†, sewage 9,600 m³† | | |
| 2.5 | A | Feed → open needs | Cottage Farm: "the only compatible generator is protecting mt-auburn" | | |

## 3 · Multiplayer (1:40–2:10)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 3.1 | X | scan the QR card with a phone not yet registered, send the pre-filled text | roster shows Player N, status pill, one replan (~0.6 s†); the phone gets its household and instruction | no player in 15 s → Replay 3 or skip | |

## 4 · Daytona (2:10–2:40)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 4.1 | A | Proof tab → **Optimize** | scatter fills with 250 points; done in ~3 s† on 90 sandboxes; `GET /optimize` → `pool: daytona` | `local-fallback` → say "local pool" | |
| 4.2 | A | read the result | kept plan named; worst-20 % unreached 15.7 vs baseline 55.2†; judge's van and hospital generator unchanged | | |

## 5 · EMBER calls first (2:40–2:55)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 5.1 | X | `POST /calls {"handle": …}` to X's opted-in phone, on speaker | rings in < 10 s; roster shows **on call**; EMBER opens with that thread's open question | no ring → read the Margaret excerpt (`docs/voice_transcripts.md`) | |
| 5.2 | X | answer "yes", hang up | "As promised" text arrives after the call | | |
| 5.3 | X | total time | ≤ 3:00 | | |

## 6 · Reset between rehearsals
| # | Who | Action | Expected | ✓ |
|---|---|---|---|---|
| 6.1 | A | `curl -X POST localhost:8000/dev/reset`, then `POST /clock {"t_s":300}` | plan v1 at 5:00; web resets live; players stay registered | |
