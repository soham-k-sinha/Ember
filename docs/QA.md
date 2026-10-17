# QA — demo run-through checklist

Owner: Aryaman (D49). Run it top to bottom at the **8 PM run-through** and again right before judging. It follows
`docs/DEMO.md` step for step; expected values were measured on `main` Sat 2026-10-17 (allston_flood_v1). Write ✅/❌ +
initials in the last column of a printed copy. A ❌ in a row marked **blocker** means we switch to that row's fallback for the demo.

Roles: **A** = Aryaman (laptop), **S** = Soham (backend, operator phone), **J** = whoever plays the judge in rehearsal,
**X** = Arnav/Anshuman (second laptop, timing).

## 0 · Setup (T−15 min)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 0.1 | A | `cd engine && uv run pytest -q` | all pass (86+) incl. `test_demo_beats.py` (3) | **blocker**: don't demo a broken beat; fix or cut it | |
| 0.2 | S | `cd residents && uv run pytest -q` | all pass | **blocker** | |
| 0.3 | A | `engine/.env` and `residents/.env` both on the backend machine | `DAYTONA_API_KEY`, `EMBER_DAYTONA_WORKERS`, `PHOTON_API_KEY`, `PHOTON_PROJECT_ID`, `ANTHROPIC_API_KEY` present (names only, never print values) | Daytona missing → local pool (fine); Photon/LLM missing → § fallbacks | |
| 0.4 | A | `cd engine && uv run ember daytona-snapshot` | "ready" in seconds (snapshot exists; `ember-engine-6a73b6188a` or newer) | build takes ~90 s; never let `/optimize` be the first thing to need it | |
| 0.5 | S | start backend (DEMO.md § Before going on stage, step 3) | log shows plan v1, listener connected | | |
| 0.6 | A | `curl localhost:8000/health` | `mode: engine`, `extraction: on`, `photon: enabled`, `photon_listener` connected | **blocker** for real phones → `/dev/inbound` | |
| 0.7 | S | `curl localhost:8000/phones` | 2 phones, roles `resident` and `operator`, both opted in | not opted in → that phone texts its line first | |
| 0.8 | A | web `npm run dev`, open `http://localhost:43123`, press **Live**, full-screen 1920×1080 | map on the Treehouse, status "live", state v1 · allston_flood_v1 | WS fails → reload; then Fixtures | |
| 0.9 | A | `POST /clock {"t_s":300}` | clock 5:00, paused | | |
| 0.10 | J | look at the resident phone | EMBER's question for #10296 ("How many people are with you, and does anyone need a wheelchair-accessible vehicle?") | missing → `POST /replan` once | |

## 1 · Map (0:00–0:30)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 1.1 | A | point at venue, water, households, Mount Auburn, Cottage Farm | all visible and labelled; "synthetic" label on screen | | |
| 1.2 | A | read the KPI bar | 78 reached before deadline, 9 not, overflow 0 m³ | different numbers → scenario/engine changed; re-measure DEMO.md | |
| 1.3 | A | click Generator 1 → Inspector | → Cottage Farm, ETA 14 min, rationale "prevents 9,600 m³ of untreated overflow…" | | |

## 2 · Judge texts (0:30–1:20), clock paused at 5:00
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 2.1 | J | resident phone: "2 of us, one is in a wheelchair, River St is blocked" | message appears in Conversations within ~5 s | **blocker** >10 s → X sends `/dev/inbound` (DEMO § Replay 2b) | |
| 2.2 | A | watch the map, no reload | new plan version within ~3 s of the inbound; River St segments red; "Roads closed" goes up | not red → reload once (web refetches `/state` after each plan) | |
| 2.3 | A | Inspector on #10296 | Accessible Van 3, pickup 132 min vs deadline 165 min | no van → extraction lost the wheelchair; X sends DEMO § Replay 2c | |
| 2.4 | A | Inspector on Generator 1 | re-routed, ETA 14 → 25 min, rationale "route changed: road reported closed" | | |
| 2.5 | J | resident phone | instruction text naming Accessible Van 3 and a pickup time | no text → say it, show the Conversations panel | |

## 3 · Comparison (1:20–1:50)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 3.1 | A | Comparison tab → **Run comparison** (~5 s) | live numbers (not the example fixture): overflow EMBER 0 vs baseline ≈ 5,244 m³; not reached ≈ 9.4 vs 59.6; EMBER vehicle-km higher, said so | "Comparison failed" → `curl "$B/comparison?seeds=5"` on the second screen | |
| 3.2 | A | the label says "spread, not confidence bounds" / 5 perturbed worlds | visible | | |

## 4 · Operator texts (1:50–2:30)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 4.1 | A | scrub clock to **15:00** | clock 15:00, state refreshes | | |
| 4.2 | S | operator phone: "Mount Auburn facilities: we lost grid power, we're on backup and it has about 10 minutes left" | message in Conversations ~5 s | >10 s → `/dev/inbound` operator (Replay 4b) | |
| 4.3 | A | Inspector on Generator 1 | → Mount Auburn Hospital, rationale "grid power lost at 15 min, down at 25 min … connected 39 min · chosen over Cottage Farm …"; old Cottage Farm assignment cancelled | rationale says "down at 120 min" → extraction didn't set `state: backup`; use Replay 4c | |
| 4.4 | A | KPI bar | hospital outage ≈ 13 min; overflow 0 → 9,600 m³ | | |
| 4.5 | A | Unresolved list | Cottage Farm: "the only compatible generator is protecting mt-auburn" + what would unblock it | | |
| 4.6 | S | operator phone | instruction/status text about Generator 1 | | |

## 5 · Daytona (2:30–3:10)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 5.1 | A | press **Optimize** (or Replay 5) | scatter fills with 100 points live | | |
| 5.2 | A | wait | done in ~10 s (Tier 1, 8 sandboxes) or less on Tier 2; `GET /optimize` → `pool: daytona` | `local-fallback` → say "local pool" and move on | |
| 5.3 | A | read the result | chosen c03 ≠ nominal best c00; worst-20% unreached 31 vs 42; judge's van and hospital generator unchanged | | |

## 6 · Close (3:10–3:30)
| # | Who | Action | Expected | Blocker / fallback | ✓ |
|---|---|---|---|---|---|
| 6.1 | A | Play at 60× for ~5 s, then pause | vans and generator move along trips; 60 fps feel | stutter → skip, show the timeline | |
| 6.2 | A | plan-version timeline | every version since v1 with its trigger and change count | | |
| 6.3 | X | total time | ≤ 3:30 live; ≤ 3:00 for the video cut | | |

## 7 · Reset between rehearsals
| # | Who | Action | Expected | ✓ |
|---|---|---|---|---|
| 7.1 | A | `curl -X POST localhost:8000/dev/reset` | plan v1, t=0; web resets live | |
| 7.2 | A | `POST /clock {"t_s":300}` | ready for beat 1 | |
