# Physical Realities (MHacks 2026 Grand Prize): how they built the sim, and what we take

Sources: Devpost https://devpost.com/software/physical-realities · repo https://github.com/Cryplo/MHacks26 (commit `f4e0a94`) · demo video https://www.youtube.com/watch?v=QAKv_QoBoQE. Team: Manav Khosla, Dylan Li, Varchas Kukreja. Notes compiled 2026-10-16 from the code, not the pitch.

## Architecture (three lanes, one frozen contract)
- `engine/` — deterministic theme-park mechanics in pure TypeScript (`src/sim/{engine,motion,queue-lines,actions,observations,services,mock-policy}.ts`, nav in `src/navigation/grid.ts`). The whole engine runs inside **SpacetimeDB reducers**; a 250 ms scheduled `tick` reducer advances up to 4 runs, ≤ 8 steps each.
- `intelligence/` — persona generator, decision worker, providers (`jev`, `jev-batch`, `laya` local MLX, `mock`), A/B coordinator + stats.
- `experience/` — React 19 + Vite + **PixiJS 8** isometric operator UI, A/B results pages.
- A byte-identical, SHA-pinned contract file (`contract/behavior-v1.ts`) shared by all three. (Same idea as our `contracts/`.)

## Agent model
- Per person: position, velocity, 11-state enum (walking/browsing/queueing/riding/eating…), target, needs {hunger, fatigue, patience, fun} 0–100, experience value, rating, bounded memory of 32 observed facts. Groups own wallet, plan, route, pending decision.
- Persona frozen at generation: archetype (6), age, walk speed, thrill preference, hunger/fatigue/patience rates, budget, must-do places, has-app, backstory.
- **Decisions are event-driven, not per tick.** A group asks for a decision only at "moments" (`what_next`, `join_line`, `hungry_tired` with cooldown, `noticed`, `forced_replan`, `closing_soon`). The engine builds an observation (only observed facts + precomputed walk-time estimates) and a validated option menu; the policy returns a **probability vector over options**; the engine samples with a seeded hash `(seed, group, moment, seq)`. Movement, queues, money, capacity are mechanical.
- **No LLM for persona seeding**: traits sampled in code; backstories are templates (an LLM hook exists but is unimplemented). Runtime choices go to Jev (batched 16 per HTTP call, ~0.2–0.3 s), a local MLX model (batch 8–16, logits→softmax), or an in-process mock policy (hand-tuned weights). Three interchangeable providers, labeled per decision.
- Tick: 5 s logical step = 7 phases (prepare → requests → barrier → apply → dispatch → integrate → persist); `integrate` = 20 × 250 ms motion substeps.

## Scale and speed (their measured numbers, `integration/INTEGRATION_REPORT.md`)
- 1,000 mock guests at ~60× real time; 1,500 at ~40–50×; live cloud policy: 300 guests ≈ 7×, 1,000 ≈ 4.5×.
- Tricks: per-destination Dijkstra distance fields cached once, recomputed only on closures; bounded local fields for wandering; 2 m spatial bins; motion chunked at 2,048 agents/work unit; mock decisions in-process; hashing every 30 sim-s; dirty-row-only persistence; bounded evidence history.
- Devpost says "thousands"; measured concurrency is 1,000–1,500.

## Renderer
- PixiJS 8, 2:1 dimetric isometric (`px = x − y`, `py = (x+y)/2 − 1.22z`), not a map. One procedurally painted atlas (8 skins × 4 poses) so all guests draw in one batch; baked ground/shadow/light textures; LOD `MIN_FIGURE_PX = 9.5` so crowds stay legible; day/night tint. 60 fps at 400 guests; ~500+ on screen in shots.
- Transport: SpacetimeDB WebSocket subscription on a per-caller view returning one JSON `LiveSnapshot` row per run, republished at most every 150 ms (~1 MB at 1,500 guests). Client diffs rows into snapshot/patch; keeps object identity for unchanged agents.
- Interpolation: trailing adaptive clock (buffer ≈ 1.35× sample gap), 64-sample motion history per guest, no extrapolation through blocked cells, ≤ 4 s extrapolation, critically damped spring for corrections, hard snaps on discontinuities. Scrubbing uses compact replay frames (int16 tuples, ~75 B/guest, every 15–30 s).

## A/B UX and metrics
- Pick Arm A/B scenario presets (baseline $15 pass, $25, closure, board-only, app message), crowd slider 100–2,000, archetype mix, N paired seeds, provider. Same population + seed per pair; only the scenario differs.
- Report: per-pair table, per-metric A / B / B−A, paired summary (mean, min, max, SD, optional paired-t), neutral wording ("min/max are spread, not confidence bounds"), CSV/JSON export. 11 metrics (revenue, satisfaction, queue minutes, abandonment, utilization…).

## What judges likely rewarded
Dense legible crowd + KPI dashboard + a **guest inspector** that exposes the options, probabilities and provider behind each decision + an honest limitations section. Visual polish, legible causality, scale numbers. Not raw accuracy.

## What Ember takes (mapped to our code)
1. **Decide at moments, move every tick.** Our households decide only on triggers (order received, road closed, hazard seen); numpy moves them. Already the shape of `queue_traffic.py`; keep it.
2. **Procedural personas, no LLM.** Our household sampler does this. Add a templated one-line "backstory" for the inspector only, if time.
3. **Distance fields per destination, recomputed only on closures.** Exactly `World.routing_table()`; keep next-hop tables, never per-agent pathfinding.
4. **Probability-vector + seeded sampling contract** for any policy we add (e.g., compliance, pickup acceptance): engine samples with `hash(seed, household, moment)` → deterministic, replayable, A/B-pairable across Daytona runs.
5. **Paired-seed A/B with neutral deltas.** Our before/after must use the same households and seed; report B−A per metric and label spread honestly. This is the robust-plan scatter's companion table.
6. **Compact replay frames + scrubber.** Our `trajectories.json` (seconds since start) feeds deck.gl TripsLayer; add int16 frames every 15–30 s if the file gets big.
7. **Trailing render clock; no extrapolating through closed roads.** For the live WebSocket view.
8. **Rationale string per decision + inspector.** "Order received 08:12; Skyway closed 08:40; rerouted via Clark" on click. The single most-praised feature of their demo; cheap for us because the engine already knows why.
9. **Label provenance.** Which numbers are synthetic, which runs used which provider. Their honesty section was part of why they won.
