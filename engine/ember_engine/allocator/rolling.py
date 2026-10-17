"""EMBER as it runs live: an initial plan at t=0, then a replan whenever a report arrives.

Scripted scenario reports and live reports both trigger replans at their observed time. Returns the
final plan (what the simulator scores) and every version (the UI's plan timeline v1 → v2 → …).
"""

from __future__ import annotations

from .search import allocate


def report_times(scn: dict, reports=()) -> list[tuple[float, str]]:
    ev = [(float(r["t_s"]), f"scenario report: {r['kind']}" + (f" for household #{r['household_id']}" if "household_id" in r else "")
           + (f" for {r['facility_id']}" if "facility_id" in r else "")) for r in scn.get("scripted_reports", [])]
    ev += [(float(r["observed_at_t_s"]), f"{r.get('source', 'resident')} report {r['id']}: {r['kind']}") for r in reports]
    merged = {}
    for t, why in sorted(ev):
        merged.setdefault(t, []).append(why)
    return [(t, "; ".join(w)) for t, w in sorted(merged.items()) if t > 0]


def run_ember(world, scn: dict, reports=(), seed: int = 0, moves: int | None = None) -> tuple[dict, list]:
    reports = list(reports)
    known = [r for r in reports if float(r["observed_at_t_s"]) <= 0]
    plan = allocate(world, scn, reports=known, seed=seed, moves=moves)
    versions = [plan]
    for t, why in report_times(scn, reports):
        prev_known = known
        known = [r for r in reports if float(r["observed_at_t_s"]) <= t]
        plan = allocate(world, scn, reports=known, t_now=t, prev=plan, prev_reports=prev_known, seed=seed, moves=moves,
                        trigger=why)
        versions.append(plan)
    return plan, versions
