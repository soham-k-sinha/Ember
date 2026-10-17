# Decision log

One line per decision, newest at the bottom. Format: `D<n> · date · decision · why · status`.
If you reverse one, add a new line referencing it; never delete.

| # | Date | Decision | Why | Status |
|---|---|---|---|---|
| D1 | 2026-10-16 | Genre: a city-scale disaster simulation around the venue (floods / infrastructure cascades / evacuation), with real phones in the loop. | Matches what wins at HackHarvard/TreeHacks/HackMIT: custom engine under a map, named vulnerable user, product that acts, judge participates. Boston audience relates to the map. | Locked |
| D2 | 2026-10-16 | Map = ~1.2 km radius around the David Rubenstein Treehouse (Allston / Harvard Square / Charles River bridges), from OpenStreetMap. Paradise, CA kept only as a possible calibration slide. | Judges see the building they're in. OSM has roads, footways, buildings, hospitals, substations, pumping stations. | Locked |
| D3 | 2026-10-16 | Population = one household per residential footprint (incl. dormitories as no-car households), with size, vehicles, vulnerability flags. Lightweight agents (rows + rules), no LLM personas, no role-play responders. | Thousands of agents must tick in numpy; personas add cost and nothing judges can verify. | Locked |
| D4 | 2026-10-16 | Hazard interface: `polygon_at(t)` + `closed_edges_at(t)`. Fire (growing wind-driven ellipse), flood (keyframed extent polygons from public layers), crowd capacity all implement it. The engine never knows the hazard type. | Lets us pick the demo hazard Saturday without touching the engine. | Locked |
| D5 | 2026-10-16 | Engine is a plug-in behind `Engine.step(...)`. v0 = per-edge queue traffic model with spillback (10 s ticks). An allocation/dependency engine (Lifeline variant) would be a second module. | Foundation first; idea variants swap one module. | Locked |
| D6 | 2026-10-16 | No multi-agent LLM orchestration (no Situation/Rescue/Infra/Coordinator agents). One deterministic engine/allocator + one LLM call in `residents/` for free text ↔ structured need. | Nondeterministic demos die on stage; "agents discussing a disaster" is the thing judges punish. | Locked |
| D7 | 2026-10-16 | Water/sewer modeled as points + dependency edges (pumping station → outfall), not pipe networks. | OSM has no pipes; MWRA publishes CSO outfalls and per-storm discharge volumes, which is enough for a cascade and is real. | Locked |
| D8 | 2026-10-16 | Renderer: deck.gl 9.4 on MapLibre (CARTO basemap, no token), 2D. Trajectories use seconds-since-start (float32-safe). | Verified in docs; 3D is a time sink with no credibility gain. | Locked |
| D9 | 2026-10-16 | Sponsors: Daytona pool for scenario fan-out (structural); Photon 2.0 **Beta** for residents (structural); Save the Earth is the anchor track; SpaceXAI only if voice ships (FIRMS/satellite inputs stay regardless); skip Chalk, Factory, Nessie, Hardware, Digital Trust, Clinical Trials. | Verified briefs and limits; no bolt-ons. | Locked |
| D10 | 2026-10-16 | Daytona: pool of N long-lived sandboxes (N = tier vCPU pool), graph baked into snapshot, stateful `code_interpreter`, results via return value. Get Tier 2 (card + $25) Friday. | Tier 1 = 10 vCPU; sandboxes can't egress on Tier 1/2. | Locked |
| D11 | 2026-10-16 | Repo: monorepo, one owned directory per person, contracts + fixtures committed first, branch per person, merges only at integration points. | Three people, no blocking. | Locked |
| D12 | 2026-10-16 | Venue closes 8 PM nightly; real build windows are Fri 4–8, Sat ~9–8, plus lodging. Gates: Fri night = map renders + fixture animation + Daytona JSON + one phone message; Sat AM = Gate A (rotate hazard 90°, a different exit closes first). | From the opening-ceremony deck. | Locked |
| — | — | **Open:** demo hazard (flood vs fire vs crowd), engine variant (evacuation vs Lifeline allocation vs crowd), project name, whether Paradise calibration slide stays. Decide Saturday morning. | | Open |
