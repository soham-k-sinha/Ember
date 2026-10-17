# Soham — map and operator UI (`web/`)

Paste this file into your Claude session (or: "read docs/team/soham.md and follow it").

## Context in five lines
- EMBER: disaster coordination for an urban flood in one district around the David Rubenstein Treehouse (the venue). One shared state, an allocator + simulator producing one coordinated plan and a personal instruction per household, real people in the loop over Photon, robustness runs on Daytona, sustainability = m³ of untreated wastewater kept out of the Charles. Spec: `docs/TECHNICAL.md` (read §0–§2, §5, §7–§11).
- You own everything the judge *sees*: the live map and the panels (ledger, inspector, conversations, plan versions, comparison, scatter). The judge's map must include the venue.
- You build against fixtures first (`contracts/fixtures/*.json`), then the backend's `GET /state` and `WS /ws`. The UI must run with no backend at all.
- Stack is fixed: Vite + React + TypeScript, deck.gl 9.4 with `@deck.gl/maplibre` and `react-map-gl/maplibre`, CARTO basemap (no token). 2D only. TripsLayer timestamps are seconds since sim start (float32-safe). Verified API notes: `docs/EMBER-hackharvard-2026-plan.md` §6.9.
- What the MHacks grand-prize sim got praised for and we copy: a dense legible map, KPI numbers, and an **inspector that shows the rationale behind each decision** (`docs/PHYSICAL_REALITIES_NOTES.md`).

## Setup (once)
```bash
git clone https://github.com/soham-k-sinha/Ember.git && cd Ember
git checkout main && git pull && git checkout -b soham/<topic>
cd web && npm create vite@latest . -- --template react-ts   # only if web/ is empty
npm i deck.gl @deck.gl/maplibre @deck.gl/layers @deck.gl/geo-layers @deck.gl/react react-map-gl maplibre-gl
npm run dev
```

## Tasks, in order (acceptance in brackets)
1. **Map skeleton** [renders `contracts/fixtures/town.fixture.json`: roads (PathLayer), the venue star, households as dots; CARTO Positron basemap; phone-width layout tolerable].
2. **Flood + closures** [PolygonLayer from the scenario keyframes driven by a sim clock (play/pause/scrub); closed edges red; the clock is the single source of truth for every layer].
3. **State layers from `state.fixture.json`** [assisted households colored by status with the judge highlighted; facilities with a state badge (ok/backup/down); resources as dots moving along `route_edges` interpolated between snapshots; assignments as ArcLayer resource → target].
4. **Panels** [resource ledger (kind, status, assignment, ETA, fuel); household/facility inspector on click (status, needs, dependencies, **rationale string verbatim**, its message thread); conversation history (resident + operator threads); unresolved needs list with the blocking constraint].
5. **Live mode** [`GET /state` + `WS /ws` events `state, plan, assignment, message, report, scatter_point, metrics` from Arnav's backend; a toggle falls back to fixtures].
6. **Controls** ["close this road" (click an edge → `POST /disruption`), "replan", "run comparison"].
7. **Comparison panel** [baseline vs EMBER per metric with B−A, from `comparison.fixture.json` then `GET /comparison`; wording: "spread, not confidence bounds"; plan-version timeline v1→v2→v3 with what changed].
8. **Scatter** [robustness runs filling live from `scatter_point` events; highlight the chosen plan].
9. Polish: empty states, loading, screenshot-ready colors, 1920×1080 demo layout.

## Interfaces you consume / produce
Consume: `town`, `scenario`, `state`, `assignment`, `comparison`, `ws-events` (schemas + fixtures in `contracts/`, owned by engine). Produce: nothing others import. If a fixture is missing a field you need, ask Aryaman in chat; don't hand-edit fixtures.

## Git and logging (non-negotiable)
Branch per feature from `main`; `git add web docs/log/soham.md`; rebase on `origin/main` before every push; PR; self-merge when only `web/` + your log changed and `npm run build` passes. After every feature: append to `docs/log/soham.md` (template in `docs/log/README.md`). At session start: read `docs/log/*.md` and `docs/DECISIONS.md`. Never edit `engine/`, `residents/`, `scenarios/`, or fixtures.

## Your Claude's opening prompt
```
Read CLAUDE.md, docs/TECHNICAL.md (§0–§2, §5, §7–§11), docs/team/soham.md, docs/DECISIONS.md and all of docs/log/*.md. You own web/ only. Work through docs/team/soham.md tasks in order, building against contracts/fixtures first; the app must run with no backend. After each task: `npm run build`, append an entry to docs/log/soham.md, commit, rebase on origin/main, push, open a PR. deck.gl 9.4 on MapLibre, 2D only, no Mapbox token, no Three.js. If a fixture lacks a field, ask in chat rather than editing it.
```

## Cut lines
Scatter animation → static chart. Ambient trips → off. Plan-version timeline → a list.
