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
rationale) and **Proof** (Run comparison; **Pre-season stress test** at 0:00, **Optimize** later; **Large stress test**; the scatter and a throughput tile).

## 0 · Setup (T−15 min)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 0.1 | A | `cd engine && uv sync --extra dev && uv run pytest -q`; `cd residents && uv run pytest -q` | all pass | **blocker**: fix or cut the beat | |
| 0.2 | A | ElevenLabs credits left; both `.env` files present (names only) | a test call doesn't stop with "exceeds your quota limit" | no credits → no calls: read `docs/voice_transcripts.md` | |
| 0.3 | A | quit every other app; `cd engine && uv run ember daytona-snapshot` | "ready" | build ~60 s; never let the stress test be first to need it | |
| 0.4 | A | start the backend (DEMO § Before going on stage 4) | "voice: residents can call +13465660512" | "isn't reachable yet" → start again | |
| 0.5 | A | `curl localhost:8000/health` | `mode: engine`, `extraction: on`, `voice_number: "+13465660512"` | `voice_number: null` → ElevenLabs keys | |
| 0.6 | A | web with `VITE_API_BASE`, `/?live` full-screen, `?perf` once | join card: **Call (346) 566-0512** + QR; fps ≥ 50 | WS fails → reload | |
| 0.7 | X | dial the number from a team phone, answer the question, say "okay" | answer in ~1 s; "I'll text you all of this now. Take care." then it hangs up | then `/dev/reset` | |

## 1 · Framing (0:00–0:15)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 1.1 | A | read the score card | 78 reached before water (baseline 58); 2,317 m³ kept out of the Charles | different → re-measure | |

## 2 · Everyone joins and talks to EMBER (0:15–1:30)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 2.1 | A | scrub to **5:00**, paused | clock 5:00 | | |
| 2.2 | J | 2–3 phones scan the QR / dial (346) 566-0512 | each: "This is EMBER, an automated assistant in a live flood simulation…"; roster shows Player N **on call** | no answer in 10 s → console `call r1` to a team phone | |
| 2.3 | J | one says "4 of us, my mom's in a wheelchair" | reply in ~1 s: **Accessible Van 3** coming to the door; Feed: words → fact → new plan | > 3 s → the model is reading a long sentence; keep it short | |
| 2.4 | J | another says "River St is flooded" | River St red; another player's pickup changes and EMBER calls them with why | | |
| 2.5 | J | each says "okay" | goodbye spoken, call ends; a "From our call:" text follows (iMessage players) | | |

## 3 · Infrastructure power loss (1:30–2:00)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 3.1 | A | scrub to **15:00** | clock 15:00 | | |
| 3.2 | S | operator phone: "Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left" | **Mount Auburn Hospital → Generator 1**; outage ≈ 13 min (baseline 27); overflow 0 → 9,600 m³ stated | > 10 s → Replay 3 (`/dev/inbound` operator) | |

## 4 · Is it still safe? Daytona (2:00–2:35)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 4.1 | A | Proof tab → **Large stress test** | heading names Daytona · 90 sandboxes; 10,000 worlds in ~5 s fan-out; laptop ~24 s tile; worst-20 % verdict | "this laptop" → say so; "superseded" → press again | |
| 4.2 | X | total time | ≤ 3:00 | | |

## 6 · Reset between rehearsals
| # | Who | Action | Expected | ✓ |
|---|---|---|---|---|
| 6.1 | A | `curl -X POST localhost:8000/dev/reset`, wait ~5 s | plan v1 at 0:00 (players who texted are placed again, one replan); web resets live; players stay registered | |
