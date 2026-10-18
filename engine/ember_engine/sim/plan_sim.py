"""Plan simulator (TECHNICAL.md §3.4): execute a plan's assignments as a timeline and score it.

    res = simulate(world, scenario, plan, reports=[...], perturbation={...})
    res.metrics        # §3.4 metrics (projected over the horizon)
    res.outcomes       # per assignment: done / infeasible / incomplete, times, met_deadline, reason
    res.events         # pickups, drop-offs, connections, stalls, facility changes, overflow start, reports
    res.state_at(t_s)  # a contracts/state.schema.json snapshot at any simulated time

Each resource works its assignments in plan order. rescue: drive to the household → service (pickup;
checks needs known, capacity, accessibility) → drive to the drop-off → unload (household safe).
protect: drive the generator to the facility → connect_s → powers it if compatible (stays there).
clear_road: drive to the road → service → reopens report closures on those edges.
Deterministic: same inputs, same result. No LLM, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..models.facilities import FacilityModel, compatible
from ..models.resources import Mover
from ..models.wastewater import Wastewater
from ..scenario import deadlines, flood_keyframes

VEHICLES = {"van", "accessible_van", "ambulance", "truck"}
UNLOAD_S = 120.0
ABANDON_S = 900.0   # no open route to the target for this long → give up and take the next assignment
POOL_DETOUR_S = 180.0   # after a pickup, a vehicle with seats collects its next household first if it is this close


@dataclass
class Outcome:
    assignment_id: str
    resource_id: str
    task: str
    target: dict
    status: str = "pending"            # pending | en_route | working | done | infeasible | incomplete
    reason: str = ""
    start_t: float | None = None
    arrive_t: float | None = None
    complete_t: float | None = None    # rescue: drop-off; protect: connected; clear: reopened
    pickup_t: float | None = None
    end_t: float | None = None         # when it stopped (done, infeasible, abandoned, cancelled)
    deadline_s: float | None = None
    met_deadline: bool | None = None
    people: int = 0
    shared_after: str | None = None    # rescue: picked up on the same trip, right after this assignment
    route_edges: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "route_edges"} | {"route_edges": list(self.route_edges)}


@dataclass
class SimResult:
    world: object
    scenario: dict
    plan: dict
    t0: float
    dt: float
    metrics: dict
    outcomes: list
    events: list
    timeline: dict
    reports: list
    edge_closed_t: np.ndarray           # first time each edge was closed (nan = never)
    edge_reopened_t: np.ndarray

    def tick_index(self, t_s: float) -> int:
        return int(np.clip(np.floor((t_s - self.t0) / self.dt + 1e-9), 0, len(self.timeline["t_s"]) - 1))

    def state_at(self, t_s: float) -> dict:
        from .snapshot import snapshot
        return snapshot(self, t_s)


def _flood_masks(world, scn: dict):
    """(frames, keyframe times, closed-edge mask per keyframe), cached on the world per scenario keyframe list:
    the allocator simulates the same scenario hundreds of times."""
    import shapely
    kfs = scn["hazard"].get("keyframes", [])
    key = (scn.get("scenario_id"), id(kfs), len(kfs), tuple(k["t_s"] for k in kfs))
    cache = world.__dict__.setdefault("_flood_cache", {})
    if key not in cache:
        if len(cache) > 32:
            cache.clear()
        frames = flood_keyframes(scn, world)
        lines = world.edge_lines()
        cache[key] = (frames, np.array([t for t, _ in frames]) if frames else np.zeros(0),
                      [shapely.intersects(g, lines) if not g.is_empty else np.zeros(world.n_edges, bool) for _, g in frames])
    return cache[key]


def _report_events(scn: dict, reports, delay_s: float) -> list[dict]:
    """Scripted scenario reports + live reports (report.schema) → one sorted event list."""
    ev = []
    for i, r in enumerate(scn.get("scripted_reports", [])):
        e = {"id": f"s-{i + 1}", "source": "scenario", "t_s": float(r["t_s"]), "kind": r["kind"]}
        for k in ("household_id", "facility_id", "edge_ids", "note"):
            if k in r:
                e[k] = r[k]
        if r["kind"] == "need":
            e["needs"] = dict(r["needs"])
        if r["kind"] == "facility_status":
            e["set"] = dict(r.get("set", {}))
        ev.append(e)
    for r in reports or []:
        p = r.get("payload", {})
        e = {"id": r["id"], "source": r.get("source", "resident"), "t_s": float(r["observed_at_t_s"]) + delay_s, "kind": r["kind"]}
        for k in ("household_id", "facility_id", "assignment_id"):
            if k in r:
                e[k] = r[k]
        if r["kind"] == "need":
            e["needs"] = {k: p[k] for k in ("people", "mobility", "accessible_vehicle", "medical") if k in p}
        elif r["kind"] == "closure_report":
            e["edge_ids"] = list(p.get("edge_ids", []))
        elif r["kind"] == "facility_status":
            e["set"] = dict(p.get("set", {}))
        ev.append(e)
    return sorted(ev, key=lambda e: e["t_s"])


LIVE_STATUSES = ("proposed", "offered", "confirmed")


def cut_at(a: dict) -> float | None:
    """When an assignment stops counting: its cancel time, or −1 for a decline with no time (never dispatched).
    A live status wins over a stale cancel time (a decline the person took back)."""
    status = a.get("status")
    if status in LIVE_STATUSES:
        return None
    if a.get("cancelled_at_t_s") is not None:
        return float(a["cancelled_at_t_s"])
    return -1.0 if status == "rejected" else None


def simulate(world, scn: dict, plan: dict, reports=(), perturbation: dict | None = None,
             t0: float = 0.0, t_end: float | None = None, dt: float | None = None, record: bool = True) -> SimResult:
    """record=False skips the per-tick replay (state_at unavailable): use it for candidate scoring."""
    pert = perturbation or {}
    dt = float(dt or scn.get("tick_s", 60.0))
    t_end = float(t_end if t_end is not None else scn["t_end_s"])
    tt_mult = float(pert.get("travel_time_mult", 1.0))
    from ..traffic_bg import table as traffic_table
    traffic = traffic_table(world, scn)   # None unless the scenario has background traffic (D73)

    # ---------- hazard: closed mask per keyframe (latest keyframe ≤ t applies) ----------
    frames, kf_t, kf_mask = _flood_masks(world, scn)
    report_closed = np.zeros(world.n_edges, dtype=bool)
    extra = [(float(t), list(e)) for t, e in pert.get("extra_closures", [])]

    def hazard_mask(t):
        i = int(np.searchsorted(kf_t, t, side="right")) - 1
        return kf_mask[i] if i >= 0 else np.zeros(world.n_edges, bool)

    # ---------- facilities, wastewater ----------
    fac = {f["id"]: f for f in scn["facilities"]}
    fm = FacilityModel(scn["facilities"], endurance_scale=float(pert.get("endurance_scale", 1.0)))
    ww = {k: Wastewater(f["wastewater"], storage_scale=float(pert.get("storage_scale", 1.0)), inflow_scale=float(pert.get("inflow_scale", 1.0)),
                        lead_s=float(pert.get("storm_lead_s", 0.0))) for k, f in fac.items() if f.get("wastewater")}
    assets = {a["id"]: a for a in world.assets}

    def fac_node(k):
        f = fac[k]
        return world.node_index(f["node"] if "node" in f else assets[f["asset_id"]]["node"])

    base = next(k for k, f in fac.items() if f["type"] in ("response_base", "shelter"))
    on_site = {k: 0 for k, f in fac.items() if f["type"] in ("response_base", "shelter")}

    # ---------- households ----------
    dl_key = ("dl",) + (scn.get("scenario_id"), id(scn["hazard"].get("keyframes", [])), float(scn.get("deadline_margin_s", 900)))
    dcache = world.__dict__.setdefault("_flood_cache", {})
    if dl_key not in dcache:
        dcache[dl_key] = deadlines(scn, world, frames)["households"]
    dl = dcache[dl_key]
    rows = {int(h): i for i, h in enumerate(world.hh_id)}
    hh = {}
    for h in scn["households"]:
        hid = h["household_id"]
        hh[hid] = {"needs": h["needs"], "needs_source": "scenario", "node": int(world.hh_node[rows[hid]]),
                   "deadline": dl.get(hid), "status": "unknown" if h["needs"] == "unknown" else "needs",
                   "pickup_t": None, "safe_t": None, "assignment": None}

    # ---------- resources + queues ----------
    assigns = list(plan.get("assignments", []))
    queues = {x["id"]: [a for a in assigns if a["resource_id"] == x["id"]] for x in scn["resources"]}
    out = {a["id"]: Outcome(a["id"], a["resource_id"], a["task"], a["target"]) for a in assigns}
    for a in assigns:
        if "household_id" in a["target"] and a["target"]["household_id"] in hh and cut_at(a) is None:
            h = hh[a["target"]["household_id"]]
            h["assignment"] = h["assignment"] or a["id"]
            if h["status"] == "needs":
                h["status"] = "assigned"
    res = {}
    for x in scn["resources"]:
        start = fac_node(x["at_facility"]) if "at_facility" in x else world.node_index(x["node"])
        res[x["id"]] = {"spec": x, "phase": "idle", "cur": None, "timer": 0.0, "on_board": 0, "failed": False, "aboard": [],
                        "mv": Mover(world, x["id"], start, speed_factor=float(x.get("speed_factor", 1.0)),
                                    fuel_l=float(x.get("fuel_l", float("inf"))), fuel_l_per_km=float(x.get("fuel_l_per_km", 0.0)),
                                    tt_mult=tt_mult, traffic=traffic)}
    fail = pert.get("resource_failure")   # {"resource_id": ..., "t_s": ...}

    def to_dropoff(r, t, closed):
        """Head for the drop-off of the people on board (after the last pickup of a trip, or a failed one)."""
        first = r["aboard"][0]
        r["mv"].go(fac_node(first.get("dropoff_facility_id") or base), closed)
        r["phase"], r["cur"] = "to_dropoff", r["aboard"][-1]

    def release(r, t, closed):
        """The current leg ended without a pickup: drop off whoever is aboard, else go idle."""
        if r["aboard"]:
            to_dropoff(r, t, closed)
        else:
            r["phase"], r["cur"] = "idle", None

    def pool_next(rid, r, t, closed):
        """The vehicle's next rescue, if it is worth collecting before the drop-off (same drop-off, seats, access, close)."""
        q = queues[rid]
        b = q[0] if q else None
        if b is None or b["task"] != "rescue" or cut_at(b) is not None or float(b.get("not_before_t_s") or 0.0) > t:
            return None
        if (b.get("dropoff_facility_id") or base) != (r["aboard"][0].get("dropoff_facility_id") or base):
            return None
        h = hh.get(b["target"].get("household_id"))
        if h is None or h["needs"] == "unknown" or h["status"] in ("picked_up", "safe"):
            return None
        need, spec = h["needs"], r["spec"]
        if (need.get("mobility") or need.get("accessible_vehicle")) and not spec.get("accessible"):
            return None
        if need["people"] + r["on_board"] > spec.get("capacity_people", 0):
            return None
        here = r["mv"].node
        if traffic is not None:
            tbin = r["mv"]._bin()
            secs = world.route(here, h["node"], closed, weight=world.edge_tt * traffic[tbin], weight_key=("traffic", id(traffic), tbin))[1]
        else:
            secs = world.route(here, h["node"], closed)[1]
        secs /= float(spec.get("speed_factor", 1.0))
        return b if secs <= POOL_DETOUR_S else None

    events: list[dict] = []
    revs = _report_events(scn, reports, float(pert.get("report_delay_s", 0.0)))
    applied = []
    ri = 0
    closed_t = np.full(world.n_edges, np.nan)
    reopened_t = np.full(world.n_edges, np.nan)
    T = {"t_s": [], "closed_n": [], "res": {k: {"lon": [], "lat": [], "status": [], "edge": [], "node": [], "assignment": [], "on_board": [], "fuel": [], "km": []} for k in res},
         "fac": {k: {"state": [], "endurance_left": [], "generator": []} for k in fac},
         "ww": {k: {"storage_m3": [], "overflow_m3": [], "inflow_m3ph": [], "pumped_m3ph": []} for k in ww},
         "hh": {k: {"status": [], "needs": []} for k in hh}, "on_site": {k: [] for k in on_site}}

    def finish(o: Outcome, status: str, t: float, reason: str = ""):
        o.status, o.reason = status, reason
        o.end_t = t
        if status == "done" and o.complete_t is None:
            o.complete_t = t
        events.append({"t_s": t, "kind": f"assignment_{status}", "assignment_id": o.assignment_id, "resource_id": o.resource_id,
                       "reason": reason})

    t = t0
    while t < t_end - 1e-9:
        # 1) reports and perturbation events due this tick
        while ri < len(revs) and revs[ri]["t_s"] < t + dt:
            e = revs[ri]; ri += 1
            if e["kind"] == "need" and e.get("household_id") in hh:
                h = hh[e["household_id"]]
                h["needs"], h["needs_source"] = e["needs"], "report"
                if h["status"] == "unknown":
                    h["status"] = "assigned" if h["assignment"] else "needs"
            elif e["kind"] == "facility_status" and e.get("facility_id") in fac:
                fm.apply_status(e["facility_id"], e.get("set", {}))
            elif e["kind"] == "closure_report":
                report_closed[[i for i in e.get("edge_ids", []) if 0 <= i < world.n_edges]] = True
            applied.append(e)
            events.append({"t_s": t, "kind": "report", "report_id": e["id"], "report_kind": e["kind"]})
        for et, eids in extra:
            if t <= et < t + dt:
                report_closed[[i for i in eids if 0 <= i < world.n_edges]] = True
        if fail and t <= float(fail["t_s"]) < t + dt and fail["resource_id"] in res:
            r = res[fail["resource_id"]]
            r["failed"] = True
            events.append({"t_s": t, "kind": "resource_failed", "resource_id": fail["resource_id"]})
            if r["cur"] is not None:
                finish(out[r["cur"]["id"]], "incomplete", t, "resource failed")

        closed = hazard_mask(t) | report_closed
        newly = closed & np.isnan(closed_t)
        closed_t[newly] = t

        # 2) resources
        for rid, r in res.items():
            if r["failed"]:
                continue
            spec, mv = r["spec"], r["mv"]
            mv.t_now = t
            cur = r["cur"]
            if cur is not None and cut_at(cur) is not None and cut_at(cur) <= t \
                    and r["phase"] in ("to_target", "service", "working") and r["on_board"] == 0:
                if r["phase"] == "working" and cur["task"] == "protect":   # connected generator moves on
                    fm.disconnect_generator(cur["target"]["facility_id"])
                    events.append({"t_s": t, "kind": "generator_disconnected", "facility_id": cur["target"]["facility_id"], "resource_id": rid})
                    out[cur["id"]].reason = "moved by replan"
                else:
                    finish(out[cur["id"]], "incomplete", t, "cancelled by replan")
                mv.dest, mv.route = None, []
                r["phase"], r["cur"], r["last"] = "idle", None, None
            while r["phase"] == "idle" and queues[rid] and cut_at(queues[rid][0]) is not None and cut_at(queues[rid][0]) <= t:
                finish(out[queues[rid].pop(0)["id"]], "incomplete", t, "cancelled by replan")
            if r["phase"] == "idle" and queues[rid] and float(queues[rid][0].get("not_before_t_s") or 0.0) <= t:
                a = queues[rid].pop(0)
                o = out[a["id"]]
                r["cur"], o.start_t = a, t
                tgt = a["target"]
                if a["task"] == "rescue":
                    dest = hh[tgt["household_id"]]["node"] if tgt.get("household_id") in hh else None
                elif a["task"] == "protect":
                    dest = fac_node(tgt["facility_id"]) if tgt.get("facility_id") in fac else None
                else:
                    eids = [i for i in tgt.get("edge_ids", []) if 0 <= i < world.n_edges]
                    dest = int(world.edge_u[eids[0]]) if eids else None
                if dest is None:
                    finish(o, "infeasible", t, "unknown target"); r["cur"] = None
                    continue
                if a["task"] == "rescue":
                    o.deadline_s = hh[tgt["household_id"]]["deadline"]
                mv.go(dest, closed)
                o.route_edges = list(mv.route)
                o.status = "en_route"
                r["phase"] = "to_target"
                events.append({"t_s": t, "kind": "dispatch", "assignment_id": a["id"], "resource_id": rid})

            if r["phase"] in ("to_target", "to_dropoff"):
                st = mv.advance(dt, closed)
                if st == "no_fuel":
                    finish(out[r["cur"]["id"]], "incomplete", t, "out of fuel"); r["failed"] = True
                    continue
                if st == "stalled" and r.get("last") != "stalled":
                    events.append({"t_s": t, "kind": "stalled", "resource_id": rid, "assignment_id": r["cur"]["id"]})
                    r["stall_since"] = t
                r["last"] = st
                if st == "stalled" and r["phase"] == "to_target" and t + dt - r["stall_since"] >= ABANDON_S:
                    finish(out[r["cur"]["id"]], "incomplete", t, f"no open route to the target for {ABANDON_S/60:.0f} min")
                    mv.dest, mv.route = None, []
                    r["last"] = None
                    release(r, t, closed)
                    continue
                if st != "arrived":
                    continue
                a, o = r["cur"], out[r["cur"]["id"]]
                if r["phase"] == "to_dropoff":   # unload everyone on this trip
                    drop = r["aboard"][0].get("dropoff_facility_id") or base
                    for b_ in r["aboard"]:
                        hid = b_["target"]["household_id"]
                        hh[hid]["status"], hh[hid]["safe_t"] = "safe", t + UNLOAD_S
                        ob = out[b_["id"]]
                        ob.complete_t = t + UNLOAD_S
                        finish(ob, "done", t + UNLOAD_S)
                        events.append({"t_s": t, "kind": "dropoff", "assignment_id": b_["id"], "household_id": hid, "facility_id": drop})
                    on_site[drop] = on_site.get(drop, 0) + r["on_board"]
                    r["on_board"], r["aboard"] = 0, []
                    r["phase"], r["timer"], r["cur"] = "unload", UNLOAD_S, a
                    continue
                o.arrive_t = t
                tgt = a["target"]
                if a["task"] == "rescue":
                    h = hh[tgt["household_id"]]
                    need = h["needs"]
                    if h["status"] in ("picked_up", "safe"):
                        finish(o, "infeasible", t, "already picked up by another resource"); release(r, t, closed)
                        continue
                    if need == "unknown":
                        finish(o, "incomplete", t, "needs unknown on arrival"); release(r, t, closed)
                        continue
                    if (need.get("mobility") or need.get("accessible_vehicle")) and not spec.get("accessible"):
                        finish(o, "infeasible", t, "needs an accessible vehicle"); release(r, t, closed)
                        continue
                    if need["people"] + r["on_board"] > spec.get("capacity_people", 0):
                        finish(o, "infeasible", t, f"{need['people']} people > capacity {spec.get('capacity_people', 0)}")
                        release(r, t, closed)
                        continue
                    r["phase"], r["timer"] = "service", float(spec.get("service_s", 300))
                elif a["task"] == "protect":
                    ok, why = compatible(spec, fac[tgt["facility_id"]])
                    if not ok:
                        finish(o, "infeasible", t, why); r["phase"], r["cur"] = "idle", None
                        continue
                    r["phase"], r["timer"] = "service", float(fac[tgt["facility_id"]].get("connect_s", 900))
                else:
                    r["phase"], r["timer"] = "service", float(spec.get("service_s", 1200))
                o.status = "working"
                events.append({"t_s": t, "kind": "arrive", "assignment_id": a["id"], "resource_id": rid})
                continue

            if r["phase"] in ("service", "unload"):
                r["timer"] -= dt
                if r["timer"] > 1e-9:
                    continue
                a, o = r["cur"], out[r["cur"]["id"]]
                done_t = t + dt + r["timer"]
                if r["phase"] == "unload":
                    r["phase"], r["cur"] = "idle", None
                    continue
                if a["task"] == "rescue":
                    hid = a["target"]["household_id"]
                    h = hh[hid]
                    o.people = int(h["needs"]["people"])
                    o.pickup_t = done_t
                    o.met_deadline = h["deadline"] is None or done_t <= h["deadline"]
                    h["status"], h["pickup_t"] = "picked_up", done_t
                    r["on_board"] += o.people
                    r["aboard"].append(a)
                    events.append({"t_s": done_t, "kind": "pickup", "assignment_id": a["id"], "household_id": hid, "people": o.people,
                                   "met_deadline": o.met_deadline})
                    nxt = pool_next(rid, r, t, closed)
                    if nxt is None:
                        to_dropoff(r, t, closed)
                    else:   # shared trip: collect the next household before the drop-off
                        queues[rid].pop(0)
                        o2 = out[nxt["id"]]
                        r["cur"], o2.start_t, o2.shared_after = nxt, t, a["id"]
                        o2.deadline_s = hh[nxt["target"]["household_id"]]["deadline"]
                        mv.go(hh[nxt["target"]["household_id"]]["node"], closed)
                        o2.route_edges, o2.status = list(mv.route), "en_route"
                        r["phase"] = "to_target"
                        events.append({"t_s": t, "kind": "dispatch", "assignment_id": nxt["id"], "resource_id": rid, "shared_after": a["id"]})
                elif a["task"] == "protect":
                    fid = a["target"]["facility_id"]
                    fm.connect_generator(fid, rid)
                    o.complete_t = done_t
                    finish(o, "done", done_t)
                    events.append({"t_s": done_t, "kind": "generator_connected", "facility_id": fid, "resource_id": rid})
                    r["phase"] = "working"     # a connected generator stays put
                else:
                    eids = [i for i in a["target"]["edge_ids"] if 0 <= i < world.n_edges]
                    report_closed[eids] = False
                    reopened_t[eids] = done_t
                    o.complete_t = done_t
                    finish(o, "done", done_t)
                    events.append({"t_s": done_t, "kind": "road_cleared", "edge_ids": eids})
                    r["phase"], r["cur"] = "idle", None

        # 3) facilities + wastewater
        events.extend(fm.step(t, dt))
        for k, w_ in ww.items():
            downstream = all(fm.state[d] != "down" for d in fac[k].get("depends_on", []) if fac[d]["type"] == "outfall")
            before = w_.overflow_started_t
            w_.step(t, dt, fm.powered(k), downstream)
            if before is None and w_.overflow_started_t is not None:
                events.append({"t_s": t, "kind": "overflow_started", "facility_id": k})

        # 4) deadlines
        for hid, h in hh.items():
            if h["deadline"] is not None and t >= h["deadline"] and h["status"] in ("needs", "assigned", "unknown"):
                h["status"] = "unreached"
                events.append({"t_s": t, "kind": "deadline_missed", "household_id": hid})

        # 5) record
        if not record:
            t += dt
            continue
        T["t_s"].append(t)
        T["closed_n"].append(int(closed.sum()))
        for rid, r in res.items():
            lon, lat = r["mv"].lonlat()
            rt = T["res"][rid]
            rt["lon"].append(round(lon, 6)); rt["lat"].append(round(lat, 6))
            rt["status"].append(_res_status(r)); rt["edge"].append(int(r["mv"].edge))
            rt["node"].append(int(world.node_id[r["mv"].node]) if r["mv"].edge < 0 else None)
            rt["assignment"].append(r["cur"]["id"] if r["cur"] is not None else None)
            rt["on_board"].append(r["on_board"]); rt["fuel"].append(round(r["mv"].fuel_l, 2) if np.isfinite(r["mv"].fuel_l) else None)
            rt["km"].append(round(r["mv"].km, 3))
        for k in fac:
            T["fac"][k]["state"].append(fm.state[k]); T["fac"][k]["endurance_left"].append(fm.endurance_left(k))
            T["fac"][k]["generator"].append(fm.generator.get(k))
        for k, w_ in ww.items():
            T["ww"][k]["storage_m3"].append(round(w_.storage, 1)); T["ww"][k]["overflow_m3"].append(round(w_.overflow, 1))
            T["ww"][k]["inflow_m3ph"].append(w_.inflow); T["ww"][k]["pumped_m3ph"].append(round(w_.pumped, 1))
        for hid, h in hh.items():
            T["hh"][hid]["status"].append(h["status"]); T["hh"][hid]["needs"].append(h["needs"])
        for k in on_site:
            T["on_site"][k].append(on_site[k])
        t += dt

    # ---------- wrap up ----------
    for o in out.values():
        if o.status in ("pending", "en_route", "working"):
            o.status, o.reason = "incomplete", o.reason or ("never started" if o.start_t is None else "not finished by t_end")
    hosp, svc = fm.outage()
    known = {hid: h for hid, h in hh.items() if h["needs"] != "unknown"}
    reached = sum(o.people for o in out.values() if o.task == "rescue" and o.pickup_t is not None and o.met_deadline)
    unreached = sum(h["needs"]["people"] for h in known.values()
                    if h["deadline"] is not None and (h["pickup_t"] is None or h["pickup_t"] > h["deadline"]))
    unresolved = sum(1 for h in hh.values() if h["pickup_t"] is None and (h["needs"] == "unknown" or h["assignment"] is None))
    used = {a["resource_id"] for a in assigns}
    metrics = {
        "projected": True,
        "people_reached_before_deadline": int(reached),
        "people_unreached": int(unreached),
        "unresolved_needs": int(unresolved),
        "hospital_outage_s": float(hosp),
        "service_outage_s_total": float(svc),
        "overflow_m3": round(float(sum(w_.overflow for w_ in ww.values())), 1),
        "fuel_l": round(float(sum(r["mv"].km * r["mv"].fuel_l_per_km for r in res.values())), 2),
        "vehicle_km": round(float(sum(r["mv"].km for r in res.values())), 2),
        "infeasible_assignments": sum(o.status == "infeasible" for o in out.values()),
        "reserve_remaining": sum(1 for rid, r in res.items() if rid not in used and not r["failed"]),
        "replan_latency_s": None,
    }
    return SimResult(world=world, scenario=scn, plan=plan, t0=t0, dt=dt, metrics=metrics,
                     outcomes=[o.as_dict() for o in out.values()], events=sorted(events, key=lambda e: e["t_s"]),
                     timeline=T, reports=applied, edge_closed_t=closed_t, edge_reopened_t=reopened_t)


def _res_status(r: dict) -> str:
    """Resource status for state.schema."""
    if r["failed"]:
        return "out_of_service"
    ph = r["phase"]
    if ph in ("to_target", "to_dropoff") and r.get("last") == "stalled":
        return "stalled"
    if ph == "to_target":
        return "en_route"
    if ph == "to_dropoff":
        return "returning"
    if ph in ("service", "unload", "working"):
        return "working"
    return "reserved" if r["spec"].get("reserved") else "available"
