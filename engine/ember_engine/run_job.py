"""The Daytona contract: run_job(world, job) -> metrics. Pure, no I/O, no network.

job = {"plan": {...}, "scenario": {...}}   (see contracts/job.schema.json)
"""

from __future__ import annotations

from .engines import QueueTrafficEngine
from .hazards import hazard_from_scenario
from .scheduler import Simulation


def run_job(world, job: dict, with_trajectories: bool = False) -> dict:
    plan = job.get("plan", {})
    scenario = job.get("scenario", {})
    hazard = hazard_from_scenario(world, scenario)
    engine = QueueTrafficEngine(n_traj=int(scenario.get("n_traj", 1500 if with_trajectories else 0)))
    sim = Simulation(world, hazard, engine, plan=plan, scenario=scenario,
                     dt_s=float(scenario.get("dt_s", 10.0)), seed=int(scenario.get("seed", 1)))
    metrics = sim.run(T_s=float(scenario.get("T_s", 10800.0)), snapshot_every=int(scenario.get("snapshot_every", 6)))
    metrics["plan_id"] = plan.get("plan_id")
    metrics["scenario_id"] = scenario.get("scenario_id")
    if with_trajectories:
        metrics["_trajectories"] = engine.trajectories(world)
        metrics["_snapshots"] = sim.snapshots
    return metrics


def default_job(world, heading_deg: float = 90.0, speed_mps: float = 0.6, compliance: float = 1.0,
                staged: bool = False, T_s: float = 10800.0) -> dict:
    """A sensible default: ignition at the venue, front moving `heading_deg`, 3 simulated hours."""
    zone_offsets = {str(z["id"]): 0.0 for z in world.zones}
    if staged:
        for i, z in enumerate(world.zones):
            zone_offsets[str(z["id"])] = 300.0 * (i % 4)
    return {
        "plan": {"plan_id": "staged" if staged else "immediate", "mode": "staged" if staged else "immediate",
                 "order_t_s": 0.0, "zone_offsets_s": zone_offsets, "closed_edges": []},
        "scenario": {"scenario_id": f"ellipse_h{int(heading_deg)}", "seed": 1, "T_s": T_s, "dt_s": 10.0,
                     "compliance": compliance, "mobilization_median_s": 900.0, "mobilization_sigma": 0.6,
                     "hazard": {"type": "ellipse", "center": [world.venue.get("lon", world.center[0]), world.venue.get("lat", world.center[1])],
                                "start_t_s": 0.0, "speed_mps": speed_mps, "heading_deg": heading_deg, "ratio": 2.5}},
    }
