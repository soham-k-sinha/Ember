# Arnav — web log (`web/`)

## 2026-10-17 03:35 · operator map and panels · branch arnav/operator-ui · commit afdebe2
What: Vite + React + deck.gl 9.4 map of the town fixture (roads, venue star, households) on CARTO Positron, with a sim clock that steps scenario flood keyframes and turns closed edges red. Panels read `state.fixture.json`: resource ledger, inspector with rationale verbatim, resident and operator threads, unresolved needs, plan-version list, and a comparison/scatter shell. Live mode calls GET /state, WS /ws, POST /disruption, POST /replan, POST /simulate, and GET /comparison, and the fixture toggle drops back to the contracts. Ambient trips stay off unless checked.
Files: web/src/App.tsx, web/src/layers.ts, web/src/model.ts, web/src/live.ts, web/src/components/MapView.tsx, web/src/components/Panels.tsx, docs/log/arnav.md
Run: cd web && npm install && npm run dev
Interfaces: consumes town, scenario, state, assignment, report, trajectories v0.1. comparison and ws-events are not published; the panels render them when GET /comparison or a scatter_point arrives. changed: none
Status: done for the published fixtures. Comparison has no fixture, so that table stays empty until the backend or a fixture exists. Resource positions are the 80 min snapshot; the clock moves flood and closures. Later keyframes close extra edges by the same line-intersection rule (122/122 match on the published keyframe).
Next: point Live at Soham's API once GET /state is up, and fill the comparison table from GET /comparison.

## 2026-10-17 03:40 · ledger ETA fallback · branch arnav/operator-ui · commit c418714
What: the resource ledger uses the assignment ETA when the resource's own eta_s is null, which is how stalled vans are recorded in the updated state fixture.
Files: web/src/components/Panels.tsx
Run: cd web && npm run dev
Interfaces: consumes state v0.1; changed: none
Status: done
Next: same as above
