"""SimResult → contracts/state.schema.json snapshot at any simulated time."""

from __future__ import annotations

import numpy as np


def _assignment_status(o: dict, t: float, planned: str) -> str:
    if planned == "cancelled":
        return "cancelled"
    if o["start_t"] is None or t < o["start_t"]:
        return planned
    if o["status"] == "infeasible" and (o["arrive_t"] is None or t >= o["arrive_t"]):
        return "cancelled"
    if o["arrive_t"] is None or t < o["arrive_t"]:
        return "en_route"
    if o["complete_t"] is None or t < o["complete_t"]:
        return "working"
    return "done"


def snapshot(res, t_s: float) -> dict:
    import shapely

    from ..scenario import deadlines, flood_keyframes

    w, scn, plan, T = res.world, res.scenario, res.plan, res.timeline
    i = res.tick_index(t_s)
    t = T["t_s"][i]
    eid = lambda e: int(w.edge_id[e])  # noqa: E731

    # hazard + closures
    kfs = sorted(scn["hazard"].get("keyframes", []), key=lambda k: k["t_s"])
    cur = [k for k in kfs if k["t_s"] <= t]
    nxt = [k for k in kfs if k["t_s"] > t]
    frames = flood_keyframes(scn, w)
    cur_frames = [g for ft, g in frames if ft <= t]
    hz_mask = shapely.intersects(cur_frames[-1], w.edge_lines()) if cur_frames and not cur_frames[-1].is_empty else np.zeros(w.n_edges, bool)
    open_again = ~np.isnan(res.edge_reopened_t) & (np.nan_to_num(res.edge_reopened_t, nan=np.inf) <= t)
    closed_now = ~np.isnan(res.edge_closed_t) & (np.nan_to_num(res.edge_closed_t, nan=np.inf) <= t) & (~open_again | hz_mask)
    closures = [{"edge_id": eid(e), "closed_from_t_s": float(res.edge_closed_t[e]), "source": "hazard" if hz_mask[e] else "report"}
                for e in np.where(closed_now)[0]]

    outcomes = {o["assignment_id"]: o for o in res.outcomes}
    first_assign = {}
    for a in plan.get("assignments", []):
        hid = a["target"].get("household_id")
        if hid is not None:
            first_assign.setdefault(hid, a["id"])

    # households
    dl = deadlines(scn, w, frames)
    rows = {int(h): k for k, h in enumerate(w.hh_id)}
    households = []
    for h in scn["households"]:
        hid = h["household_id"]
        r = rows[hid]
        needs = T["hh"][hid]["needs"][i]
        households.append({"household_id": hid, "label": h.get("label", f"household #{hid}"),
                           "lon": float(w.hh_lon[r]), "lat": float(w.hh_lat[r]), "node": int(w.node_id[w.hh_node[r]]),
                           "judge": bool(h.get("judge")), "phone_role": h.get("phone_role", "none"),
                           "needs": needs, "needs_source": "scenario" if needs == h["needs"] else "report",
                           "deadline_s": dl["households"].get(hid), "status": T["hh"][hid]["status"][i],
                           "assignment_id": first_assign.get(hid)})

    # facilities
    assets = {a["id"]: a for a in w.assets}
    facilities = []
    for f in scn["facilities"]:
        k = f["id"]
        node = f["node"] if "node" in f else assets[f["asset_id"]]["node"]
        n = w.node_index(node)
        hist = T["fac"][k]["state"][: i + 1]
        since = next((T["t_s"][j] for j in range(len(hist) - 1, 0, -1) if hist[j] != hist[j - 1]), T["t_s"][0])
        entry = {"id": k, "type": f["type"], "name": f["name"],
                 "lon": float(assets[f["asset_id"]]["lon"]) if "asset_id" in f else float(w.node_lon[n]),
                 "lat": float(assets[f["asset_id"]]["lat"]) if "asset_id" in f else float(w.node_lat[n]),
                 "node": int(node), "synthetic": bool(f.get("synthetic")), "critical": bool(f.get("critical")),
                 "state": hist[-1], "state_since_t_s": float(since), "endurance_left_s": T["fac"][k]["endurance_left"][i],
                 "powered_by": T["fac"][k]["generator"][i], "threatened_at_s": dl["facilities"].get(k),
                 "depends_on": f.get("depends_on", []), "consequence": f.get("consequence", ""), "wastewater": None}
        if f["type"] in ("response_base", "shelter"):
            entry["capacity_people"] = int(f.get("capacity_people", 0))
            entry["people_on_site"] = int(T["on_site"].get(k, [0] * (i + 1))[i])
        if k in T["ww"]:
            ww = T["ww"][k]
            idx = [j for j in range(i + 1) if int(round(T["t_s"][j])) % 300 == 0]
            entry["wastewater"] = {"storage_m3": ww["storage_m3"][i], "storage_max_m3": float(f["wastewater"]["storage_max_m3"]),
                                   "inflow_m3ph": float(ww["inflow_m3ph"][i]), "pumped_m3ph": float(ww["pumped_m3ph"][i]),
                                   "overflow_m3": ww["overflow_m3"][i],
                                   "series": {"t_s": [T["t_s"][j] for j in idx], "storage_m3": [ww["storage_m3"][j] for j in idx],
                                              "overflow_m3": [ww["overflow_m3"][j] for j in idx]}}
        facilities.append(entry)

    # resources
    reserved = set(plan.get("reserved", []))
    resources = []
    for x in scn["resources"]:
        rt = T["res"][x["id"]]
        st = rt["status"][i]
        if st == "available" and x["id"] in reserved:
            st = "reserved"
        aid = rt["assignment"][i]
        e = rt["edge"][i]
        r = {"id": x["id"], "kind": x["kind"], "name": x["name"], "lon": rt["lon"][i], "lat": rt["lat"][i],
             "node": rt["node"][i], "edge_id": eid(e) if e >= 0 else None, "heading_deg": None, "status": st,
             "assignment_id": aid, "eta_s": outcomes[aid]["arrive_t"] if aid and outcomes[aid]["arrive_t"] is not None else None,
             "fuel_l": rt["fuel"][i] if rt["fuel"][i] is not None else 0.0, "km_driven": rt["km"][i]}
        for k in ("capacity_people", "accessible", "kw", "connector"):
            if k in x:
                r[k] = x[k]
        if x["kind"] in ("van", "accessible_van", "truck"):
            r["people_on_board"] = int(rt["on_board"][i])
        resources.append(r)

    # plan (assignment status as of t; ETAs from the simulation)
    p_assign = []
    for a in plan.get("assignments", []):
        o = outcomes[a["id"]]
        route_edges = [eid(e) for e in o["route_edges"]]
        route = [[round(float(c[0]), 6), round(float(c[1]), 6)]
                 for e in o["route_edges"] for c in zip(*w.xy_to_lonlat(w.geom_x[w.geom_start[e]: w.geom_start[e] + w.geom_count[e]],
                                                                       w.geom_y[w.geom_start[e]: w.geom_start[e] + w.geom_count[e]]))]
        eta = o["arrive_t"] if o["arrive_t"] is not None else a.get("eta_s", 0.0)
        d = a.get("deadline_s", o["deadline_s"])
        p_assign.append({"id": a["id"], "plan_version": a.get("plan_version", plan.get("version", 1)), "resource_id": a["resource_id"],
                         "task": a["task"], "target": a["target"], "dropoff_facility_id": a.get("dropoff_facility_id"),
                         "eta_s": float(eta), "deadline_s": d, "slack_s": None if d is None else round(d - eta, 1),
                         "status": _assignment_status(o, t, a.get("status", "proposed")), "rationale": a.get("rationale", ""),
                         "not_before_t_s": a.get("not_before_t_s"), "cancelled_at_t_s": a.get("cancelled_at_t_s"),
                         "route_edges": route_edges, "route": route})
    plan_out = None
    if plan:
        plan_out = {"version": plan.get("version", 1), "parent_version": plan.get("parent_version"), "reserved": sorted(reserved),
                    "created_at_t_s": float(plan.get("created_at_t_s", 0.0)), "trigger": plan.get("trigger", ""),
                    "planner": plan.get("planner", "ember"), "assignments": p_assign, "changes": plan.get("changes", []),
                    "unresolved": plan.get("unresolved", []), "info_requests": plan.get("info_requests", []),
                    "metrics": dict(res.metrics)}

    # reports applied so far
    reports = []
    for e in res.reports:
        if e["t_s"] > t + res.dt:
            continue
        r = {"id": e["id"], "source": e["source"], "kind": e["kind"], "observed_at_t_s": e["t_s"], "confidence": 1.0, "resolved": True}
        for k in ("household_id", "facility_id", "assignment_id"):
            if k in e:
                r[k] = e[k]
        if e.get("note"):
            r["text"] = e["note"]
        if e["kind"] == "need":
            r["payload"] = dict(e["needs"])
        elif e["kind"] == "facility_status":
            r["payload"] = {"set": e.get("set", {})}
        elif e["kind"] == "closure_report":
            r["payload"] = {"edge_ids": e.get("edge_ids", [])}
        reports.append(r)

    # metrics so far
    dtk = res.dt
    hosp = sum(dtk for f in scn["facilities"] if f["type"] == "hospital" for s in T["fac"][f["id"]]["state"][: i + 1] if s == "down")
    svc = sum(dtk for f in scn["facilities"] if f["type"] in ("hospital", "clinic", "pumping_station")
              for s in T["fac"][f["id"]]["state"][: i + 1] if s == "down")
    picked = [o for o in res.outcomes if o["task"] == "rescue" and o["pickup_t"] is not None and o["pickup_t"] <= t]
    reached = sum(o["people"] for o in picked if o["met_deadline"])
    unreached = sum(h["needs"]["people"] for h in households
                    if h["needs"] != "unknown" and h["deadline_s"] is not None and h["deadline_s"] <= t
                    and not any(o["pickup_t"] is not None and o["pickup_t"] <= h["deadline_s"]
                                for o in picked if o["target"].get("household_id") == h["household_id"]))
    km = sum(r["km_driven"] for r in resources)
    fuel = sum(T["res"][x["id"]]["km"][i] * float(x.get("fuel_l_per_km", 0.0)) for x in scn["resources"])
    metrics = {"projected": False, "people_reached_before_deadline": int(reached), "people_unreached": int(unreached),
               "unresolved_needs": sum(1 for h in households if h["status"] in ("unknown",) or (h["assignment_id"] is None and h["status"] in ("needs", "unreached"))),
               "hospital_outage_s": float(hosp), "service_outage_s_total": float(svc),
               "overflow_m3": float(sum(T["ww"][k]["overflow_m3"][i] for k in T["ww"])),
               "fuel_l": round(float(fuel), 2), "vehicle_km": round(float(km), 2),
               "infeasible_assignments": sum(1 for o in res.outcomes if o["status"] == "infeasible" and o["arrive_t"] is not None and o["arrive_t"] <= t),
               "reserve_remaining": int(res.metrics["reserve_remaining"]), "replan_latency_s": None}

    return {"version": "0.2", "scenario_id": scn["scenario_id"], "t_s": float(t), "plan_version": plan.get("version") if plan else None,
            "source": "simulator", "synthetic": list(scn.get("synthetic", [])),
            "hazard": {"keyframe_t_s": cur[-1]["t_s"] if cur else None, "geometry": cur[-1]["geometry"] if cur else None,
                       "next_keyframe_t_s": nxt[0]["t_s"] if nxt else None, "keyframe_times_s": [k["t_s"] for k in kfs]},
            "closures": closures, "households": households, "facilities": facilities, "resources": resources,
            "plan": plan_out, "reports": reports, "messages": [], "metrics": metrics}
