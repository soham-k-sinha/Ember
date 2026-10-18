# allston_plume_v1 — assumptions

A second hazard on the same engine (D94): same town, roads, household ids, planner, simulator and baseline as `allston_flood_v1`; only the hazard and the rescue problem differ. **Everything here is synthetic**: no real release, no dispersion model, no real fleet. On stage and in the write-up: "a synthetic drill on the real map."

| Item | Value | Why | What would change it |
|---|---|---|---|
| Release point | Storage tank 180 m south of the Treehouse (`town.json` asset 9, OSM `storage_tank`, contents unknown) | The only mapped tank next to the venue; we assume nothing about what it holds. | A real facility's hazardous-materials inventory (Tier II reports). |
| Plume shape | `GrowingEllipseHazard` (engine `hazards.py`): starts 60 m across at t=5 min, semi-major axis grows 0.1 m/s, length/breadth 2.5, drifts downwind | The engine's existing hazard interface (`polygon_at(t_s)`); a shape, not chemistry. | A dispersion model (ALOHA / CAMEO) for a named chemical and weather. |
| Wind | From the west (`heading_deg` 90): the plume crosses Western Ave and the Charles toward Riverside | Puts the plume over the densest no-car households in the box; prevailing Boston winds are westerly much of the year. | Observed wind on the day. |
| Sampling | `polygon_at` every 5 min becomes a keyframe (`keyframe_every_s` 300), the same timed extents the flood uses | The planner and simulator read every hazard as timed extents; a road closes when the plume touches it. | Finer sampling (closures up to 5 min late today). |
| Horizon, margin | 2 h (`t_end_s` 7200), `deadline_margin_s` 600 | A household must be out 10 min before the plume reaches its street. | Field guidance for shelter-in-place vs evacuate. |
| Households | 22 known (54 people, 6 needing the accessible van) + the judge (needs unknown): carless elderly, mobility or medical households from `town.json` whose street the plume reaches between 45 and 115 min, one per street corner | Spread of deadlines from 35 to 105 min; listed by household id, so the baseline's arrival order is neutral. | A real registry of residents who need help to leave. |
| Fleet | Van 1, Van 2, Accessible Van 3 (6 seats each) at EMS Station 14; reserve 1 van | Few enough that the order of pickups decides who is reached. | A real EMS/municipal fleet list. |
| Drop-off | Boston EMS Station 14 (real station, upwind), `capacity_people` 80 | Upwind of every keyframe; using it as the drill's base is our choice. | The city's actual reception centre. |
| Not modelled | Shelter-in-place, exposure dose, people walking out on their own, background traffic, power or wastewater | Kept small: this scenario shows the engine is not flood-only, nothing more. | — |
