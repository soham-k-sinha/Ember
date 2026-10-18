# Devpost — outline (EMBER, HackHarvard 2026)

Owner: Aryaman (D49). Target: ≥ 900 words, ≥ 8 images, video < 3 min (the DEMO.md video cut). Framing: D63–D65.
Every number below is from the integration run (2026-10-17, `engine/scripts/e2e.py`, `ember compare --seeds 5`); re-measure after the fix round before submitting.

## Title and tagline
**EMBER: adaptive coordination for disasters, shown on a Charles River flood.**
Tagline: *"Forecasts are wrong by minute 10; EMBER keeps the plan right once real people start texting."*

## 1. Inspiration (≈120 words)
- In a flood the plan is made once, from a forecast, and goes stale as soon as people start reporting what is actually happening: a wheelchair, a blocked street, a hospital on backup.
- Coordinators handle each call as it comes (incident by incident). Shared resources (one accessible van, one big generator) get committed early and can't be re-thought.
- We are standing next to the Charles: Cottage Farm (MWRA outfall MWR201) released 21.33 MG ≈ **80,700 m³** of untreated sewage into the river in one 13-hour storm on 2024-01-10 (MWRA 2024 CSO report).

## 2. What it does (≈180 words): the product is the loop
**Flood response is our first demonstration. Adaptive coordination is the product.**
1. People report by iMessage or phone call (Photon): residents and facility operators.
2. The AI reads each text into a structured fact (people, wheelchair, blocked street, minutes of backup) and words the reply; a guard rejects any number, vehicle or street the planner didn't compute. The AI never decides.
3. A planner scores candidate plans with a simulator of the whole district (roads, flood, vehicles, facilities, sewage) and replans in ~0.7 s.
4. Everyone whose instruction changed gets a personal text, with the reason, tagged with the plan version.
5. Daytona stress-tests the top plans in 50 perturbed versions of tonight and keeps the one that holds up in the worst 20%.

