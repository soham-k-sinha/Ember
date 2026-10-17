"""Offline tests on a synthetic grid town (no OSM, no network)."""

from __future__ import annotations

import numpy as np
import pytest

from ember_engine.geo import local_projector
from ember_engine.hazards import GrowingEllipseHazard
from ember_engine.run_job import default_job, run_job
from ember_engine.world import World

CENTER = (-71.12076, 42.36360)


def grid_town(n: int = 9, step_m: float = 120.0, hh_per_node: int = 3) -> dict:
    """n×n two-way grid centered on CENTER; exits = the four mid-side boundary nodes."""
    _, to_ll = local_projector(*CENTER)
    half = (n - 1) / 2
    nodes, idx = [], {}
    for i in range(n):
        for j in range(n):
            nid = 1000 + i * n + j
            lon, lat = to_ll((j - half) * step_m, (i - half) * step_m)
            nodes.append({"id": nid, "lon": float(lon), "lat": float(lat)})
            idx[(i, j)] = nid
    pos = {nd["id"]: (nd["lon"], nd["lat"]) for nd in nodes}
    edges = []

    def add(a, b):
        edges.append({"id": len(edges), "u": a, "v": b, "key": 0, "length_m": step_m, "lanes": 1,
                      "speed_kph": 36.0, "travel_time_s": step_m / 10.0, "capacity_vph": 1800,
                      "storage_veh": 18, "oneway": False, "highway": "residential", "name": None,
                      "geom": [list(pos[a]), list(pos[b])]})

    for i in range(n):
        for j in range(n):
            for di, dj in ((0, 1), (1, 0)):
                if i + di < n and j + dj < n:
                    add(idx[(i, j)], idx[(i + di, j + dj)])
                    add(idx[(i + di, j + dj)], idx[(i, j)])
    m = n // 2
    exits = [idx[(0, m)], idx[(n - 1, m)], idx[(m, 0)], idx[(m, n - 1)]]
    hh = []
    for nd in nodes:
        for _ in range(hh_per_node):
            hh.append({"id": len(hh), "lon": nd["lon"], "lat": nd["lat"], "building_id": "b", "building": "house",
                       "node": nd["id"], "zone": len(hh) % 4, "size": 2, "vehicles": 1,
                       "flags": {"elderly": len(hh) % 7 == 0, "mobility": False, "medical": False, "no_car": False}})
    venue_id = idx[(m, m)]
    return {
        "meta": {"version": "0.1", "center": list(CENTER), "dist_m": int(half * step_m), "counts": {}},
        "venue": {"name": "test", "lon": CENTER[0], "lat": CENTER[1], "node": venue_id},
        "nodes": nodes, "edges": edges, "paths": [], "households": hh, "assets": [], "exits": exits,
        "zones": [{"id": z, "centroid": list(CENTER), "n_households": 0} for z in range(4)],
    }


@pytest.fixture(scope="module")
def world() -> World:
    return World.from_dict(grid_town())


def test_routing_reaches_exit(world):
    next_edge, dist = world.routing_table()
    assert (next_edge[world.exits] == -2).all()
    assert np.isfinite(dist).all()
    # following next_edge from every node terminates at an exit
    for n in range(world.n_nodes):
        seen = 0
        while next_edge[n] != -2:
            n = int(world.edge_v[next_edge[n]]); seen += 1
            assert seen < world.n_nodes


def test_parallel_edges_take_minimum():
    t = grid_town(n=3)
    slow = dict(t["edges"][0]); slow["id"] = len(t["edges"]); slow["travel_time_s"] = 1000.0
    t["edges"].append(slow)
    w = World.from_dict(t)
    _, d_with = w.routing_table()
    _, d_without = World.from_dict(grid_town(n=3)).routing_table()
    np.testing.assert_allclose(d_with, d_without)


def test_closures_reroute_and_block(world):
    closed = np.zeros(world.n_edges, dtype=bool)
    ins = world.exit_in_edges()[0]
    closed[ins] = True
    next_edge, _ = world.routing_table(closed)
    assert not closed[next_edge[next_edge >= 0]].any()


def test_hazard_grows_and_heading_matters(world):
    east = GrowingEllipseHazard(world, CENTER, speed_mps=1.0, heading_deg=90.0)
    north = GrowingEllipseHazard(world, CENTER, speed_mps=1.0, heading_deg=0.0)
    a0, a1 = east.closed_mask_at(0.0, world).sum(), east.closed_mask_at(300.0, world).sum()
    assert 0 < a0 < a1
    assert (east.closed_mask_at(300.0, world) != north.closed_mask_at(300.0, world)).any()


def test_no_hazard_everyone_exits(world):
    job = default_job(world, T_s=7200.0)
    job["scenario"]["hazard"] = {"type": "none"}
    m = run_job(world, job)
    assert m["exited"] == m["vehicles"] and m["exposed_vehicles"] == 0
    assert m["clearance_s_95"] is not None


def test_rotating_heading_changes_first_exit(world):
    firsts = []
    for h in (90.0, 180.0):
        m = run_job(world, default_job(world, heading_deg=h, speed_mps=0.6, T_s=3600.0))
        assert m["exposed_vehicles"] > 0
        firsts.append(m["exit_closure_order"][0][0])
    assert firsts[0] != firsts[1]


def test_trajectories_are_monotonic(world):
    m = run_job(world, default_job(world, T_s=1800.0), with_trajectories=True)
    trips = m["_trajectories"]
    assert trips
    for tr in trips:
        assert len(tr["path"]) == len(tr["t"])
        assert all(b > a for a, b in zip(tr["t"], tr["t"][1:]))
