"""Turn the winning simulation into the plan everyone reads: ETAs, rationale, unmet needs, questions, diff.

Every number here comes from the simulator (the winning run, or a counterfactual run without one
assignment), never from the allocator's own estimates.
"""

from __future__ import annotations

from ..models.facilities import compatible
from ..sim.plan_sim import simulate
from .context import VEHICLES, Context

mins = lambda t: f"{t/60:.0f} min"  # noqa: E731


def explain(ctx: Context, carry, assignments: list, res, reports, version: int, prev: dict | None, pol) -> dict:
    from .search import _held

    w, scn = ctx.world, ctx.scn
    out = {o["assignment_id"]: o for o in res.outcomes}
    res_name = {x["id"]: x["name"] for x in scn["resources"]}
    accessible = [x["id"] for x in scn["resources"] if x.get("accessible") and x["kind"] in VEHICLES]
    final = []
    for a in assignments:
        o = out[a["id"]]
        a = dict(a)
        a["eta_s"] = round(float(o["arrive_t"] if o["arrive_t"] is not None else a.get("eta_s") or scn["t_end_s"]), 1)
        a["route_edges"] = [int(w.edge_id[e]) for e in o["route_edges"]]
        if a["task"] == "rescue":
            hid = a["target"]["household_id"]
            d = ctx.deadline.get(hid)
            a["deadline_s"], a["slack_s"] = d, (None if d is None else round(d - a["eta_s"], 1))
            if not a.get("rationale") or a.get("plan_version") == version:
                a["rationale"] = _rescue_why(ctx, a, o, res_name, accessible, pol)
        elif a["task"] == "protect" and (not a.get("rationale") or a.get("plan_version") == version):
            a["deadline_s"] = ctx.power_risk.get(a["target"]["facility_id"], (None, None))[1]
            a["rationale"] = _protect_why(ctx, a, o, assignments, res, reports, res_name)
        old = {b["id"]: b for b in (prev or {}).get("assignments", [])}.get(a["id"])
        if old is not None and a.get("status") != "cancelled" and a.get("plan_version") != version \
                and abs(float(a["eta_s"]) - float(old.get("eta_s") or 0)) > 120:
            base_why = a.get("rationale", "").split(" · v")[0]
            a["rationale"] = (f"{base_why} · v{version}: ETA {mins(float(old['eta_s']))} → {mins(a['eta_s'])}"
                              + (" (route changed: road reported closed)" if any(r["kind"] == "closure_report" and
                                 float(r["observed_at_t_s"]) <= ctx.t_now for r in ctx.known_reports) else ""))
        if a.get("status") == "cancelled" and a.get("cancelled_at_t_s") == ctx.t_now:
            moved_to = [b["target"].get("facility_id") or b["target"].get("household_id") for b in assignments
                        if b["resource_id"] == a["resource_id"] and b.get("plan_version") == version and b.get("status") != "cancelled"]
            own = a["target"].get("facility_id") or a["target"].get("household_id")
            a["rationale"] = (f"cancelled at {mins(ctx.t_now)} by plan v{version}"
                              + (f": {res_name[a['resource_id']]} re-routed to the same target from where it is now" if moved_to and moved_to[0] == own
                                 else f": {res_name[a['resource_id']]} re-targeted to {moved_to[0]}" if moved_to else ": no longer feasible with the new facts")
                              + f" (was: {a.get('rationale', '')})")
        elif a["task"] == "protect" and a.get("plan_version") == version and prev:
            # a generator re-planned onto the same facility: say what it replaces and why the ETA moved
            old = next((b for b in prev.get("assignments", []) if b["resource_id"] == a["resource_id"] and b["task"] == "protect"
                        and b["target"] == a["target"] and b.get("status") != "cancelled"), None)
            if old is not None:
                closed = any(r["kind"] == "closure_report" and float(r["observed_at_t_s"]) <= ctx.t_now for r in ctx.known_reports)
                a["rationale"] += (f" · v{version}: replaces {old['id']}, ETA {mins(float(old['eta_s']))} → {mins(a['eta_s'])}"
                                   + (" (route changed: road reported closed)" if closed else ""))
        final.append(a)

    # unmet needs + questions
    unresolved, info = [], []
    picked = {o["target"].get("household_id"): o for o in res.outcomes if o["task"] == "rescue" and o["pickup_t"] is not None}
    active = {a["target"].get("household_id") for a in final if a["task"] == "rescue" and a.get("status") != "cancelled"}
    held = _held(ctx, carry.slots, pol)
    for hid, h in ctx.hh.items():
        need = ctx.needs[hid]
        if need == "unknown":
            unresolved.append({"target": {"household_id": hid}, "need": "unknown", "blocked_by": "needs unknown",
                               "would_unblock": "how many people, and whether anyone needs a wheelchair-accessible vehicle",
                               "alternatives": ["keep the accessible van's next slot open", "send a standard van if no mobility need"]})
            info.append({"id": f"q-{hid}", "to": {"household_id": hid},
                         "question": "How many people are with you, and does anyone need a wheelchair-accessible vehicle?",
                         "why": ("the accessible van is the scarce resource; your answer decides its next trip" if h.get("judge")
                                 else "needed to schedule a pickup before the water reaches your street")})
            continue
        d = ctx.deadline.get(hid)
        o = picked.get(hid)
        if o is not None and (d is None or o["pickup_t"] <= d):
            continue
        if d is None and hid in active:
            continue
        unresolved.append(_why_unmet(ctx, hid, need, d, o, out, final, held, res_name))
    protected = {a["target"]["facility_id"] for a in final if a["task"] == "protect" and a.get("status") != "cancelled"}
    for k, (_, down_t) in ctx.power_risk.items():
        f = ctx.fac[k]
        if down_t is None or k in protected or f["type"] not in ("pumping_station", "hospital", "clinic") or not f.get("connector"):
            continue
        gens = [x for x in scn["resources"] if x["kind"] == "generator"]
        fit = [x for x in gens if compatible(x, f)[0]]
        busy = [a for a in final if a["task"] == "protect" and a["resource_id"] in {x["id"] for x in fit} and a.get("status") != "cancelled"]
        blocked = ("no compatible generator in the fleet" if not fit else
                   f"the only compatible generator is protecting {busy[0]['target']['facility_id']}" if busy else
                   "keeping a compatible generator in reserve scored better")
        if busy:
            alt = _swap_metrics(ctx, final, busy[0], k, reports, version)
            blocked += (f"; sending {res_name[busy[0]['resource_id']]} here instead (rest of the plan unchanged, simulated): "
                        f"{_deltas(res.metrics, alt)}. {RANKING}")
            if busy[0].get("plan_version") == version:
                busy[0]["rationale"] += f" · chosen over {f['name']}: sending it there instead would mean {_deltas(res.metrics, alt)}"
        unresolved.append({"target": {"facility_id": k}, "need": f"{f.get('power_kw_required', 0):.0f} kW on {f['connector']} before {mins(down_t)}",
                           "blocked_by": blocked,
                           "would_unblock": "a second compatible generator, or a longer backup endurance report from the operator"})
        if f.get("backup_endurance_s"):
            info.append({"id": f"q-{k}", "to": {"facility_id": k}, "question": "How many hours of backup power do you have on site right now?",
                         "why": f"decides whether a generator should move to {f['name']}"})

    plan = {"version": version, "parent_version": prev.get("version") if prev else None, "created_at_t_s": float(ctx.t_now),
            "planner": "ember", "reserved": sorted(r for r in held if not any(a["resource_id"] == r and a.get("status") != "cancelled" for a in final)),
            "assignments": final, "changes": _diff(prev, final), "unresolved": unresolved, "info_requests": info,
            "metrics": dict(res.metrics)}
    return plan