**Two incident types, one engine (D64):** household rescue (the judge's text) and critical-infrastructure power loss (Mount Auburn Hospital, the Cottage Farm sewage station). Same planner, plan versions and messaging.

## 3. How we built it (≈220 words)
- **Engine** (Python, numpy): real OpenStreetMap streets and buildings around the venue (586 intersections, 1,196 road segments, 17,810 buildings); a keyframed flood that closes roads over time; facility, wastewater and vehicle models; a deterministic plan simulator (~6 ms per plan); a lexicographic objective: people not reached, then hospital outage, then sewage overflow.
- **Planner:** priority rules + local search, every candidate scored by the simulator; replans keep work in progress, respect declines, keep confirmed pickups in order, let neighbours share a van, drop off at the nearest shelter, and explain each decision with simulated numbers ("sending the generator there instead would mean hospital outage 13 → 215 min, overflow 9,600 → 0 m³").
- **Daytona:** 250 robustness runs (top candidates + baseline × 50 perturbed worlds) on a warm pool of 90 sandboxes, results returned as `run_code` values (no internet in the sandbox), ~3 s fan-out; 10,000 worlds in ~4 s on Daytona vs 24 s on the laptop.
- **Photon 2.0:** iMessage threads (residents, hospital operator) with opt-in, plan-versioned texts, confirm/decline by reply; a join card that registers a judge's phone on the shared iMessage line, then a QR that texts `JOIN EMBER` to it; a call-back when a text can't be delivered; voice calls on the Photon number through ElevenLabs, with EMBER's backend as the agent's LLM, calling the most at-risk first.
- **Backend** (FastAPI, SQLite) is the single source of truth; **website** (React, PixiJS isometric stage) shows the live district, a score card vs baseline, the text → fact → plan feed, plan versions, the comparison and the robustness scatter.
- **Contracts:** JSON Schemas + fixtures let four people build in parallel.

## 4. Results (≈120 words), all from simulation of a synthetic drill
- Plan v1: Generator 1 pre-positioned at Cottage Farm → **0 m³** overflow vs **2,317 m³** for the incident-by-incident baseline.
- After the judge's text (5 seeds, paired worlds): **88.6 vs 51.6 people reached before their deadline (+37.0)**, hospital outage **11 vs 28 min**. EMBER drives more vehicle-km; we say so.
- Hospital report at minute 15: generator re-targeted, outage **13 min** instead of 215; the 9,600 m³ cost is stated, not hidden. People first, always.
- Daytona, 50 worlds at minute 15: worst-20% unreached **18.7 vs 54.8** for the baseline; it picks a different plan than the nominal best at minute 15 (c04 over c00) and at minute 0 (c03 over c00).
- Same engine, second hazard: a synthetic chemical plume next to the venue, **50.8 vs 28.6** people reached (5 perturbed worlds).

## 5. Sustainability and climate adaptation (ASUS Save the Earth, D65)
Untreated overflow (m³) is a term in the planner's objective and a row in every comparison, anchored to the real 2024 Cottage Farm event (≈ 80,700 m³ into the Charles). Plan v1 pre-positions the generator: 0 m³ vs 2,317 m³ for the incident-by-incident baseline. Climate Ready Boston lists Allston/Brighton among the Charles River neighbourhoods exposed to flooding; the same Daytona run at minute 0 is a pre-season question: where to stage generators so the plan holds up across 50 versions of the storm. Never at the expense of people: the objective is lexicographic, and when the hospital needs the generator the plan states the 9,600 m³ it costs.

## 6. What's real vs synthetic (say it plainly)
Real: OSM streets and buildings, the venue, Mount Auburn Hospital, the Cottage Farm CSO facility and outfall MWR201, Boston EMS Station 14, the 2024 MWRA discharge figures. Synthetic (labelled in the app; `scenarios/allston_flood_v1/assumptions.md`): the 40 households and their needs, flood timing, backup endurance, inflow rates, the substation's de-energization time, perturbation ranges.

## 7. Challenges (≈100 words): pick 2–3
- Keeping the LLM out of the plan (hard rule) while still answering every text.
- The planner left the hospital dark when moving the generator cost no rescue (a search gap); found by explaining every decision with counterfactual simulations.
- The backend's robustness runs silently fell back to the laptop (a missing dependency); found by an end-to-end test of the live stack.

## 8. Who built what, and what we learned
From git history and `docs/log/<name>.md`. Each person writes their own lesson; nobody writes one for someone else.
- **Aryaman:** the engine (OSM town, flood hazard, vehicle/facility/sewage models, plan simulator, allocator and replans, baseline, comparison), the contracts, Daytona robustness (snapshot, warm 90-sandbox pool), the PixiJS stage and judge-facing website, multiplayer join, proactive calls, the simulator-graded eval, integration and the end-to-end test.
  Lesson:
- **Soham:** the backend (FastAPI, SQLite shared state, WebSocket), Photon 2.0 threads, the text → fact extraction and its keyword fallback, the text-driven drill, answering questions from the plan, and voice calls through ElevenLabs on the Photon number.
  Lesson:
- **Arnav:** the first operator map (React + deck.gl on MapLibre), its panels and the live WebSocket client.
  Lesson:
- **Anshuman:** the allston_flood_v1 scenario: flood keyframes, facilities, fleet, the 40 households, assumptions and sources (MWRA, Climate Ready Boston).
  Lesson:

## 9. What's next
- More hazards on the same loop (each is a new hazard behind `polygon_at` / `closed_edges_at`): a synthetic chemical plume is built (`scenarios/allston_plume_v1`); heat waves, wildfire and winter storms are not.
- Adjacent markets: grid resilience (crew and generator dispatch), sewer overflow control for utilities, heat-wave outreach to vulnerable residents.
- Calibrated travel and flood models from real elevation and traffic data.

## 10. Built with
Python, numpy, scipy, OSMnx, Shapely, FastAPI, SQLite, Photon 2.0, ElevenLabs, Anthropic Claude (reading texts, wording replies), Daytona, React, TypeScript, Vite, PixiJS, deck.gl, MapLibre.

## Images (≥ 8), take them from the final website after the run-through
1. Map at plan v1 (venue, flood, households, Mount Auburn, Cottage Farm).
2. The judge's phone thread (question → reply → instruction).
3. Map after the judge's text: River St closed, Accessible Van 3 route, rerouted generator.
4. Inspector with a rationale (the judge's pickup, slack before the deadline).
5. Comparison panel (baseline vs EMBER, 5 seeds, "spread, not confidence bounds").
6. Operator thread + the hospital decision with its stated overflow cost.
7. Robustness scatter filling live from Daytona + the ranking table.
8. Plan-version timeline (v1 → v5, what changed each time).
9. Architecture diagram (phones → Photon → backend → engine/Daytona → website).
10. The QR join card with the player roster, and a phone on a call ("on call" pill).

## Video (< 3 min)
The DEMO.md beats at the same timings, opening with the framing sentence; a 15 s call clip for the voice beat. Record after the run-through.
