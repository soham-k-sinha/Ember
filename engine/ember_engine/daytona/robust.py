"""Robust plan selection (TECHNICAL.md §3.7): top allocator candidates × perturbed worlds → best worst-20%.

    plan, points = robust_plan(world, scenario, reports, pool=get_pool())

The allocator's top-K candidates (and the baseline, as a reference cloud for the scatter) are each run on
the same M perturbed worlds (paired seeds) through the pool. A candidate's robust score is the mean of its
worst 20% of runs on people unreached, then on overflow m³; the best robust candidate becomes the plan.
Points stream to `on_point` as they arrive (the backend broadcasts them as WS `scatter_point` events).
"""

from __future__ import annotations

import math
import time

from ..allocator.search import finalize, search
from ..baseline import baseline_plan
from .jobs import make_jobs
from .pool import get_pool

WORST_SHARE = 0.2


def worst_mean(values: list[float], share: float = WORST_SHARE) -> float:
    k = max(1, math.ceil(share * len(values)))
    return sum(sorted(values, reverse=True)[:k]) / k


def robust_rank(points: list[dict], exclude=("baseline",)) -> list[dict]:
    by = {}
    for p in points:
        by.setdefault(p["candidate"], []).append(p["metrics"])
    rows = []
    for cid, ms in by.items():
        un = [m["people_unreached"] for m in ms]
        ov = [m["overflow_m3"] for m in ms]
        rows.append({"candidate": cid, "runs": len(ms), "eligible": cid not in exclude,
                     "worst20_people_unreached": round(worst_mean(un), 2), "worst20_overflow_m3": round(worst_mean(ov), 1),
                     "mean_people_unreached": round(sum(un) / len(un), 2), "mean_overflow_m3": round(sum(ov) / len(ov), 1),
                     "max_people_unreached": max(un)})
    rows.sort(key=lambda r: (not r["eligible"], r["worst20_people_unreached"], r["worst20_overflow_m3"],
                             r["mean_people_unreached"], r["mean_overflow_m3"], r["candidate"]))
    return rows


def robust_plan(world, scn: dict, reports=(), t_now: float = 0.0, prev: dict | None = None, prev_reports=None,
                k: int = 4, seeds: int = 20, pool=None, on_point=None, seed: int = 0, trigger: str | None = None,
                include_baseline: bool = True) -> tuple[dict, list]:
    t0 = time.time()
    s = search(world, scn, reports, t_now, prev, prev_reports, seed)
    cands = {c.cid: c for c in s.ranked[:k]}
    plans = {cid: {"assignments": c.assignments} for cid, c in cands.items()}
    if include_baseline:
        plans["baseline"] = baseline_plan(world, scn, s.reports)
    batch_id = f"v{s.version}"
    jobs = make_jobs(batch_id, list(plans), list(range(1, seeds + 1)), scn, world.n_edges)
    labels = {cid: c.pol.label() + (f" ({c.note})" if c.note else "") for cid, c in cands.items()} | {"baseline": "incident-by-incident baseline"}

    def emit(p):
        p.update(n_total=len(jobs), plan_version=s.version, candidate_label=labels[p["candidate"]])
        if on_point:
            on_point(p)

    own = pool is None
    pool = pool or get_pool(world=world)
    try:
        t1 = time.time()
        points = pool.run(batch_id, scn, plans, s.reports, jobs, on_point=emit)
        fan_s = time.time() - t1
    finally:
        if own:
            pool.close()
    points.sort(key=lambda p: p["run_id"])
    ranking = robust_rank(points)
    chosen = cands[ranking[0]["candidate"]]
    plan = finalize(s, chosen, prev, trigger)
    plan["search"]["robust"] = {"batch_id": batch_id, "jobs": len(jobs), "seeds": seeds, "candidates": list(plans), "pool": "local-fallback" if getattr(pool, "fell_back", False) else pool.kind,
                                "workers": getattr(pool, "n", None) or getattr(pool, "workers", None), "fanout_wall_s": round(fan_s, 2),
                                "rule": f"best mean of the worst {int(WORST_SHARE * 100)}% of runs: people unreached, then overflow m³",
                                "chosen": chosen.cid, "nominal_best": s.ranked[0].cid, "ranking": ranking}
    plan["search"]["wall_s"] = round(time.time() - t0, 3)
    return plan, points
