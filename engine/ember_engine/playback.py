"""SimResult → contracts/playback.schema.json: the whole run as a replay the map can scrub.

The plan simulator samples every resource once per tick (lon/lat, edge, status). Vehicles cover
~1 km per tick, so drawing straight lines between samples would cut across blocks. Between two
samples a Mover drives the rest of its edge (always u → v), then the shortest open path to the next
edge, then part of that edge; we rebuild that from the town geometry, keep it only if its length
matches the km the Mover logged for the tick (else a straight line), and spread the tick's seconds
over it by distance. Everything else (statuses, facility states, wastewater, closures,
events) is copied from the run, run-length encoded where it changes rarely.

Timestamps keep the simulator's convention: a sample labelled t is the state at the end of the
tick that starts at t, the same label events carry. That keeps "van at the door" and the pickup
event on the same frame.

Pure function of the run; no I/O. `ember playback` writes one; the backend serves one per plan.
"""

from __future__ import annotations

import math

import numpy as np

from .geo import local_metres

VERSION = "0.2"
_DEG = 5                      # 5 decimals of a degree ≈ 1 m
_MATCH = 0.35                 # rebuilt path must be within 35 % (+60 m) of the km the Mover logged that tick


def _rle(values: list, times: list) -> list:
    """[[t, value], ...] at each change (first sample always kept)."""
    out: list = []
    for t, v in zip(times, values):
        if not out or out[-1][1] != v:
            out.append([float(t), v])
    return out


def _edge_pts(w, e: int) -> np.ndarray:
    """Edge geometry as an (n, 2) lon/lat array, ordered u → v."""
    s, n = int(w.geom_start[e]), int(w.geom_count[e])
    lon, lat = w.xy_to_lonlat(w.geom_x[s:s + n], w.geom_y[s:s + n])
    return np.c_[lon, lat]


def _split(pts: np.ndarray, p) -> int:
    """Index of the vertex after the projection of p onto polyline pts (1..len)."""
    best, at = float("inf"), 1
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        ab = b - a
        L = float(ab @ ab)
        f = 0.0 if L == 0 else float(np.clip(((np.asarray(p) - a) @ ab) / L, 0.0, 1.0))
        d = float(np.hypot(*(a + f * ab - p)))
        if d < best:
            best, at = d, i + 1
    return at


def _leg(w, p0, e0: int, n0: int | None, p1, e1: int, n1: int | None, closed: np.ndarray) -> list:
    """Points strictly between p0 and p1 along the road the Mover drove."""
    if e0 >= 0 and e0 == e1:                      # still on the same edge
        pts = _edge_pts(w, e0)
        i, j = _split(pts, p0), _split(pts, p1)
        return [tuple(x) for x in pts[i:j]] if j > i else []
    mid: list = []
    if e0 >= 0:                                   # finish the current edge
        pts = _edge_pts(w, e0)
        mid += [tuple(x) for x in pts[_split(pts, p0):]]
        start = int(w.edge_v[e0])
    elif n0 is not None:
        start = n0
    else:
        return []
    goal = int(w.edge_u[e1]) if e1 >= 0 else n1
    if goal is None:
        return []
    if goal != start:
        path, _ = w.route(start, goal, closed)
        if not path:
            path, _ = w.route(start, goal, None)
        if not path:
            return []
        for e in path:
            mid += [tuple(x) for x in _edge_pts(w, e)[1:]]
    if e1 >= 0:                                   # the start of the edge it is on now
        pts = _edge_pts(w, e1)
        mid += [tuple(x) for x in pts[1:_split(pts, p1)]]
    return mid


def _track(w, T: dict, rid: str, closed_t: np.ndarray) -> tuple[list, list]:
    rt, ts = T["res"][rid], T["t_s"]
    node_ix = {int(n): i for i, n in enumerate(w.node_id)}
    path: list = []
    times: list = []

    def put(p, t):
        q = [round(float(p[0]), _DEG), round(float(p[1]), _DEG)]
        if path and q == path[-1] and times[-1] == t:
            return
        path.append(q)
        times.append(round(float(t), 2))

    for k in range(len(ts)):
        p1 = (rt["lon"][k], rt["lat"][k])
        if k == 0:
            put(p1, ts[0])
            continue
        p0 = (rt["lon"][k - 1], rt["lat"][k - 1])
        if p0 != p1:
            e0, e1 = int(rt["edge"][k - 1]), int(rt["edge"][k])
            n0 = node_ix.get(rt["node"][k - 1]) if rt["node"][k - 1] is not None else None
            n1 = node_ix.get(rt["node"][k]) if rt["node"][k] is not None else None
            closed = ~np.isnan(closed_t) & (closed_t <= ts[k])
            mid = _leg(w, p0, e0, n0, p1, e1, n1, closed)
            pts = [p0, *mid, p1]
            seg = [local_metres(a, b) for a, b in zip(pts, pts[1:])]
            total = sum(seg)
            driven = 1000.0 * (rt["km"][k] - rt["km"][k - 1])
            if mid and abs(total - driven) <= _MATCH * driven + 60.0:
                acc, t0, dt = 0.0, ts[k - 1], ts[k] - ts[k - 1]
                for q, d in zip(mid, seg):
                    acc += d
                    put(q, t0 + dt * acc / total)
        put(p1, ts[k])
    return _squeeze(path, times)


