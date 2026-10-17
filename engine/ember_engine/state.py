"""Shared-state snapshot (contracts/state.schema.json): an example builder and a validator.

`example_state` computes a plausible snapshot from a scenario at time t_s: flood extent and closures
from the keyframes, facility states from scheduled events and dependencies, wastewater storage
integrated tick by tick, and a deadline-ordered example dispatch (real routes and ETAs on the
closed-edge graph). It is NOT the allocator: `plan.planner = "example"`, and outcomes before the
plan's creation time are illustrative (listed in `synthetic`). It exists so web/ and residents/ can
build against a realistic state before the simulator and allocator land.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .scenario import CONTRACTS, deadlines, flood_keyframes

TICK = 60.0


# ---------- small helpers ----------
def _step(series, t: float) -> float:
    """[[t_s, v], ...] step function (or a constant)."""
    if not isinstance(series, list):
        return float(series)
    v = float(series[0][1])
    for ts, val in series:
        if ts <= t:
            v = float(val)
    return v


def _place(fac: dict, town: dict) -> tuple[int, float, float]:
    """Facility → (OSM node, lon, lat)."""
    if "asset_id" in fac:
        a = town["assets"][fac["asset_id"]]
        return a["node"], a["lon"], a["lat"]
    n = next(n for n in town["nodes"] if n["id"] == fac["node"])
    return n["id"], n["lon"], n["lat"]


def facility_timeline(scn: dict, t_end: float, gen_at: dict | None = None) -> dict:
    """Facility states per tick from scheduled events, dependencies and backup endurance.

    gen_at: {facility_id: t_s a compatible generator is connected} → state 'ok' from then on.
    Returns {id: [(t, state, endurance_left_s|None, since_t)]}."""
    gen_at = gen_at or {}
    fac = {f["id"]: f for f in scn["facilities"]}
    endurance = {k: float(f.get("backup_endurance_s", 0.0)) for k, f in fac.items()}
    own = {k: f.get("state0", "ok") for k, f in fac.items()}
    state = dict(own)
    since = {k: 0.0 for k in fac}
    used = {k: 0.0 for k in fac}   # backup seconds consumed
    out = {k: [] for k in fac}
    t = 0.0
    while t <= t_end + 1e-9:
        for k, f in fac.items():   # scheduled events set the facility's own state
            for ev in f.get("events", []):
                if ev["t_s"] <= t < ev["t_s"] + TICK:
                    own[k] = ev["state"]
        for rep in scn.get("scripted_reports", []):
            if rep["kind"] == "facility_status" and rep["t_s"] <= t < rep["t_s"] + TICK:
                if "backup_endurance_s" in rep.get("set", {}):
                    endurance[rep["facility_id"]] = float(rep["set"]["backup_endurance_s"]) + used[rep["facility_id"]]
        for _ in range(len(fac)):   # settle dependency chains
            for k, f in fac.items():
                if own[k] == "down":
                    new = "down"
                elif k in gen_at and t >= gen_at[k]:
                    new = "ok"
                elif any(state[d] == "down" for d in f.get("depends_on", []) if fac[d]["type"] != "outfall"):
                    new = "backup" if endurance[k] - used[k] > 0 else "down"
                else:
                    new = own[k]
                if new != state[k]:
                    state[k], since[k] = new, t
        for k in fac:
            left = None
            if state[k] == "backup":
                used[k] += TICK
                left = max(0.0, endurance[k] - used[k])
            out[k].append((t, state[k], left, since[k]))
        t += TICK
    return out


def wastewater_at(f: dict, states: list, t_s: float) -> dict:
    """Integrate storage/overflow for a pumping station up to t_s (TECHNICAL §3.3)."""
    ww = f["wastewater"]
    storage, overflow = float(ww["storage_m3"]), 0.0
    smax, pump = float(ww["storage_max_m3"]), float(ww["pump_m3ph"])
    ser = {"t_s": [], "storage_m3": [], "overflow_m3": []}
    inflow = pumped = 0.0
    for t, st, _, _ in states:
        if t > t_s + 1e-9:
            break
        inflow = _step(ww["inflow_m3ph"], t)
        powered = st in ("ok", "backup") and ww.get("downstream_ok", True)
        pumped = min(pump, inflow + storage * 3600.0 / TICK) if powered else 0.0
        storage += (inflow - pumped) * TICK / 3600.0
        if storage > smax:
            overflow += storage - smax
            storage = smax
        if int(round(t)) % 300 == 0:
            ser["t_s"].append(t); ser["storage_m3"].append(round(storage, 1)); ser["overflow_m3"].append(round(overflow, 1))
    return {"storage_m3": round(storage, 1), "storage_max_m3": smax, "inflow_m3ph": inflow, "pumped_m3ph": round(pumped, 1),
            "overflow_m3": round(overflow, 1), "series": ser}


# ---------- example snapshot ----------
def example_state(town: dict, scn: dict, t_s: float = 4800.0, plan_t_s: float = 4500.0) -> dict:
    import shapely

    from .world import World

    w = World.from_dict(town)
    frames = flood_keyframes(scn, w)
    dl = deadlines(scn, w, frames)
    kfs = sorted(scn["hazard"]["keyframes"], key=lambda k: k["t_s"])
    eid = lambda e: int(w.edge_id[e])  # noqa: E731

    # hazard + closures (each edge closes at the first keyframe that touches it)
    closed_t = np.full(w.n_edges, np.nan)
    for t, g in frames:
        if t <= t_s and not g.is_empty:
            hit = np.isnan(closed_t) & shapely.intersects(g, w.edge_lines())
            closed_t[hit] = t
    cur = [k for k in kfs if k["t_s"] <= t_s]
    nxt = [k for k in kfs if k["t_s"] > t_s]
    hazard = {"keyframe_t_s": cur[-1]["t_s"] if cur else None, "geometry": cur[-1]["geometry"] if cur else None,
              "next_keyframe_t_s": nxt[0]["t_s"] if nxt else None, "keyframe_times_s": [k["t_s"] for k in kfs]}
    closures = [{"edge_id": eid(e), "closed_from_t_s": float(closed_t[e]), "source": "hazard"} for e in np.where(~np.isnan(closed_t))[0]]
    closed_at_plan = ~np.isnan(closed_t) & (np.nan_to_num(closed_t, nan=np.inf) <= plan_t_s)

    fac = {f["id"]: f for f in scn["facilities"]}
    place = {k: _place(f, town) for k, f in fac.items()}
    base = next(k for k, f in fac.items() if f["type"] in ("response_base", "shelter"))
    base_n = w.node_index(place[base][0])

    # households: needs known at t_s (scenario or scripted reports)
    reports, needs, needs_src = [], {}, {}
    for h in scn["households"]:
        needs[h["household_id"]] = h["needs"]
        needs_src[h["household_id"]] = "scenario"
    for i, rep in enumerate(sorted(scn.get("scripted_reports", []), key=lambda r: r["t_s"])):
        if rep["t_s"] > t_s:
            continue
        r = {"id": f"r-{i + 1}", "source": "scenario", "kind": rep["kind"], "observed_at_t_s": float(rep["t_s"]), "confidence": 1.0, "resolved": True}
        if rep.get("note"):
            r["text"] = rep["note"]
        if rep["kind"] == "need":
            r |= {"household_id": rep["household_id"], "payload": dict(rep["needs"])}
            needs[rep["household_id"]] = dict(rep["needs"]); needs_src[rep["household_id"]] = "report"
        elif rep["kind"] == "facility_status":
            r |= {"facility_id": rep["facility_id"], "payload": {"set": rep.get("set", {})}}
        elif rep["kind"] == "closure_report":
            r |= {"payload": {"edge_ids": rep.get("edge_ids", [])}}
            if rep.get("household_id") is not None:
                r["household_id"] = rep["household_id"]
        reports.append(r)

    hh_by_id = {h["id"]: h for h in town["households"]}
    hrow = {int(h): i for i, h in enumerate(w.hh_id)}
    hnode = {h: int(w.hh_node[hrow[h]]) for h in needs}

    # resources start at their facility / node
    res = []
    for x in scn["resources"]:
        n = w.node_index(place[x["at_facility"]][0]) if "at_facility" in x else w.node_index(x["node"])
        res.append(dict(x, _n=n))
    reserve_v, reserve_g = scn["reserve"].get("vans", 0), scn["reserve"].get("generators", 0)
    vehicles = [x for x in res if x["kind"] in ("van", "accessible_van", "truck") and not x.get("reserved")]
    gens = [x for x in res if x["kind"] == "generator" and not x.get("reserved")]
    # reserve rule: hold back the largest vehicle(s) and the smallest generator(s)
    held = {x["id"] for x in sorted(vehicles, key=lambda x: -x["capacity_people"])[:reserve_v]}
    held |= {x["id"] for x in sorted(gens, key=lambda x: x.get("kw", 0))[:reserve_g]}

    def travel(x, a, b):
        path, tt = w.route(a, b, closed_at_plan)
        return path, tt / float(x.get("speed_factor", 1.0))

    assignments, unresolved, info_requests = [], [], []
    status = {}
    gen_at = {}
    # protect: dependency-first — a pumping station whose power source fails gets the strongest compatible generator
    tl0 = facility_timeline(scn, scn["t_end_s"])
    for k, f in fac.items():
        if f["type"] != "pumping_station" or "connector" not in f:
            continue
        down = [t for t, st, _, _ in tl0[k] if st == "down"]
        cands = [g for g in gens if g["id"] not in held and g.get("connector") == f["connector"] and g.get("kw", 0) >= f.get("power_kw_required", 0)]
        if not down or not cands:
            continue
        g = max(cands, key=lambda g: g["kw"])
        path, tt = w.route(g["_n"], w.node_index(place[k][0]))   # dispatched in plan v1 at t=0, roads still open
        tt /= float(g.get("speed_factor", 1.0))
        if not path or not np.isfinite(tt):
            unresolved.append({"target": {"facility_id": k}, "need": f"{f.get('power_kw_required', 0):.0f} kW on {f['connector']}",
                               "blocked_by": "no open route from the generator", "would_unblock": "a crew clearing the approach road"})
            continue
        eta = tt
        gen_at[k] = eta + float(f.get("connect_s", 900))
        wet = closed_t[path][~np.isnan(closed_t[path])]
        route_txt = f"its route floods at {wet.min()/60:.0f} min" if len(wet) else "route stays dry"
        hosp = [h for h in fac.values() if h["type"] == "hospital"]
        hosp_txt = f"; hospital backup {hosp[0].get('backup_endurance_s', 0)/3600:.1f} h" if hosp else ""
        assignments.append(dict(id=f"a-{g['id']}-{k}", resource=g, task="protect", target={"facility_id": k}, path=path, eta=eta,
                                deadline=float(down[0]), rationale=(f"{g['name']} → {f['name']} (pre-positioned in v1): power fails at {down[0]/60:.0f} min with no backup "
                                f"→ overflow to the Charles; {route_txt}; on site {eta/60:.0f} min, "
                                f"connected by {gen_at[k]/60:.0f} min{hosp_txt}"), dispatched=0.0))
        g["_busy"] = True

    # rescue: deadline-ordered greedy over known needs (the example planner, not the allocator)
    free_at = {x["id"]: plan_t_s for x in vehicles if x["id"] not in held}
    pos = {x["id"]: x["_n"] for x in vehicles}
    first_job = {}
    order = sorted(needs, key=lambda h: (dl["households"].get(h) is None, dl["households"].get(h) or 0, h))
    for h in order:
        d = dl["households"].get(h)
        nd = needs[h]
        if nd == "unknown":
            status[h] = "unknown"
            continue
        if d is not None and d <= plan_t_s:   # before this plan: illustrative history
            status[h] = "unreached" if h == order[0] else "safe"
            continue
        if d is None and len([a for a in assignments if a["task"] == "rescue"]) >= 2 * len(free_at):
            status[h] = "needs"
            continue
        best = None
        for x in vehicles:
            if x["id"] not in free_at or x["capacity_people"] < nd["people"]:
                continue
            if (nd.get("mobility") or nd.get("accessible_vehicle")) and not x.get("accessible"):
                continue
            path, tt = travel(x, pos[x["id"]], hnode[h])
            eta = free_at[x["id"]] + tt
            if best is None or eta < best[1]:
                best = (x, eta, path)
        need_txt = f"{nd['people']} people" + (", accessible vehicle" if nd.get("mobility") else "")
        if best is None or not np.isfinite(best[1]):
            status[h] = "needs"
            unresolved.append({"target": {"household_id": h}, "need": need_txt,
                               "blocked_by": "no open route: flooded roads cut the household off from the base",
                               "would_unblock": "the reserve high-clearance truck, or a crew clearing the access road",
                               "alternatives": ["shelter in place above ground floor", "walk to the nearest dry pickup point if able"]})
            continue
        if d is not None and best[1] > d:
            status[h] = "needs"
            unresolved.append({"target": {"household_id": h}, "need": need_txt,
                               "blocked_by": ("no accessible vehicle" if nd.get("mobility") else "no vehicle") + " arrives before the deadline",
                               "would_unblock": "release the reserve vehicle or a closer drop-off point",
                               "alternatives": ["shelter in place above ground floor until the next trip"]})
            continue
        x, eta, path = best
        _, back = travel(x, hnode[h], base_n)
        free_at[x["id"]] = eta + float(x.get("service_s", 300)) + back
        pos[x["id"]] = base_n
        status[h] = "assigned"
        slack = None if d is None else d - eta
        street = max(((w.edge_name[e], w.edge_len[e]) for e in path if w.edge_name[e]), key=lambda p: p[1], default=("local streets", 0))[0]
        assignments.append(dict(id=f"a-{x['id']}-{h}", resource=x, task="rescue", target={"household_id": h}, path=path, eta=eta, deadline=d,
                                dispatched=plan_t_s if x["id"] not in first_job else None,
                                rationale=(f"{x['name']} → household #{h}: {nd['people']} people ≤ capacity {x['capacity_people']}"
                                           + (", accessible" if nd.get("mobility") else "")
                                           + (f"; deadline {d/60:.0f} min, ETA {eta/60:.0f} min (slack {slack/60:.0f} min)" if d is not None else f"; not flooded, ETA {eta/60:.0f} min")
                                           + f"; via {street}")))
        first_job.setdefault(x["id"], assignments[-1]["id"])

    for h, nd in needs.items():
        if nd == "unknown":
            judge = any(hh.get("judge") for hh in scn["households"] if hh["household_id"] == h)
            unresolved.append({"target": {"household_id": h}, "need": "unknown", "blocked_by": "needs unknown",
                               "would_unblock": "how many people, and whether anyone needs a wheelchair-accessible vehicle",
                               "alternatives": ["hold the accessible van after its current pickup", "send a standard van if no mobility need"]})
            info_requests.append({"id": f"q-{h}", "to": {"household_id": h},
                                  "question": "How many people are with you, and does anyone need a wheelchair-accessible vehicle?",
                                  "why": ("the accessible van is the scarce resource; your answer decides its next trip"
                                          if judge else "needed to schedule a pickup before the water reaches your street")})
    hosp = [k for k, f in fac.items() if f["type"] == "hospital"]
    if hosp:
        info_requests.append({"id": f"q-{hosp[0]}", "to": {"facility_id": hosp[0]}, "question": "How many hours of backup fuel do you have on site right now?",
                              "why": "decides whether the big generator stays at the pumping station or moves to the hospital"})

    # positions at t_s along each first job's route
    tl = facility_timeline(scn, t_s, gen_at)
    out_assign, out_res = [], []
    by_res = {}
    for a in assignments:
        by_res.setdefault(a["resource"]["id"], []).append(a)
    for x in res:
        r = {"id": x["id"], "kind": x["kind"], "name": x["name"], "status": "available", "assignment_id": None, "eta_s": None,
             "node": None, "edge_id": None, "heading_deg": None, "fuel_l": float(x.get("fuel_l", 0)), "km_driven": 0.0}
        for k in ("capacity_people", "accessible", "kw", "connector"):
            if k in x:
                r[k] = x[k]
        if x["kind"] in ("van", "accessible_van", "truck"):
            r["people_on_board"] = 0
        lon, lat = w.node_lon[x["_n"]], w.node_lat[x["_n"]]
        r["node"] = int(w.node_id[x["_n"]])
        if x["id"] in held or x.get("reserved"):
            r["status"] = "reserved"
        jobs = by_res.get(x["id"], [])
        if jobs:
            a = jobs[0]
            elapsed = t_s - (a["dispatched"] if a.get("dispatched") is not None else plan_t_s)
            tt = np.array([w.edge_tt[e] / float(x.get("speed_factor", 1.0)) for e in a["path"]])
            cum = np.concatenate([[0.0], np.cumsum(tt)])
            km = 0.0
            if elapsed >= cum[-1]:
                r["status"] = "working"
                n = int(w.edge_v[a["path"][-1]]) if a["path"] else x["_n"]
                lon, lat = w.node_lon[n], w.node_lat[n]
                r["node"] = int(w.node_id[n])
                km = float(w.edge_len[a["path"]].sum()) / 1000 if a["path"] else 0.0
            else:
                i = int(np.searchsorted(cum, elapsed, side="right")) - 1
                e = a["path"][i]
                frac = (elapsed - cum[i]) / max(tt[i], 1e-6)
                xx, yy = w.edge_pos_to_xy(np.array([e]), np.array([frac * w.edge_len[e]]))
                lon, lat = (float(v[0]) for v in w.xy_to_lonlat(xx, yy))
                r["status"], r["node"], r["edge_id"] = "en_route", None, eid(e)
                km = (float(w.edge_len[a["path"][:i]].sum()) + frac * w.edge_len[e]) / 1000
            r["assignment_id"], r["eta_s"] = a["id"], round(a["eta"], 1)
            r["km_driven"] = round(km, 2)
            r["fuel_l"] = round(r["fuel_l"] - km * float(x.get("fuel_l_per_km", 0)), 1)
        r["lon"], r["lat"] = round(float(lon), 6), round(float(lat), 6)
        out_res.append(r)
        for j, a in enumerate(jobs):
            st = ("working" if r["status"] == "working" else "en_route") if j == 0 else "proposed"
            route = [[round(float(c[0]), 6), round(float(c[1]), 6)] for e in a["path"] for c in town["edges"][e]["geom"]]
            out_assign.append({"id": a["id"], "plan_version": 2, "resource_id": x["id"], "task": a["task"], "target": a["target"],
                               "dropoff_facility_id": base if a["task"] == "rescue" else None, "eta_s": round(a["eta"], 1),
                               "deadline_s": a["deadline"], "slack_s": None if a["deadline"] is None else round(a["deadline"] - a["eta"], 1),
                               "status": st, "rationale": a["rationale"], "route_edges": [eid(e) for e in a["path"]], "route": route})
    a_of = {a["target"].get("household_id"): a for a in out_assign if "household_id" in a["target"]}
    for h, a in a_of.items():
        if a["status"] in ("en_route", "working"):
            status[h] = "confirmed"

    households = []
    for h in scn["households"]:
        hid = h["household_id"]
        src = hh_by_id[hid]
        entry = {"household_id": hid, "label": h.get("label", f"household #{hid}"), "lon": src["lon"], "lat": src["lat"], "node": src["node"],
                 "judge": bool(h.get("judge")), "phone_role": h.get("phone_role", "none"), "needs": needs[hid], "needs_source": needs_src[hid],
                 "deadline_s": dl["households"].get(hid), "status": status.get(hid, "needs"),
                 "assignment_id": a_of[hid]["id"] if hid in a_of else None}
        households.append(entry)

    facilities = []
    for k, f in fac.items():
        node, lon, lat = place[k]
        t_, st, left, since = tl[k][-1]
        entry = {"id": k, "type": f["type"], "name": f["name"], "lon": lon, "lat": lat, "node": node, "synthetic": bool(f.get("synthetic")),
                 "critical": bool(f.get("critical")), "state": st, "state_since_t_s": since, "endurance_left_s": left,
                 "powered_by": next((a["resource_id"] for a in out_assign if a["target"].get("facility_id") == k and k in gen_at and t_s >= gen_at[k]), None),
                 "threatened_at_s": dl["facilities"].get(k), "depends_on": f.get("depends_on", []), "consequence": f.get("consequence", "")}
        if f["type"] in ("response_base", "shelter"):
            entry["capacity_people"] = int(f.get("capacity_people", 0))
            entry["people_on_site"] = sum(needs[h["household_id"]]["people"] for h in households
                                          if h["status"] == "safe" and needs[h["household_id"]] != "unknown")
        entry["wastewater"] = wastewater_at(f, tl[k], t_s) if f.get("wastewater") else None
        facilities.append(entry)

    judge = next(h for h in households if h["judge"])
    messages = [
        {"id": "m-1", "thread": {"household_id": judge["household_id"]}, "direction": "out", "t_s": plan_t_s + 60, "plan_version": 2, "assignment_id": None,
         "report_id": None, "text": "[EMBER drill] Flood warning for your street. How many people are with you, and does anyone need a wheelchair-accessible vehicle? Reply here."},
    ]
    if hosp:
        messages.append({"id": "m-2", "thread": {"facility_id": hosp[0]}, "direction": "out", "t_s": plan_t_s + 60, "plan_version": 2, "assignment_id": None,
                         "report_id": None, "text": "[EMBER drill] Your substation is down. How many hours of backup fuel do you have on site right now?"})

    people = lambda st: sum(needs[h["household_id"]]["people"] for h in households  # noqa: E731
                            if h["status"] == st and needs[h["household_id"]] != "unknown")
    outage = sum(TICK for k, f in fac.items() if f.get("critical") for (_, s, _, _) in tl[k] if s == "down")
    service = sum(TICK for k in fac for (_, s, _, _) in tl[k] if s == "down")
    metrics = {"projected": False, "people_reached_before_deadline": people("safe"), "people_unreached": people("unreached"),
               "unresolved_needs": len(unresolved), "hospital_outage_s": outage, "service_outage_s_total": service,
               "overflow_m3": sum((x["wastewater"] or {}).get("overflow_m3", 0.0) for x in facilities),
               "fuel_l": round(sum(float(x.get("fuel_l", 0)) for x in scn["resources"]) - sum(r["fuel_l"] for r in out_res), 1),
               "vehicle_km": round(sum(r["km_driven"] for r in out_res), 2), "infeasible_assignments": 0,
               "reserve_remaining": sum(r["status"] == "reserved" for r in out_res), "replan_latency_s": None}

    return {
        "version": "0.1", "scenario_id": scn["scenario_id"], "t_s": float(t_s), "plan_version": 2, "source": "engine-example",
        "synthetic": [f"plan v2 from the example planner (deadline-ordered greedy), not the allocator",
                      f"household outcomes before {plan_t_s/60:.0f} min (plan v1) are illustrative",
                      "messages are examples of what the backend sends"] + scn.get("synthetic", []),
        "hazard": hazard, "closures": closures, "households": households, "facilities": facilities, "resources": out_res,
        "plan": {"version": 2, "parent_version": 1, "created_at_t_s": plan_t_s, "planner": "example",
                 "trigger": next((f"{f['name']} down at {ev['t_s']/60:.0f} min (scenario event)" for f in scn["facilities"]
                                  for ev in f.get("events", []) if ev["t_s"] <= plan_t_s), "scheduled replan"),
                 "assignments": out_assign,
                 "changes": [{"assignment_id": a["id"], "change": "added"} for a in out_assign if a["task"] == "rescue"],
                 "unresolved": unresolved, "info_requests": info_requests, "metrics": dict(metrics)},
        "reports": reports, "messages": messages, "metrics": metrics,
    }


# ---------- validation ----------
def validate_state(state: dict, scn: dict | None, town: dict) -> list[str]:
    """Schema errors + references (edge / household / facility / resource / assignment ids)."""
    import jsonschema
    from referencing import Registry, Resource

    reg = Registry()
    for p in CONTRACTS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        reg = reg.with_resource(s["$id"], Resource.from_contents(s))
    schema = json.loads((CONTRACTS / "state.schema.json").read_text())
    errs = [f"schema: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:300]}"
            for e in jsonschema.Draft202012Validator(schema, registry=reg).iter_errors(state)]
    if errs:
        return errs
    E = errs.append
    n_edges = len(town["edges"])
    hh_ids = {h["id"] for h in town["households"]}
    fac_ids = {f["id"] for f in state["facilities"]}
    res_ids = {r["id"] for r in state["resources"]}
    asg_ids = {a["id"] for a in (state["plan"] or {}).get("assignments", [])}
    for c in state["closures"]:
        if not 0 <= c["edge_id"] < n_edges:
            E(f"closures: edge {c['edge_id']} not in town.json")
    for h in state["households"]:
        if h["household_id"] not in hh_ids:
            E(f"households: {h['household_id']} not in town.json")
        if h["assignment_id"] and h["assignment_id"] not in asg_ids:
            E(f"households: {h['household_id']} points at unknown assignment {h['assignment_id']}")
    for f in state["facilities"]:
        for d in f.get("depends_on", []):
            if d not in fac_ids:
                E(f"facility {f['id']}: depends_on {d} unknown")
        if f.get("powered_by") and f["powered_by"] not in res_ids:
            E(f"facility {f['id']}: powered_by {f['powered_by']} is not a resource")
    for r in state["resources"]:
        if r["assignment_id"] and r["assignment_id"] not in asg_ids:
            E(f"resource {r['id']}: unknown assignment {r['assignment_id']}")
    assisted = {h["household_id"] for h in state["households"]}
    for a in (state["plan"] or {}).get("assignments", []):
        if a["resource_id"] not in res_ids:
            E(f"assignment {a['id']}: resource {a['resource_id']} unknown")
        t = a["target"]
        if "household_id" in t and t["household_id"] not in assisted:
            E(f"assignment {a['id']}: household {t['household_id']} is not assisted")
        if "facility_id" in t and t["facility_id"] not in fac_ids:
            E(f"assignment {a['id']}: facility {t['facility_id']} unknown")
        if any(not 0 <= e < n_edges for e in a.get("route_edges", [])):
            E(f"assignment {a['id']}: route edge not in town.json")
    if scn is not None:
        if state["scenario_id"] != scn["scenario_id"]:
            E(f"scenario_id {state['scenario_id']} != {scn['scenario_id']}")
        want = {h["household_id"] for h in scn["households"]}
        if assisted != want:
            E(f"households: state has {len(assisted)}, scenario has {len(want)} (mismatch: {sorted(assisted ^ want)[:5]})")
    return errs


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())
