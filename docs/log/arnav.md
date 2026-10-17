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

## 2026-10-17 04:24 · comparison panel and WS envelopes · branch arnav/operator-ui · commit c2640c8
What: the comparison table reads nominal.baseline and nominal.ember from comparison.fixture.json; B−A is EMBER minus baseline, with the seed spread labeled as spread rather than confidence bounds. The plan timeline lists plans.ember.versions and shows plan.changes for the matching version. The WebSocket client follows contracts/ws-events.schema.json on aryaman/ws-events (PR #11): every message is {type, seq, t_s, data}, and a skipped seq drops the stream and reloads GET /state. scatter_point is drawn as provisional until Soham signs off. State v0.2 fields stay optional.
Files: web/src/live.ts, web/src/components/Panels.tsx, web/src/App.tsx, web/src/types.ts, web/src/fixtures.ts, web/scripts/check-ws.ts
Run: cd web && npm run dev
Interfaces: consumes comparison v0.1 and state v0.2; consumes the proposed ws-events envelope (not merged; not residents/ws-events.schema.json). changed: none
Status: done. scatter_point shape is provisional.
Next: switch the client comment to contracts/ws-events.schema.json on main once PR #11 merges.

## 2026-10-17 04:55 · allston flood on the operator map · branch arnav/operator-ui · commit pending
What: Rebased onto main. Fixture mode draws scenarios/allston_flood_v1 (judge household #10296, Cottage Farm, Treehouse shelter) instead of the example_flood snapshot. The clock opens on the 90 min keyframe; flood polygons and closures follow that scenario. The comparison table still reads comparison.fixture.json (nominal columns, B−A = EMBER − baseline, spread not confidence bounds) until Live calls GET /comparison. The WebSocket client follows contracts/ws-events.schema.json: an assignment event is {plan_version, change, assignment_id, assignment}, and scatter_point is {run_id, batch_id, candidate, seed, metrics}. Live posts /disruption {close_edges}, /replan, and /clock, and does not call /simulate. The dev server stays on 43123; residents CORS on main already allows 43123 and 5173.
Files: web/src/opening.ts, web/src/fixtures.ts, web/src/App.tsx, web/src/live.ts, web/src/model.ts, web/src/components/Panels.tsx, web/src/types.ts, web/scripts/check-ws.ts, web/.env.example, docs/log/arnav.md
Run: cd web && npm install && npm run dev
Interfaces: consumes allston_flood_v1 (scenarios/, read-only), town and comparison fixtures, ws-events on main, state v0.2 from GET /state. changed: none
Status: done. The opening picture is placement from the scenario at t=0, not a simulated plan; Live replaces it with GET /state. scatter_point is still the D38 proposal.
Next: none for this pass.
