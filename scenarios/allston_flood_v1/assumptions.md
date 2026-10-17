# allston_flood_v1 — assumptions

Everything in `scenario.json` that is **not** observed data. Each row: the value, why we picked it, and what would change it. Real facts and links are in `sources.md`. On stage and in the write-up: "simulation outcomes from a synthetic drill on the real map."

## District and hazard

| Item | Value | Why | What would change it |
|---|---|---|---|
| District | lon −71.1300…−71.1065, lat 42.3528…42.3722 | Smallest box holding the venue, Soldiers Field Rd, Memorial Dr, three bridges (Anderson / N Harvard St, Western Ave, River St), Cambridge Riverside and the Cottage Farm CSO facility. | A different reach of the river; a larger `town.json` box. |
| Storm length | 3 h to crest (t=10800 s), sim horizon 4 h (14400 s) | Long enough for three rescue rounds and a generator decision; short enough to replay in a 3-minute demo. | A real hydrograph (USGS Charles River gauges) for a named storm. |
| Flood mechanism | Charles overtops its low bank in the Anderson → River St reach and backs into Riverside's low streets | Climate Ready Boston groups Allston/Brighton with the "Charles River neighborhoods" exposed if the Charles River Dam is overtopped or flanked; Cambridge's 2017 vulnerability assessment names low-lying Riverside (stormwater backing up from high Charles tailwater). | A modeled inundation layer (Boston Harbor Flood Risk Model, Cambridge FloodViewer) clipped to this box. |
| t=0 | Dry (no polygon) | The engine treats "before the first keyframe" as no hazard. | — |
| t=3600 (60 min) | River channel + low bank between the Anderson and Western Ave bridges; closes 0 drive edges | "River edge paths first": the walk network is empty in the current `town.json`, so nothing on the drive graph closes yet. | Rebuilding `town.json` with the walk network (paths would then close here). |
| t=5400 (90 min) | Soldiers Field Rd + Memorial Dr between the two bridges, first Riverside side streets (Flagg, Akron, Hingham, DeWolfe); 30 edges | Riverfront parkways are the lowest roads and close first in real Charles floods; bridges kept open so the network still works. | Real low points along both parkways. |
| t=9000 (150 min) | Riverside low streets (Banks, Putnam Ave, Elmer, Callender), the **Western Ave bridge approach**, Putnam Ave substation yard; 87 edges | "One bridge approach" per the brief; Riverside is the lowest residential land in the box. | As above. |
| t=10800 (180 min, crest) | Riverside south to River St, the **River St bridge approach at Memorial Dr**, Soldiers Field Park; 136 edges | The crest takes the judge's pickup road and the generator truck's shortest route to Cottage Farm, which is the decision the demo needs. N Harvard St (Anderson bridge) stays open so the district is never cut off. | A modeled crest extent. |
| One polygon per keyframe | One contiguous pocket per time | A polygon over both banks also covers every bridge deck, so each extent is one pocket that leaves the still-open bridges outside it. The schema allows MultiPolygon if we later want separate pockets. | — |
| `t_end_s` | 14,400 s | One hour past the crest so overflow after the backup runs out shows up in the metric. | — |
| `deadline_margin_s` | 900 s | Brief default: a household must be picked up 15 min before its node floods. | Field guidance on safe margins for wheelchair users (likely longer). |

## Facilities

| Item | Value | Why | What would change it |
|---|---|---|---|
| Cottage Farm as a "pumping station" | `pumping_station` with detention storage and a pump to the interceptor | Real CSO facility on the Charles (MWRA outfall MWR201). The engine models wastewater as storage + pump + overflow (TECHNICAL §3.3). In reality it screens, disinfects and discharges *treated* CSO; we use it as the district's wastewater pinch point. | MWRA facility data (pump and treatment rates, real power supply). |
| `storage_max_m3` | 4,900 m³ (≈1.3 MG) | Detention volume reported for Cottage Farm in MWRA advisory-committee minutes found by search (link not reachable at write time; **unverified**, so treat as assumed). | MWRA's facility fact sheet. |
| `storage_m3` (initial) | 1,500 m³ | Storm already raining for a while at t=0; about one third full. | Real CSO meter data at storm start. |
| `inflow_m3ph(t)` | 3,000 → 6,000 (60 min) → 9,000 (90) → 10,000 (150) → 9,500 (180) m³/h | Scaled so a powered station keeps up and an unpowered one overflows within ~20 min. For scale: Cottage Farm's largest 2024 event discharged 21.33 MG (~80,700 m³) over a 13 h, 2.71 in storm (sources.md), ≈6,200 m³/h on average. | Real hydrograph of a design storm into Cottage Farm. |
| `pump_m3ph` | 10,500 m³/h | Just above peak inflow so that power, not pump size, decides overflow. | Real pump capacity. |
| `power_kw_required`, `connector`, `connect_s` | 350 kW, `camlock-400a`, 1,200 s | Typical portable-generator hookup class for a mid-size pump station. | The facility's actual emergency-power hookup. |
| `backup_endurance_s` | 1,800 s (30 min) | Short on-site backup so the grid loss matters inside the horizon. | Real on-site generator / fuel. |
| Overflow numbers this produces (stand-in check) | No generator: ~9,600 m³; gen-1 connected by t=9000: 0; at t=10800: ~100; at t=12600: ~4,850 | So the generator's ETA, not just its assignment, is what the allocator optimizes. | Any of the above. |
| Putnam Ave substation `events: down at t_s 7200` | 7,200 s | Pre-emptive de-energization 30 min before water reaches the yard (t=9000 in the flood); utilities de-energize flooded substations before the water arrives. | Eversource's real feeder map and flood protocol. |
| Dependencies | Cottage Farm `depends_on` the substation and outfall MWR201; Mount Auburn `depends_on` the substation | Synthetic. Gives one power failure that hits both a critical service and the wastewater system, so the generator decision trades between them. We do not know which feeders actually serve either. | The utility's feeder map. |
| Mount Auburn Hospital | `critical: true`, `backup_endurance_s` 32,400 s (9 h), 450 kW critical branch, `camlock-400a`, `connect_s` 900 | The 9 h figure is the example in TECHNICAL §3.5; it means the hospital is safe within the horizon unless an operator reports otherwise. 450 kW is a critical-branch load a portable unit could carry, not the whole hospital. | The hospital's real emergency power plan (NFPA 99/110). |
| Outfall location | MWR201 placed at the Cottage Farm node | The real discharge point is on the bank by the BU Bridge, a few hundred meters away; the graph has no node there. | — |
| Response base | Boston EMS Station 14 (real station), `capacity_people` 40 | Real emergency station at the west edge of the box; using it as the drill's base is our choice. | The city's actual staging plan. |
| Shelter | The Treehouse (venue), capacity 200 | Judges are standing in it; it stays dry in every keyframe. Designating it a shelter is synthetic. | A real designated shelter (e.g. a BPS school). |

