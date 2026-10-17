"""Baseline planner (TECHNICAL.md §3.6): incident by incident, the way a dispatch desk without EMBER works.

Alerts are handled in arrival order: households whose needs are known at t=0 (scenario order), each
need report at its report time, and each facility at the moment it actually goes down. Every alert gets
the nearest available compatible resource (earliest free if none is free), dispatched when the alert
arrives. No lookahead, no dependency awareness (it reacts to the pumping station failing, not to the
substation that will cause it), no reserve, and no deadline check.
"""

from __future__ import annotations

from .allocator.context import Context
from .models.facilities import compatible


def alerts(ctx: Context, reports=()) -> list[tuple[float, str, object]]:
    """[(t_s, 'household' | 'facility', id)] in arrival order."""
    out, seen = [], set()
    for h in ctx.scn["households"]:
        if h["needs"] != "unknown":
            out.append((0.0, "household", h["household_id"])); seen.add(h["household_id"])
    revs = [(float(r["t_s"]), r["household_id"]) for r in ctx.scn.get("scripted_reports", []) if r["kind"] == "need"]
    revs += [(float(r["observed_at_t_s"]), r["household_id"]) for r in reports if r["kind"] == "need" and "household_id" in r]
    for t, hid in sorted(revs):
        if hid not in seen and hid in ctx.hh:
            out.append((t, "household", hid)); seen.add(hid)
    for k, (_, down_t) in ctx.power_risk.items():
        f = ctx.fac[k]
        if down_t is not None and f.get("connector") and f["type"] in ("pumping_station", "hospital", "clinic"):
            out.append((down_t, "facility", k))
    return sorted(out, key=lambda a: a[0])


def baseline_plan(world, scn: dict, reports=(), version: int = 1) -> dict:
    reports = list(reports)
    # the baseline learns each need when it arrives; plan with everything, dispatch at arrival time
    ctx = Context(world, scn, reports, t_now=float(scn["t_end_s"]))
    fleet = Context(world, scn, [], 0.0).fleet()
    assignments = []
    for t_alert, kind, ref in alerts(ctx, reports):
        if kind == "household":
            need = ctx.needs.get(ref)
            if need == "unknown" or need is None:
                continue
            node = ctx.hh_node[ref]
            best = None
            for s in fleet.values():
                if not s.available or not ctx.eligible(s.spec, ref):
                    continue
                start = max(s.free_at, t_alert)
                key = (start > t_alert, start + ctx.travel(s.spec, s.node, node))   # free now first, then nearest
                if best is None or key < best[0]:
                    best = (key, s, start)
            if best is None:
                continue
            _, s, start = best
            leg = ctx.travel(s.spec, s.node, node)
            drop = ctx.dropoff_for(ref)   # same drop-off rule as EMBER, so the comparison isolates the planning
            back = float(ctx.tb(ctx.fac_node[drop])[node]) / float(s.spec.get("speed_factor", 1.0))
            eta = start + leg
            s.free_at, s.node = eta + float(s.spec.get("service_s", 300)) + back + 120.0, ctx.fac_node[drop]
            assignments.append({"id": f"a-{s.rid}-{ref}", "plan_version": version, "resource_id": s.rid, "task": "rescue",
                                "target": {"household_id": ref}, "dropoff_facility_id": drop, "eta_s": round(eta, 1),
                                "deadline_s": ctx.deadline.get(ref), "status": "proposed", "not_before_t_s": t_alert,
                                "rationale": f"incident-by-incident: alert at {t_alert/60:.0f} min; nearest available "
                                             f"{s.spec['name']} ({leg/60:.0f} min away)"})
        else:
            f = ctx.fac[ref]
            best = None
            for s in fleet.values():
                if s.spec["kind"] != "generator" or not s.available or not compatible(s.spec, f)[0]:
                    continue
                key = (max(s.free_at, t_alert) > t_alert, ctx.travel(s.spec, s.node, ctx.fac_node[ref]))
                if best is None or key < best[0]:
                    best = (key, s)
            if best is None:
                continue
            s = best[1]
            s.available = False
            assignments.append({"id": f"a-{s.rid}-{ref}", "plan_version": version, "resource_id": s.rid, "task": "protect",
                                "target": {"facility_id": ref}, "dropoff_facility_id": None, "eta_s": round(t_alert + best[0][1], 1),
                                "deadline_s": t_alert, "status": "proposed", "not_before_t_s": t_alert,
                                "rationale": f"incident-by-incident: {f['name']} lost power at {t_alert/60:.0f} min; "
                                             f"nearest compatible {s.spec['name']}"})
    return {"version": version, "parent_version": None, "created_at_t_s": 0.0, "planner": "baseline",
            "trigger": "alerts in arrival order", "assignments": assignments, "changes": [], "unresolved": [], "info_requests": []}
