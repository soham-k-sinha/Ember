# Simulated environment: implementation plan

Goal for Friday night: a real, idea-agnostic world around the venue that ticks, closes roads under a hazard, moves thousands of agents, streams snapshots, and renders. Everything variant-specific (which hazard, which engine, which metrics) is a plug-in on top.

## 1. Layers (what we pull, what it's for)

| Layer | Source | Used by |
|---|---|---|
| Drive network (nodes, directed edges, geometry, highway class, lanes, maxspeed) | OSMnx `graph_from_point(center, dist, network_type="drive")` + `add_edge_speeds` + `add_edge_travel_times` | Traffic engine, routing, rendering |
| Walk network (footways, bridges, stairs) | OSMnx `network_type="walk"` | Crowd variant, rendering |
| Building footprints | OSMnx `features_from_point(tags={"building": True})` | Households (residential), assets (non-residential) |
| Critical assets | OSMnx tags: `amenity` in {hospital, clinic, fire_station, police}, `power` in {substation, plant}, `man_made` in {pumping_station, water_works, wastewater_plant}, `emergency` | Dependency graph (Lifeline variant), rendering |
| Venue | Geocode "David Rubenstein Treehouse" (fallback: Western Ave & N Harvard St) | Rendering, relatability |
| Exits | Boundary nodes of the drive graph (degree ≤ 2, > 90% of radius from center) | Evacuation destinations |
| Zones | k-means (k=10) on household coordinates | Staged plans |
| Hazard inputs | Fire: ellipse params. Flood: GeoJSON extents (FEMA NFHL via MassGIS, Boston Climate Ready layers). Crowd: section polygons. | `hazards.py` |

Not pulled: shops, parks, transit (unless a variant needs them). No pipes (OSM has none); water/sewer are points + dependency edges.

## 2. Data model (`contracts/town.schema.json`)

```
town.json
  meta       {version, center [lon,lat], dist_m, built_at, counts}
  nodes[]    {id, lon, lat}
  edges[]    {id, u, v, length_m, lanes, speed_kph, travel_time_s, capacity_vph, storage_veh, oneway, highway, geom [[lon,lat],...]}
  paths[]    {id, u, v, length_m, geom}                       # walk network (optional)
  households[] {id, lon, lat, building_id, node, zone, size, vehicles, flags{elderly,mobility,medical,no_car}}
  assets[]   {id, type, name, lon, lat, node}
  exits[]    node ids
  zones[]    {id, centroid [lon,lat], n_households}
  venue      {name, lon, lat, node}
```

Engine-side (`world.py`) this becomes numpy arrays: `edge_u, edge_v, edge_len, edge_tt, edge_speed, edge_cap_per_tick, edge_storage`, CSR adjacency, cumulative geometry lengths per edge (for position → lon/lat), household arrays.

Capacity rules (standard planning values, labeled synthetic): `capacity_vph = lanes × 1800`, `storage_veh = lanes × length_m / 1000 × 150`. Lanes imputed by highway class when untagged.

## 3. Households

- Residential footprint classes → households: house/detached/semi/bungalow = 1; terrace = area/90; apartments/residential = floors × area/90; dormitory = floors × area/60 with `vehicles=0, no_car=true`; unknown (`building=yes`, no amenity/shop/office) = 1 if area < 250 m² else area/120. Cap 400 per building.
- Size ~ {1:0.3, 2:0.35, 3:0.2, 4+:0.15}. Vehicles: apartments {0:0.4, 1:0.45, 2:0.15}, houses {0:0.15, 1:0.55, 2:0.30}. Flags: elderly 15%, mobility 5%, medical 3% (seeded RNG).
- Placement: footprint centroid; `node` = nearest drive node (projected cKDTree). Households with `vehicles=0` generate no vehicle in the traffic engine and are flagged `needs_transport` for the residents layer.

## 4. Tick loop (`scheduler.py`)

```
Simulation(world, hazard, engine, dt_s=10)
  step(): closed = hazard.closed_edges_at(t); engine.step(world, t, dt, closed); t += dt
  run(T, snapshot_every=6 ticks) → snapshots (closed mask, edge occupancy, vehicle states, metrics), trajectories (subsampled vehicles → [lon,lat,t])
```

Performance target: 10k vehicles × 1,080 ticks (3 h) in < 5 s on a laptop. Vectorized movement; the only Python loop is the per-tick transfer step over vehicles at edge ends (hundreds, not thousands).

## 5. Hazards (`hazards.py`)

- `GrowingEllipseHazard(center, start_t, speed_mps, heading_deg, ratio)`: wind-driven front for fire-like spread and for Gate A testing (rotate heading 90° → a different exit should close first).
- `KeyframePolygonHazard([(t, polygon)...])`: flood extents from public layers stepped over a storm timeline.
- `closed_edges_at(t)`: an edge is closed when any geometry vertex falls inside the polygon (shapely `contains_xy`, vectorized; recomputed when the polygon changes).

## 6. Engine v0 (`engines/queue_traffic.py`)

- Vehicle = household with ≥1 vehicle. State: waiting → moving → queued → exited | exposed.
- Routing: one reverse multi-source Dijkstra from all exits (scipy `csgraph.dijkstra`, `min_only`) gives `next_edge[node]`; recomputed whenever the closed set changes. No per-vehicle pathfinding.
- Departure: `zone_offset[zone] + lognormal mobilization` (median 15 min); compliance `p` = share that follows the offset, the rest leave on their own clock.
- Movement: `pos += speed × dt`; at edge end, transfer if downstream `count < storage` and this edge's per-tick capacity credit allows; else queued (spillback).
- Closure: vehicles on a newly closed edge become `exposed`; closed edges get infinite cost in routing.
- Metrics: `exposed_vehicles, clearance_s_95, max_queue_veh, vulnerable_delay_s_mean, vehicle_hours, first_closure_s, closure_order[]`.

## 7. Job runner (`run_job.py`) — the Daytona contract

`run_job(world, job) → metrics` where `job = {plan, scenario}`. Pure function, no I/O, no network. The Daytona snapshot bakes `town.json` + this package; each sandbox loads the world once and runs many jobs.

## 8. Rendering

- Fast check: `ember render` → matplotlib PNG (roads, households by zone, assets, venue, exits, hazard polygon, closed edges in red).
- Real: `web/` deck.gl TripsLayer (trajectories), PathLayer (edges colored by occupancy), PolygonLayer (hazard), ScatterplotLayer (assets, venue). Fed by `trajectories.json` first, then the live WebSocket.

## 9. Gates

- **Tonight:** `ember build` produces a town with > 5k households, > 1k edges, the venue and ≥ 5 assets; `ember smoke` runs 1 sim hour with vehicles exiting and some exposed; `ember render` shows the venue on the map.
- **Gate A (Sat AM):** rotate the ellipse heading 90°; a different exit closes first and `closure_order` changes. If not, fix the engine before any UI.
- **Sat 11 AM:** run_job → Daytona pool → scatter in web.

## 10. Known gaps / risks
- OSM `lanes`/`maxspeed` missing on many edges → imputed (say so).
- Boundary "exits" are an approximation of where the network leaves the box; hand-curate the 6–8 real ones (bridges, Western Ave, N Harvard, Soldiers Field Rd) before the demo.
- Walk graph is large; only loaded when needed.
- Flood layers: download and keyframe on Saturday if flood is chosen.
