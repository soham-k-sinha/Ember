"""A simple, explainable plan for a scenario: the stand-in until the allocator lands.

Dependency-first protect (a pumping station whose power source has a scheduled failure gets the
strongest compatible generator, dispatched at t0 while roads are open), then deadline-ordered rescues:
each household with known needs goes to the eligible vehicle (capacity, accessibility) with the
earliest estimated arrival; the accessible van is kept for mobility needs when another vehicle can go.
Reserve rule: hold back the largest vehicle(s) and the smallest generator(s). Unknown needs become
info requests. Estimates use free-flow times at t0; the simulator decides what actually happens.
"""

from __future__ import annotations

import numpy as np

from ..models.facilities import compatible
from ..scenario import deadlines, flood_keyframes
from .plan_sim import UNLOAD_S

ACCESSIBLE_PENALTY_S = 600.0


def example_plan(world, scn: dict, t0: float = 0.0, version: int = 1) -> dict:
    fac = {f["id"]: f for f in scn["facilities"]}
    assets = {a["id"]: a for a in world.assets}
    node_of = lambda f: world.node_index(f["node"] if "node" in f else assets[f["asset_id"]]["node"])  # noqa: E731
    base = next(k for k, f in fac.items() if f["type"] in ("response_base", "shelter"))
    frames = flood_keyframes(scn, world)
    dl = deadlines(scn, world, frames)["households"]
    rows = {int(h): i for i, h in enumerate(world.hh_id)}

    res = scn["resources"]
    start = {x["id"]: (node_of(fac[x["at_facility"]]) if "at_facility" in x else world.node_index(x["node"])) for x in res}
    vehicles = [x for x in res if x["kind"] in ("van", "accessible_van", "ambulance", "truck") and not x.get("reserved")]
    gens = [x for x in res if x["kind"] == "generator" and not x.get("reserved")]
    rsv = scn.get("reserve", {})
    held = {x["id"] for x in sorted(vehicles, key=lambda x: -x.get("capacity_people", 0))[:rsv.get("vans", 0)]}
    held |= {x["id"] for x in sorted(gens, key=lambda x: x.get("kw", 0))[:rsv.get("generators", 0)]}

    assignments, unresolved, info = [], [], []

    # ---------- protect: dependency-first ----------
    scheduled_down = {k for k, f in fac.items() if any(e["state"] == "down" for e in f.get("events", []))}
    for k, f in fac.items():
        if f["type"] != "pumping_station":
            continue
        if not any(d in scheduled_down for d in f.get("depends_on", [])) and f.get("backup_endurance_s", 0) > 0:
            continue
        cands = [g for g in gens if g["id"] not in held and compatible(g, f)[0] and not any(a["resource_id"] == g["id"] for a in assignments)]
        if not cands:
            unresolved.append({"target": {"facility_id": k}, "need": f"{f.get('power_kw_required', 0):.0f} kW on {f.get('connector', '?')}",
                               "blocked_by": "no compatible generator available", "would_unblock": "a generator with that connector"})
            continue
        g = max(cands, key=lambda g: g["kw"])
        fail_t = min((e["t_s"] for d in f.get("depends_on", []) for e in fac[d].get("events", []) if e["state"] == "down"), default=None)
        assignments.append({"id": f"a-{g['id']}-{k}", "plan_version": version, "resource_id": g["id"], "task": "protect",
                            "target": {"facility_id": k}, "dropoff_facility_id": None, "eta_s": 0.0, "status": "proposed",
                            "rationale": (f"{g['name']} → {f['name']}: dependency-first; "
                                          + (f"its power fails at {fail_t/60:.0f} min" if fail_t is not None else "no backup power")
                                          + " → untreated overflow to the river; dispatch now while the approach is dry")})

    # ---------- rescue: deadline-ordered greedy ----------
    out = {b: world.times_from(start[b] if b in start else node_of(fac[base])) for b in {x["id"] for x in vehicles}}
    back = world.times_from(node_of(fac[base]), reverse=True)
    from_base = world.times_from(node_of(fac[base]))
    free_at = {x["id"]: t0 for x in vehicles if x["id"] not in held}
    at_base = {x["id"]: start[x["id"]] == node_of(fac[base]) for x in vehicles}
    order = sorted(scn["households"], key=lambda h: (dl.get(h["household_id"]) is None, dl.get(h["household_id"]) or 0, h["household_id"]))
    for h in order:
        hid, need = h["household_id"], h["needs"]
        if need == "unknown":
            unresolved.append({"target": {"household_id": hid}, "need": "unknown", "blocked_by": "needs unknown",
                               "would_unblock": "how many people, and whether anyone needs a wheelchair-accessible vehicle",
                               "alternatives": ["hold the accessible van after its current pickup", "send a standard van if no mobility need"]})
            info.append({"id": f"q-{hid}", "to": {"household_id": hid},
                         "question": "How many people are with you, and does anyone need a wheelchair-accessible vehicle?",
                         "why": ("the accessible van is the scarce resource; your answer decides its next trip" if h.get("judge")
                                 else "needed to schedule a pickup before the water reaches your street")})
            continue
        node = int(world.hh_node[rows[hid]])
        d = dl.get(hid)
        mob = need.get("mobility") or need.get("accessible_vehicle")
        best = None
        for x in vehicles:
            vid = x["id"]
            if vid not in free_at or x.get("capacity_people", 0) < need["people"] or (mob and not x.get("accessible")) \
                    or (x["kind"] == "ambulance" and not need.get("medical")):
                continue
            leg = (from_base[node] if at_base[vid] else out[vid][node]) / float(x.get("speed_factor", 1.0))
            eta = free_at[vid] + leg
            score = eta + (ACCESSIBLE_PENALTY_S if x.get("accessible") and not mob and x["kind"] != "ambulance" else 0.0)
            if np.isfinite(eta) and (best is None or score < best[2]):
                best = (x, eta, score)
        if best is None or (d is not None and best[1] > d):
            unresolved.append({"target": {"household_id": hid}, "need": f"{need['people']} people" + (", accessible vehicle" if mob else ""),
                               "blocked_by": ("no open route from the base" if best is None and np.isinf(from_base[node])
                                              else ("no accessible vehicle" if mob else "no vehicle") + " arrives before the deadline"),
                               "would_unblock": "release the reserve vehicle or a closer drop-off point"})
            continue
        x, eta, _ = best
        free_at[x["id"]] = eta + float(x.get("service_s", 300)) + back[node] / float(x.get("speed_factor", 1.0)) + UNLOAD_S
        at_base[x["id"]] = True
        slack = None if d is None else d - eta
        assignments.append({"id": f"a-{x['id']}-{hid}", "plan_version": version, "resource_id": x["id"], "task": "rescue",
                            "target": {"household_id": hid}, "dropoff_facility_id": base, "eta_s": round(eta, 1),
                            "deadline_s": d, "slack_s": None if slack is None else round(slack, 1), "status": "proposed",
                            "rationale": (f"{x['name']} → household #{hid}: {need['people']} people ≤ capacity {x['capacity_people']}"
                                          + (", accessible" if mob else "")
                                          + (f"; deadline {d/60:.0f} min, est. arrival {eta/60:.0f} min (slack {slack/60:.0f} min)"
                                             if d is not None else f"; not in the flood, est. arrival {eta/60:.0f} min"))})

    return {"version": version, "parent_version": None, "created_at_t_s": t0, "planner": "example", "trigger": "initial plan",
            "assignments": assignments, "changes": [], "unresolved": unresolved, "info_requests": info,
            "reserved": sorted(held)}
