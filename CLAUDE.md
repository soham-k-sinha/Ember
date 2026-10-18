# CLAUDE.md — Ember (HackHarvard 2026)

Read this before touching anything. It is short on purpose.

## What this is
A city-scale disaster simulation around the David Rubenstein Treehouse (Harvard, Allston). Real OSM roads and buildings, thousands of lightweight household agents, a hazard that closes roads over time, a tick-based engine, a planner that fans scenario runs out to Daytona sandboxes, and a residents layer that talks to real phones over Photon 2.0. The judge's map includes the venue.

**Start with `docs/HANDOFF.md`** (current status + next steps). Full plan: `docs/EMBER-hackharvard-2026-plan.md`. Decisions: `docs/DECISIONS.md`. Sim-env design: `docs/SIM_ENV_PLAN.md`. What the MHacks grand-prize sim did: `docs/PHYSICAL_REALITIES_NOTES.md`.

## Hard rules
1. **Contracts are the interface.** `contracts/*.schema.json` + `contracts/fixtures/`. Engine, residents and web build against fixtures; nobody blocks on anyone. Changing a contract = bump `version`, update the fixture, say so in `docs/DECISIONS.md`.
2. **No LLM in the tick loop: the AI talks, the planner decides (D76).** The simulation and the planner are deterministic numpy. LLMs live only in `residents/`: one call understands a text (free text → structured fact), one words the reply from the computed messages (a guard rejects any number, vehicle, place or street they don't contain). Routes, times, assignments are always computed, never generated.
3. **Agents are rows, not personas.** A household is attributes + a behavior rule. Responders (if the allocation variant ships) are resources in a ledger. No role-play agents.
4. **Time** is seconds since simulation start (`t_s`, float32-safe). **Coordinates** are `[lon, lat]` in GeoJSON order everywhere. Distances in meters, speeds in m/s inside the engine.
5. **Hazards implement one interface:** `polygon_at(t_s)` and `closed_edges_at(t_s)`. Fire, flood, crowd-capacity all plug in here. The engine never knows what a fire is.
6. **Engines are plug-ins** behind `Engine.step(world, t_s, dt_s, closed_mask)`. `queue_traffic` is v0. An allocation engine is a separate module, not a rewrite.
7. **2D simulation, isometric view (D50 → D71).** The map is a PixiJS isometric stage of the flood district (deck.gl on MapLibre stays as the flat fallback). No Three.js, no 3D models, no z in the engine or contracts.
8. **Daytona sandboxes cannot reach the internet on Tier 1/2.** Results come back as the `run_code` return value. Bake data into the snapshot. Always pass `timeout=`.
9. **Photon:** use Beta (Photon 2.0, `api.photon.codes/v1`). Shared iMessage lines: tester must text first; no group chats; no calls on shared lines.
10. **Label what's synthetic.** Household counts, behavior parameters, hazard timing: say it in the UI and the write-up.
11. **Calls first, one notice, nothing official (D100, D111).** Residents hear the moments that matter on a call (first contact, the pickup, a changed pickup, "2 minutes away"); texts are the written follow-up. These reach real phones, strangers included: the first call opens "Hi, this is EMBER, an automated flood-response assistant for this live demo." and the first text starts "EMBER flood response, live demo."; everything after is in-world (D111). One exception: anyone who says "this is a real emergency" gets "If this is a real emergency, please hang up and call 911." and nothing else. Never impersonate an official authority. Never ask for a YES or a DONE.

## The build plan and the team
`docs/TECHNICAL.md` is the execution plan (architecture, models, allocator, API, UI, timeline, git protocol). Each person has a self-contained brief in `docs/team/<name>.md` and an append-only feature log in `docs/log/<name>.md`. **Every session starts by reading all of `docs/log/*.md` and `docs/DECISIONS.md`, and ends each feature by appending to its own log.**

## Ownership
Aryaman owns the whole repo (D77). Branch `aryaman/<topic>`, PR, rebase-merge.

## Commands
```bash
cd engine && uv sync
uv run ember build [--dist 1200]     # OSM → data/town.json
uv run ember smoke                   # hazard + traffic, 1 sim hour, prints metrics
uv run ember render [--t 1800]       # data/town.png
uv run pytest -q
```

## Conventions
- Python 3.12, `uv`, type hints, numpy-first. Keep the hot loop free of Python per-vehicle work except the transfer step.
- Branch per person: `<name>/<topic>`. Merge to `main` only at the integration points agreed in chat.
- Secrets in `.env` (gitignored). Never commit keys.
- Commit messages: imperative, one line, what and why.

## When you finish a piece of work
Add one line to `docs/DECISIONS.md` if you made a decision; update the fixture if you changed a contract; run `uv run ember smoke` before pushing.