def _squeeze(path: list, times: list) -> tuple[list, list]:
    """Drop samples in the middle of a run of identical positions (a parked vehicle)."""
    keep = [i for i in range(len(path))
            if i == 0 or i == len(path) - 1 or not (path[i] == path[i - 1] == path[i + 1])]
    return [path[i] for i in keep], [times[i] for i in keep]


def _finite(o):
    """JSON has no inf/nan (the baseline plan's eta_s is inf until dispatch): → null, recursively."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_finite(v) for v in o]
    return o


def _target(a: dict) -> dict:
    t = a.get("target", {})
    return {"household_id": int(t["household_id"])} if "household_id" in t else dict(t)


def playback(res, planner: str | None = None, traffic: bool = True) -> dict:
    """The run as contracts/playback.schema.json v0.2 (v0.2: optional background `traffic`, D73)."""
    w, scn, plan, T = res.world, res.scenario, res.plan, res.timeline
    ts = [float(t) for t in T["t_s"]]
    names = {r["id"]: r for r in scn["resources"]}
    tracks = []
    for rid, rt in T["res"].items():
        path, times = _track(w, T, rid, res.edge_closed_t)
        spec = names.get(rid, {})
        tracks.append({
            "id": rid, "kind": spec.get("kind", ""), "name": spec.get("name", rid),
            "path": path, "t": times,
            "status": _rle(rt["status"], ts),
            "on_board": _rle(rt["on_board"], ts),
            "assignment": _rle(rt["assignment"], ts),
        })
    from .scenario import deadlines
    dl = deadlines(scn, w)["households"]
    households = [{"household_id": int(h), "deadline_s": dl.get(int(h)), "status": _rle(v["status"], ts)} for h, v in T["hh"].items()]
    facilities = [{"id": k, "state": _rle(v["state"], ts), "generator": _rle(v["generator"], ts)} for k, v in T["fac"].items()]
    closures = []
    for e in np.where(~np.isnan(res.edge_closed_t))[0]:
        r = res.edge_reopened_t[e]
        closures.append([int(w.edge_id[e]), float(res.edge_closed_t[e]), None if np.isnan(r) else float(r)])
    keep = ("id", "resource_id", "task", "target", "dropoff_facility_id", "eta_s", "deadline_s", "slack_s", "status", "rationale")
    return _finite({
        "version": VERSION,
        "scenario_id": scn["scenario_id"],
        "planner": planner or plan.get("planner", "ember"),
        "plan_version": plan.get("version"),
        "t0": float(res.t0), "dt": float(res.dt), "t_end_s": float(ts[-1] + res.dt) if ts else float(res.t0),
        "synthetic": list(scn.get("synthetic", [])),
        "t_s": ts,
        "tracks": tracks,
        "households": households,
        "facilities": facilities,
        "wastewater": {k: {"storage_m3": v["storage_m3"], "overflow_m3": v["overflow_m3"]} for k, v in T["ww"].items()},
        "on_site": {k: list(v) for k, v in T["on_site"].items()},
        "closures": closures,
        "events": [{k: v for k, v in e.items() if v is not None} for e in res.events],
        "reports": [{k: v for k, v in r.items() if v is not None} for r in res.reports],
        "outcomes": [{k: o[k] for k in ("assignment_id", "resource_id", "task", "target", "status", "reason", "arrive_t",
                                        "pickup_t", "complete_t", "deadline_s", "met_deadline", "people")} for o in res.outcomes],
        "plan": {
            "version": plan.get("version"), "planner": plan.get("planner"), "trigger": plan.get("trigger"),
            "created_at_t_s": plan.get("created_at_t_s", 0.0),
            "assignments": [{k: a[k] for k in keep if k in a} | {"target": _target(a)} for a in plan.get("assignments", [])],
            "unresolved": plan.get("unresolved", []),
            "info_requests": plan.get("info_requests", []),
            "metrics": plan.get("metrics", {}),
        },
        "metrics": dict(res.metrics),
        **({"traffic": cars} if traffic and (cars := _traffic(w, scn)) else {}),
    })


def _traffic(w, scn: dict) -> dict | None:
    """Sampled background cars for the map (synthetic, D73), cached on the world per scenario."""
    from . import traffic_bg
    cfg = traffic_bg.config(scn)
    if cfg is None:
        return None
    key = (scn.get("scenario_id"), repr(sorted(cfg.items())))
    cache = w.__dict__.setdefault("_traffic_trails", {})
    if key not in cache:
        r = traffic_bg.run(w, scn, n_trails=3000)
        cars = []
        for c in r["trails"]:
            pts, ts = c["path"], c["t"]
            moves = [i for i in range(1, len(pts)) if pts[i] != pts[i - 1]]
            if not moves:
                continue
            # on the road only: from just before it first moves to where it stops for good (exit / exposure)
            i0, i1 = moves[0] - 1, moves[-1]
            cars.append({"id": str(c["id"]), "path": [[round(x, 5), round(y, 5)] for x, y in pts[i0:i1 + 1]],
                         "t": [round(float(t)) for t in ts[i0:i1 + 1]]})
        cache[key] = {"synthetic": True, "rule": cfg["rule"], "config": cfg, "bin_s": r["bin_s"],
                      "metrics": r["metrics"], "cars": cars}
    return cache[key]