def _rescue_why(ctx, a, o, res_name, accessible, pol) -> str:
    hid = a["target"]["household_id"]
    need = ctx.needs[hid]
    mob = need.get("mobility") or need.get("accessible_vehicle")
    who = res_name[a["resource_id"]]
    why = ("the only wheelchair-accessible vehicle" if mob and len(accessible) == 1 else
           "an accessible vehicle (mobility need)" if mob else "earliest eligible arrival")
    d = ctx.deadline.get(hid)
    if o["pickup_t"] is not None:
        when = f"simulated pickup {mins(o['pickup_t'])}" + (f" vs deadline {mins(d)} (slack {mins(d - o['pickup_t'])})" if d is not None else "")
    else:
        when = f"simulated outcome: {o['status']} ({o['reason'] or 'not reached'})"
    return f"{who} → household #{hid}: {need['people']} people{', wheelchair' if mob else ''}; {why}; {when}; plan rule: {pol.order}-first"


def _protect_why(ctx, a, o, assignments, res, reports, res_name) -> str:
    fid = a["target"]["facility_id"]
    f = ctx.fac[fid]
    backup_t, down_t = ctx.power_risk.get(fid, (None, None))
    without = simulate(ctx.world, ctx.scn, {"assignments": [x for x in assignments if x["id"] != a["id"]]}, reports=reports, record=False).metrics
    d_over = without["overflow_m3"] - res.metrics["overflow_m3"]
    d_hosp = without["hospital_outage_s"] - res.metrics["hospital_outage_s"]
    gains = []
    if d_over > 0:
        gains.append(f"prevents {d_over:,.0f} m³ of untreated overflow to the river")
    if d_hosp > 0:
        gains.append(f"prevents {mins(d_hosp)} of hospital outage")
    risk = (f"grid power lost at {mins(backup_t)}" + (f", down at {mins(down_t)}" if down_t is not None else "")) if backup_t is not None else "at risk"
    conn = f"connected {mins(o['complete_t'])}" if o["complete_t"] is not None else f"simulated outcome: {o['status']} ({o['reason']})"
    return (f"{res_name[a['resource_id']]} → {f['name']}: {risk}; " + ("; ".join(gains) or "no simulated benefit in this horizon")
            + f" (simulated with vs without); {conn}")


RANKING = "The plan ranks people not reached first, then hospital outage, then overflow."


