"""Background traffic, simulated once per scenario (D63).

The scenario's households drive out under a *staged evacuation order* keyed to the flood forecast:
each household whose home lies within `zone_buffer_m` of a flood keyframe's extent is told to leave
`lead_s` before that stage arrives (the riverside first, then each band inland); a `compliance`
share of them goes, after a lognormal mobilisation delay. A small `shadow_share` of households outside
every flood stage leaves anyway over the following two hours. All of it is synthetic and labelled.

`queue_traffic` runs that once over the whole horizon (≈0.5 s at 10 s ticks). Two products:

- `table(world, scn)`: per 5-minute bin and road, a travel-time multiplier (free-flow time × speed
  slowdown + time to clear the cars queued at the end of the road), cached on the world. The plan
  simulator and the planner look it up; nothing is simulated per candidate plan. Vans do not add to the
  traffic (they only feel it), and roads closed later by reports do not re-run it: both stated limits.
- `trails(world, scn)`: a sample of car paths for the map (playback `traffic`, v0.2).

Scenarios without `background_traffic` are untouched (table() returns None).
"""

from __future__ import annotations

import numpy as np

from .engines import QueueTrafficEngine
from .engines.queue_traffic import EXITED, EXPOSED, QUEUED, STUCK, WAITING
from .hazards import hazard_from_scenario
from .scenario import first_flooded_at, flood_keyframes
from .scheduler import Simulation

BIN_S = 300.0
DT_S = 10.0
MAX_MULT = 8.0
DEFAULTS = {"lead_s": 1800.0, "compliance": 0.8, "shadow_share": 0.15, "mobilization_median_s": 900.0,
            "mobilization_sigma": 0.6, "zone_buffer_m": 150.0, "seed": 7}


def config(scn: dict) -> dict | None:
    bt = scn.get("background_traffic")
    if not bt:
        return None
    return {**DEFAULTS, **bt}


def departures(world, scn: dict, hh_rows: np.ndarray, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """(departure time per vehicle household (inf = stays), order time (nan = no order)) under the staged rule."""
    rng = np.random.default_rng(int(cfg["seed"]))
    frames = [(t, g.buffer(float(cfg["zone_buffer_m"]))) for t, g in flood_keyframes(scn, world)]
    nodes = world.hh_node[hh_rows]
    x, y = world.node_x[nodes], world.node_y[nodes]
    stage_t = first_flooded_at(frames, x, y) if frames else np.full(len(nodes), np.nan)
    order = stage_t - float(cfg["lead_s"])
    first = float(frames[0][0]) if frames else 0.0
    n = len(nodes)
    goes = rng.random(n) < float(cfg["compliance"])
    shadow = np.isnan(order) & (rng.random(n) < float(cfg["shadow_share"]))
    order = np.where(shadow, first - float(cfg["lead_s"]) + rng.uniform(0, 7200, n), order)
    goes = np.where(shadow, True, goes & ~np.isnan(order))
    mob = rng.lognormal(np.log(float(cfg["mobilization_median_s"])), float(cfg["mobilization_sigma"]), n)
    depart = np.where(goes, np.maximum(order, 0.0) + mob, np.inf)
    return depart, order


def run(world, scn: dict, n_trails: int = 0) -> dict:
    """One background run: travel-time multiplier table (bins × edges), metrics, and optionally trails."""
    cfg = config(scn) or dict(DEFAULTS)
    T = float(scn["t_end_s"])
    eng = QueueTrafficEngine(n_traj=n_trails)
    sim = Simulation(world, hazard_from_scenario(world, scn), eng, plan={"order_t_s": 0.0},
                     scenario={"seed": int(cfg["seed"]), "compliance": 1.0}, dt_s=DT_S)
    eng.depart, order = departures(world, scn, eng.hh, cfg)
    if n_trails:  # sample the cars that actually drive
        movers = np.where(np.isfinite(eng.depart))[0]
        pick = np.random.default_rng(int(cfg["seed"]) + 1).choice(movers, size=min(n_trails, len(movers)), replace=False)
        eng.traj_idx = np.sort(pick)
    nb = int(np.ceil(T / BIN_S))
    E = world.n_edges
    mult_sum = np.zeros((nb, E))
    ticks = np.zeros(nb)
    cap_s = np.maximum(world.edge_cap_vph / 3600.0, 1e-6)
    tt = np.maximum(world.edge_tt, 1e-3)
    every = max(1, int(round(20.0 / DT_S)))
    n = 0
    while sim.t < T:
        if n_trails and n % every == 0:
            eng.snapshot(world, sim.t)
        b = min(int(sim.t // BIN_S), nb - 1)
        sim.step()
        n += 1
        occ = eng.count / np.maximum(eng.storage, 1.0)
        slow = 1.0 / np.clip(1.0 - 0.8 * occ, 0.2, 1.0)
        queued = np.bincount(eng.edge[eng.state == QUEUED], minlength=E) if (eng.state == QUEUED).any() else np.zeros(E)
        mult_sum[b] += np.minimum(slow + queued / cap_s / tt, MAX_MULT)
        ticks[b] += 1
    mult = (mult_sum / np.maximum(ticks, 1)[:, None]).astype(np.float32)
    mult[ticks == 0] = 1.0
    s = eng.state
    ordered = ~np.isnan(order)
    out = {
        "bin_s": BIN_S,
        "mult": mult,
        "config": cfg,
        "metrics": {"vehicles": int(eng.N), "ordered": int(ordered.sum()), "departed": int((s != WAITING).sum()),
                    "exited": int((s == EXITED).sum()), "exposed": int((s == EXPOSED).sum()), "stuck": int((s == STUCK).sum()),
                    "max_queue_veh": int(eng.max_queue), "roads_slowed_2x": int((mult.max(0) >= 2).sum())},
    }
    if n_trails:
        eng.snapshot(world, sim.t)
        out["trails"] = eng.trajectories(world)
    return out


def table(world, scn: dict) -> np.ndarray | None:
    """Travel-time multiplier per (5-min bin, edge) for this scenario, computed once and cached on the world."""
    cfg = config(scn)
    if cfg is None:
        return None
    key = (scn.get("scenario_id"), tuple(sorted((k, str(v)) for k, v in cfg.items())), float(scn["t_end_s"]))
    cache = world.__dict__.setdefault("_traffic_cache", {})
    if key not in cache:
        cache[key] = run(world, scn)["mult"]
    return cache[key]


def bin_of(t: float, mult: np.ndarray) -> int:
    return int(min(max(t, 0.0) // BIN_S, len(mult) - 1))
