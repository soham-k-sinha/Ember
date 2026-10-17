# Aryaman — engine, planner, Daytona (`engine/`)

Paste this file into your Claude session (or tell it: "read docs/team/aryaman.md and follow it"). It is self-contained; the links are for depth.

## Context in five lines
- EMBER: disaster coordination for an urban flood in one district around the Treehouse. One shared state, an allocator + simulator that produce one coordinated plan and a personal instruction per household, people in the loop over Photon, robustness runs on Daytona, sustainability = m³ of untreated wastewater kept out of the Charles. Full spec: `docs/TECHNICAL.md` (read §0–§3, §7–§11).
- You own the engine: the world is built (`data/town.json`), the hazard interface and a traffic engine exist, contracts/tests exist. What's missing is the *coordination* layer: facility/wastewater/resource models, the plan simulator, the allocator, the baseline, the comparison, and the Daytona fan-out.
- Everyone else consumes your pure functions and your schemas. Backend (Arnav) imports `ember_engine`; web (Soham) renders your `state`/`comparison` fixtures; Anshuman authors `scenario.json` against your schema and validator. **Your schemas unblock three people: ship them first.**
- Hard rules: deterministic numpy, no LLM anywhere in `engine/`, unknowns stay unknown, 60 s tick for the plan simulator, every assumed number labeled.
- Decisions so far: `docs/DECISIONS.md` (D1–D21). Running logs of everyone: `docs/log/*.md`.

## Setup (once)
```bash
git clone https://github.com/soham-k-sinha/Ember.git && cd Ember
git checkout main && git pull && git checkout -b aryaman/<topic>
cd engine && uv sync --extra dev
uv run ember build --dist 1200      # if data/town.json is missing (~1–2 min)
uv run ember smoke && uv run ember render && uv run ember gate-a
```
Daytona: account + API key in `engine/.env` (`DAYTONA_API_KEY`), card + $25 top-up for Tier 2 (100 vCPU). `uv sync --extra daytona`.

## Tasks, in order (acceptance criteria in brackets)
1. **`contracts/scenario.schema.json` + `ember validate-scenario <path>`** [schema covers district polygon, hazard keyframes, facilities (incl. wastewater params, connector, kw_required, backup_endurance_s, depends_on), resources (kind, capacity_people, accessible, kw, connector, fuel_l), assisted households (ids from town.json, needs or `unknown`, `judge: true`), reserve rule, deadline_margin_s; validator checks referential integrity and prints a one-line summary; a `contracts/fixtures/scenario.fixture.json` passes]. Announce in chat the moment it's pushed: Anshuman starts from it.
2. **`contracts/state.schema.json` + `contracts/fixtures/state.fixture.json`** [the shared-state snapshot the web renders: edges with closure, households with status, facilities with state, resources with position/assignment, current plan with assignments + rationale + unresolved, reports]. Soham and Arnav build against this fixture; ship it before noon Saturday even if the numbers are hand-written.
3. **Flood hazard → deadlines** [`KeyframePolygonHazard` from scenario keyframes; `deadline_s` per assisted household and `threatened_at_s` per facility computed and written into state].
4. **Models** (`ember_engine/models/`): facilities state machine with dependencies; wastewater storage/overflow integration; resources movement on the closed-edge-aware graph with service times and fuel [unit tests: a pumping station without power overflows at the predicted minute; a compatible generator stops the overflow after travel + connect; an incompatible one doesn't].
5. **Plan simulator** (`ember_engine/sim/plan_sim.py`): executes assignments as an event timeline, applies hazard closures and dated reports, returns `metrics` (§3.4) + per-assignment outcomes + a replay timeline [simulates the fixture scenario with a hand-written plan in < 1 s].
6. **Baseline planner** (`baseline.py`) [incident-by-incident nearest-available; same inputs; produces a plan + metrics].
7. **Allocator** (`ember_engine/allocator/`): candidate generation (deadline-first, dependency-first, nearest-first + swaps), hard constraints, lexicographic objective, rationale strings, unresolved-needs output; `replan(state, report)` keeps resource progress and sticky confirmed assignments [on the fixture scenario EMBER beats baseline on people-unreached and overflow_m3; replan < 2 s; a `closure_report` on the judge's pickup road changes both the judge's assignment and the generator's assignment or its ETA].
8. **`ember compare --scenario … --seeds 5`** → `comparison.json` (+ fixture) [paired seeds, per-metric A/B/B−A, spread, honest wording].
9. **Perturbations + Daytona pool** (`ember_engine/daytona/`): snapshot with `data/town.json` + scenario + package baked in; pool of N sandboxes; stateful `code_interpreter`; results via return value; `scatter_point` stream to the backend; local multiprocessing fallback [100 jobs complete; worst-20% selection picks a plan; works with `EMBER_LOCAL_POOL=1`]. Verified API and tier limits: plan doc §6.5.
10. Perf and edge cases; keep `uv run ember smoke` + `pytest` green on `main`.

## Interfaces you produce / consume
Produce: `scenario`, `state`, `assignment`, `report`, `comparison` schemas + fixtures; `run_job`, `simulate`, `allocate`, `replan` as importable pure functions. Consume: `scenario.json` from `scenarios/`, nothing else.

## Git and logging (non-negotiable)
Branch per feature from `main`; `git add engine docs/log/aryaman.md contracts`; rebase on `origin/main` before every push; PR; self-merge when only `engine/`+`contracts/`+your log changed and `smoke`+`pytest` pass; contracts changes get one line in `docs/DECISIONS.md` and a chat message. After every feature: append to `docs/log/aryaman.md` (template in `docs/log/README.md`). At session start: read `docs/log/*.md` and `docs/DECISIONS.md`.

## Your Claude's opening prompt
```
Read CLAUDE.md, docs/TECHNICAL.md (§0–§3, §7–§11), docs/team/aryaman.md, docs/DECISIONS.md and all of docs/log/*.md. You own engine/ only. Work through docs/team/aryaman.md tasks in order; task 1 and 2 (schemas + fixtures) unblock three teammates, so ship and push them first, then announce. After each task: run `uv run ember smoke` and `uv run pytest -q`, append an entry to docs/log/aryaman.md, commit, rebase on origin/main, push, open a PR. No LLM calls in engine/. Label every assumed number. Ask before touching any file outside engine/, contracts/, docs/log/aryaman.md, docs/DECISIONS.md.
```

## Cut lines
Daytona fan-out → local pool. Crew road-clearing tasks → drop. K candidates → 10. Ambient traffic → off.