def _swap_metrics(ctx, final: list, protect: dict, facility_id: str, reports, version: int) -> dict:
    """Simulated metrics if `protect`'s generator went to `facility_id` instead, everything else unchanged.
    A job new in this version is retargeted; a carried-over one is cancelled now and replaced, as a replan would."""
    t = ctx.t_now
    if protect.get("plan_version") == version:
        alt = [dict(a, target={"facility_id": facility_id}) if a["id"] == protect["id"] else a for a in final]
    else:
        alt = [dict(a, status="cancelled", cancelled_at_t_s=t) if a["id"] == protect["id"] else a for a in final]
        alt.append(dict(protect, id=f"{protect['id']}-swap", plan_version=version, target={"facility_id": facility_id},
                        status="proposed", not_before_t_s=t if t > 0 else None, cancelled_at_t_s=None))
    return simulate(ctx.world, ctx.scn, {"assignments": alt}, reports=reports, record=False).metrics


def _deltas(now: dict, alt: dict) -> str:
    """'people not reached 5 → 7, hospital outage 190 → 16 min, overflow 0 → 9,600 m³' (only what changes)."""
    parts = []
    if alt["people_unreached"] != now["people_unreached"]:
        parts.append(f"people not reached {now['people_unreached']} → {alt['people_unreached']}")
    if round(alt["hospital_outage_s"] / 60) != round(now["hospital_outage_s"] / 60):
        parts.append(f"hospital outage {now['hospital_outage_s'] / 60:.0f} → {mins(alt['hospital_outage_s'])}")
    if round(alt["overflow_m3"]) != round(now["overflow_m3"]):
        parts.append(f"overflow {now['overflow_m3']:,.0f} → {alt['overflow_m3']:,.0f} m³")
    return ", ".join(parts) or "no simulated difference"


def _why_unmet(ctx, hid, need, d, o, out, final, held, res_name) -> dict:
    mob = need.get("mobility") or need.get("accessible_vehicle")
    txt = f"{need['people']} people" + (", wheelchair-accessible vehicle" if mob else "") + (f" before {mins(d)}" if d is not None else "")
    mine = [a for a in final if a["task"] == "rescue" and a["target"].get("household_id") == hid and a.get("status") != "cancelled"]
    elig = [s for s in ctx.fleet().values() if ctx.eligible(s.spec, hid)]
    if mine:
        oo = out[mine[-1]["id"]]
        blocked = (f"assigned to {res_name[mine[-1]['resource_id']]} but simulated pickup at {mins(oo['pickup_t'])}, after the deadline"
                   if oo["pickup_t"] is not None else f"assigned to {res_name[mine[-1]['resource_id']]}: {oo['reason'] or oo['status']}")
    elif not elig:
        blocked = "no wheelchair-accessible vehicle with room" if mob else f"no vehicle with capacity ≥ {need['people']}"
    elif d is not None and ctx.tf(ctx.base_node)[ctx.hh_node[hid]] == float("inf"):
        blocked = "no open route: flooded or reported-closed roads cut the household off"
    else:
        blocked = "every eligible vehicle is committed to earlier deadlines"
    spare = sorted(r for r in held if any(s.rid == r for s in elig))
    unblock = (f"release reserve {', '.join(res_name[r] for r in spare)}" if spare else
               "another eligible vehicle, a closer drop-off point, or a road report that reopens access")
    return {"target": {"household_id": hid}, "need": txt, "blocked_by": blocked, "would_unblock": unblock,
            "alternatives": ["shelter in place above ground floor", "walk to the nearest dry pickup point if able"]}


def _diff(prev: dict | None, final: list) -> list:
    if not prev:
        return []
    before = {a["id"]: a for a in prev.get("assignments", []) if a.get("status") != "cancelled"}
    after = {a["id"]: a for a in final if a.get("status") != "cancelled"}
    by_target_before = {_tkey(a): a for a in before.values()}
    ch = []
    for i, a in after.items():
        if i in before:
            if abs(float(a["eta_s"]) - float(before[i].get("eta_s") or 0)) > 120:
                ch.append({"assignment_id": i, "change": "eta_changed", "note": f"ETA {mins(before[i]['eta_s'])} → {mins(a['eta_s'])}"})
        elif _tkey(a) in by_target_before:
            b = by_target_before[_tkey(a)]
            ch.append({"assignment_id": i, "change": "resource_changed", "note": f"{b['resource_id']} → {a['resource_id']}"})
        else:
            ch.append({"assignment_id": i, "change": "added"})
    cancelled_now = {a["id"] for a in final if a.get("status") == "cancelled"}
    for i, b in before.items():
        if i not in after and i not in cancelled_now and not any(_tkey(a) == _tkey(b) for a in after.values()):
            ch.append({"assignment_id": i, "change": "removed"})
    for a in final:
        if a.get("status") == "cancelled" and a["id"] in before:
            ch.append({"assignment_id": a["id"], "change": "removed", "note": f"cancelled at {mins(a['cancelled_at_t_s'])}"})
    return ch


def _tkey(a: dict) -> tuple:
    t = a["target"]
    return (a["task"], t.get("household_id"), t.get("facility_id"), tuple(t.get("edge_ids", [])))
