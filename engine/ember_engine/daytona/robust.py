"""Robust plan selection (TECHNICAL.md §3.7): top allocator candidates × perturbed worlds → best worst-20%.

    plan, points = robust_plan(world, scenario, reports, pool=get_pool())

The allocator's top-K different candidates (plans with the same live assignments are run once), the forecast-best
with its new generators sent at the grid trip instead of now (same rescues, so only overflow tells them apart), and the
baseline (a reference cloud for the scatter) are each run on the same M perturbed worlds (paired seeds) through
the pool. A candidate's robust score is the mean of its worst 20% of runs on people unreached, then on overflow
m³. The best robust candidate becomes the plan if it beats the forecast-best by at least MIN_GAIN people there;
otherwise the forecast-best stays (a smaller edge is noise, and every change is a text to someone).
Points stream to `on_point` as they arrive (the backend broadcasts them as WS `scatter_point` events).
"""

from __future__ import annotations

import math
import time

from ..allocator.search import Candidate, finalize, objective, search
from ..baseline import baseline_plan
from ..sim import simulate
from .jobs import make_jobs
from .pool import get_pool

WORST_SHARE = 0.2
MIN_GAIN = 1.0


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


def choose(ranking: list[dict], nominal: str) -> str:
    """The most robust candidate, unless it saves fewer than MIN_GAIN people (worst 20%) over the forecast-best."""
    worst = {r["candidate"]: r["worst20_people_unreached"] for r in ranking}
    return ranking[0]["candidate"] if worst[nominal] - worst[ranking[0]["candidate"]] >= MIN_GAIN else nominal


def distinct(cands, k: int) -> dict:
    """The first k candidates with different live assignments (a generator re-targeted to where it already is
    gives the same plan)."""
    out = {}
    for c in cands:
        out.setdefault(tuple((a["resource_id"], a["task"], str(a["target"]), a["dropoff_facility_id"])
                             for a in c.assignments if a["status"] not in ("cancelled", "rejected")), c)
    return {c.cid: c for c in list(out.values())[:k]}


def staged_at_trip(s, c):
    """c with each new generator sent when its facility's grid feed trips on the forecast instead of now: the
    conventional timing, so the robust runs price early staging in overflow m³ (D94). None if nothing changes."""
    trip = {k: b for k, (b, _) in s.ctx.power_risk.items() if b is not None and b > s.ctx.t_now}
    late = [dict(a, not_before_t_s=trip[a["target"]["facility_id"]])
            if a["task"] == "protect" and a["plan_version"] == s.version and a["target"]["facility_id"] in trip else a for a in c.assignments]
    if late == c.assignments:
        return None
    r = simulate(s.ctx.world, s.ctx.scn, {"assignments": late}, reports=s.reports, record=False)
    return Candidate(f"{c.cid}-trip", objective(r.metrics), c.pol, late, r, "generators sent at the grid trip")


def robust_plan(world, scn: dict, reports=(), t_now: float = 0.0, prev: dict | None = None, prev_reports=None,
                k: int = 4, seeds: int = 50, pool=None, on_point=None, seed: int = 0, trigger: str | None = None,
                include_baseline: bool = True, moves: int | None = None, version: int | None = None) -> tuple[dict, list]:
    t0 = time.time()
    # The published version must be used while assembling assignments, including timing variants.
    # Relabeling only Search.version after assembly hides the new generators from staged_at_trip.
    s = search(world, scn, reports, t_now, prev, prev_reports, seed, moves, version=version)
    cands = distinct(s.ranked, k)
    late = staged_at_trip(s, s.ranked[0])
    if late:
        cands[late.cid] = late
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
    chosen = cands[choose(ranking, s.ranked[0].cid)]
    plan = finalize(s, chosen, prev, trigger)
    plan["search"]["robust"] = {"batch_id": batch_id, "jobs": len(jobs), "seeds": seeds, "candidates": list(plans), "pool": "local-fallback" if getattr(pool, "fell_back", False) else pool.kind,
                                "workers": pool.workers, "startup_s": round(pool.startup_s, 2), "fanout_wall_s": round(fan_s - pool.startup_s, 2),
                                "rule": f"best mean of the worst {int(WORST_SHARE * 100)}% of runs: people unreached, then overflow m³; "
                                        f"the forecast-best stays unless that saves ≥ {MIN_GAIN:g} person",
                                "chosen": chosen.cid, "nominal_best": s.ranked[0].cid, "ranking": ranking}
    if getattr(pool, "fell_back", False) and getattr(pool, "log", None):   # never fall back silently
        plan["search"]["robust"]["fallback_reason"] = next((x for x in pool.log if "unavailable" in x), pool.log[-1])
    plan["search"]["wall_s"] = round(time.time() - t0, 3)
    return plan, points