## Resources

| Item | Value | Why | What would change it |
|---|---|---|---|
| Fleet | 2 vans + 1 accessible van (all 6 seats), 1 truck (2 seats in the cab; `validate-scenario` requires >0), 1 crew, 2 generators | From the brief: few enough that the allocator has to choose. Six mobility households (11 people) plus the judge's household means the accessible van needs at least three trips. | A real municipal/EMS fleet list. |
| Van speed | Edge free-flow speed from `town.json` | No congestion model in the rescue sim (TECHNICAL §3.3). | Ambient traffic from `queue_traffic`. |
| `service_s` | Van 300 s, accessible van 600 s, crew 1,200 s, truck 300 s | Boarding a household with bags vs. a wheelchair lift; clearing debris. | Field timings. |
| Fuel | Vans 60 L at 0.15 L/km (accessible 0.18), truck 150 L at 0.35 L/km, crew 60 L at 0.2 L/km; gen-1 400 L, gen-2 150 L | Light-duty van consumption. A 500 kW unit at ~350 kW burns roughly 95 L/h (≈0.27 L/kWh), so 400 L covers the 4 h horizon; the schema has no burn rate, so generator fuel is never binding. Fuel is a tie-breaker in the objective. | Real equipment specs. |
| gen-1 | 500 kW, `camlock-400a`, `speed_factor` 0.8 (towed), starts at the Treehouse with the truck | Compatible with both Cottage Farm and the hospital, so it is the contested resource. | — |
| gen-2 | 150 kW, `l21-30-twistlock`, `speed_factor` 0.8 | Too small and wrong connector for both: the "incompatible generator" the allocator must not send. Natural reserve. | — |
| Truck and generators stage at the Treehouse lot | — | Their shortest route to Cottage Farm crosses the River St bridge and Memorial Dr, the judge's pickup road. | — |
| Reserve rule | Keep 1 van and 1 generator unassigned when every deadline can still be met | Brief/TECHNICAL §3.5. | — |

## Households

| Item | Value | Why | What would change it |
|---|---|---|---|
| Which households | 40 ids (90 people) from `contracts/fixtures/town.fixture.json` whose drive node floods in a keyframe: 6 at t=5400 (deadline 4,500), 15 at t=9000 (8,100), 19 at t=10800 (9,900) | Spread of deadlines across the storm. Mostly carless, elderly or medical households per the synthetic `town.json` flags. | A real registry of residents who asked for help (e.g. Boston's vulnerable-resident list). |
| Household ids | Taken from the fixture (every 12th household of the seed-7 build) | `data/town.json` could not be rebuilt tonight (Overpass down, D26). The fixture's households are a subset of the same seed-7 build, so the ids exist in `town.json`. | Rebuilding `town.json` with a different seed or footprint data **changes the ids**; re-pick if so. |
| People per household | `town.json` size (1–4) | Synthetic sizes from the builder. | — |
| Mobility (accessible vehicle) | 6 households: 12048, 9000, 12720, 11352, 3384, 7956 | Brief asks for 6; picked from households already flagged `mobility` in `town.json`, spread over all three deadlines. | — |
| Unknown needs | 4 households: 10296 (**judge**), 7464, 4560, 17124 | Brief asks for 4 including the judge. The three non-judge ones are resolved by `scripted_reports` so baseline vs EMBER is reproducible without phones: t=1800 #7464 is 4 people, walking; t=2700 #4560 is 3 people incl. a walker user (**a second claim on the accessible van**); t=4200 #17124 is 2 people, one on home oxygen. The judge is never scripted: their need arrives live. | Live replies from teammates' phones instead. |
| The judge | 10296, 3 people, River St at Memorial Dr (node 61328128), deadline 9,900 s | That node is on the generator truck's shortest route to Cottage Farm and floods at the crest, so one reply ("we need an accessible vehicle and River St is blocked") changes both the judge's pickup and the generator's route/ETA. Its `town.json` flags say nothing about mobility, so the reply is new information. | — |
| Background households | Every other household in `town.json` stays on the map, not in the rescue problem | D21. | — |
