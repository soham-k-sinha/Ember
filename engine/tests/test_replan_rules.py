"""Replan rules the backend relies on, on the real scenario: declines are constraints, a confirmation keeps its
place in the vehicle's queue, and a decline that is taken back is live again."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from ember_engine.allocator import allocate
from ember_engine.scenario import load_scenario
from ember_engine.sim.plan_sim import cut_at, simulate
from ember_engine.world import World

ROOT = Path(__file__).resolve().parents[2]
SCN = ROOT / "scenarios" / "allston_flood_v1" / "scenario.json"
pytestmark = pytest.mark.skipif(not SCN.exists(), reason="allston_flood_v1 not present")


@pytest.fixture(scope="module")
def world() -> World:
    return World.from_dict(json.loads(gzip.decompress((ROOT / "engine" / "data" / "town.json.gz").read_bytes())))


@pytest.fixture(scope="module")
def scn() -> dict:
    return load_scenario(SCN)


@pytest.fixture(scope="module")
def v1(world, scn) -> dict:
    return allocate(world, scn, moves=20)


def _queue(plan: dict, rid: str) -> list:
    return [a for a in plan["assignments"] if a["resource_id"] == rid and a["task"] == "rescue" and cut_at(a) is None]


def _busiest(plan: dict) -> str:
    """The standard vehicle with the longest rescue queue (the reserve van may have none)."""
    return max(("van-1", "van-2", "truck-1"), key=lambda rid: len(_queue(plan, rid)))


def _with_status(plan: dict, assignment_id: str, status: str) -> dict:
    p = copy.deepcopy(plan)
    for a in p["assignments"]:
        if a["id"] == assignment_id:
            a["status"] = status
    return p


def test_a_declined_vehicle_is_never_reproposed_and_stops_driving_there(world, scn, v1):
    scn_needs = {h["household_id"]: h["needs"] for h in scn["households"]}
    rid = _busiest(v1)
    a = next(x for x in _queue(v1, rid)[1:] if scn_needs[x["target"]["household_id"]] != "unknown")
    hid = a["target"]["household_id"]
    v2 = allocate(world, scn, t_now=60, prev=_with_status(v1, a["id"], "rejected"), prev_reports=[], moves=20)
    live = [x for x in v2["assignments"] if x["target"].get("household_id") == hid and cut_at(x) is None]
    assert all(x["resource_id"] != rid for x in live)
    declined = next(x for x in v2["assignments"] if x["id"] == a["id"])
    assert declined["status"] == "rejected" and declined["cancelled_at_t_s"] == 60
    assert live or any(u["target"].get("household_id") == hid for u in v2["unresolved"])
    out = {o["assignment_id"]: o for o in simulate(world, scn, v2, record=False).outcomes}
    assert out[a["id"]]["pickup_t"] is None   # the vehicle no longer goes there


def test_a_decline_with_no_alternative_says_so(world, scn, v1):
    a = next(x for x in _queue(v1, "van-3")[1:])
    v2 = allocate(world, scn, t_now=60, prev=_with_status(v1, a["id"], "rejected"), prev_reports=[], moves=20)
    u = next((u for u in v2["unresolved"] if u["target"].get("household_id") == a["target"]["household_id"]), None)
    if u is not None:
        assert u["blocked_by"].startswith("declined Accessible Van 3")


def test_taking_a_decline_back_makes_the_assignment_live_again(world, scn, v1):
    a = _queue(v1, _busiest(v1))[1]
    v2 = allocate(world, scn, t_now=60, prev=_with_status(v1, a["id"], "rejected"), prev_reports=[], moves=20)
    undone = _with_status(v2, a["id"], "offered")          # what the backend does on a later YES
    assert cut_at(next(x for x in undone["assignments"] if x["id"] == a["id"])) is None
    v3 = allocate(world, scn, t_now=120, prev=undone, prev_reports=[], moves=20)
    hid = a["target"]["household_id"]
    assert any(x["target"].get("household_id") == hid and cut_at(x) is None for x in v3["assignments"])


def test_confirming_keeps_the_assignment_in_its_place_in_the_queue(world, scn, v1):
    rid = _busiest(v1)
    last = _queue(v1, rid)[-1]
    v2 = allocate(world, scn, t_now=60, prev=_with_status(v1, last["id"], "confirmed"), prev_reports=[], moves=20)
    q2 = _queue(v2, rid)
    mine = next(x for x in q2 if x["id"] == last["id"])
    assert mine["status"] == "confirmed"
    # did not jump the queue: still behind the earlier deadlines, ETA about where it was
    assert q2.index(mine) >= len(q2) - 2
    assert abs(mine["eta_s"] - last["eta_s"]) < 900


def test_rescues_drop_off_at_the_nearest_drop_off_point(world, scn, v1):
    from ember_engine.allocator.context import Context
    ctx = Context(world, scn, [], 0.0)
    rescues = [a for a in v1["assignments"] if a["task"] == "rescue"]
    assert rescues and all(a["dropoff_facility_id"] == ctx.dropoff_for(a["target"]["household_id"]) for a in rescues)
    assert {a["dropoff_facility_id"] for a in rescues} == {"treehouse-shelter"}   # every household is nearer the shelter


def test_a_full_shelter_spills_over_to_the_next_drop_off(world, scn):
    small = copy.deepcopy(scn)
    for f in small["facilities"]:
        if f["id"] == "treehouse-shelter":
            f["capacity_people"] = 10
    plan = allocate(world, small, moves=0)
    to = [a["dropoff_facility_id"] for a in plan["assignments"] if a["task"] == "rescue"]
    assert "ems14" in to and "treehouse-shelter" in to
    out = {o["assignment_id"]: o for o in simulate(world, small, plan, record=False).outcomes}
    assert any(o["status"] == "done" for o in out.values())


def _two_neighbours(world, scn):
    """Two households of the scenario that are close by road (the simulator pools those)."""
    from ember_engine.allocator.context import Context
    ctx = Context(world, scn, [], 0.0)
    ids = [h for h in ctx.hh if ctx.needs[h] != "unknown" and not ctx.needs[h].get("mobility")
           and not ctx.needs[h].get("accessible_vehicle")]
    for a in ids:
        for b in ids:
            if a != b and ctx.needs[a]["people"] + ctx.needs[b]["people"] <= 6 and float(ctx.tf(ctx.hh_node[a])[ctx.hh_node[b]]) < 120:
                return a, b
    pytest.skip("no close pair")


def _trip(rid, *hids):
    return {"assignments": [{"id": f"a-{rid}-{h}", "resource_id": rid, "task": "rescue", "target": {"household_id": h},
                             "dropoff_facility_id": "treehouse-shelter", "status": "proposed"} for h in hids]}


def test_neighbours_share_a_trip_when_seats_allow(world, scn):
    a, b = _two_neighbours(world, scn)
    r = simulate(world, scn, _trip("van-2", a, b), record=False)
    out = {o["assignment_id"]: o for o in r.outcomes}
    first, second = out[f"a-van-2-{a}"], out[f"a-van-2-{b}"]
    assert second["shared_after"] == f"a-van-2-{a}"
    assert first["status"] == second["status"] == "done" and first["complete_t"] == second["complete_t"]   # one drop-off


def test_no_shared_trip_without_seats(world, scn):
    a, b = _two_neighbours(world, scn)
    small = copy.deepcopy(scn)
    for x in small["resources"]:
        if x["id"] == "van-2":
            x["capacity_people"] = max(small_need for small_need in (
                next(h["needs"]["people"] for h in small["households"] if h["household_id"] == a),
                next(h["needs"]["people"] for h in small["households"] if h["household_id"] == b)))
    r = simulate(world, small, _trip("van-2", a, b), record=False)
    out = {o["assignment_id"]: o for o in r.outcomes}
    assert out[f"a-van-2-{b}"]["shared_after"] is None
    assert out[f"a-van-2-{a}"]["complete_t"] < out[f"a-van-2-{b}"]["complete_t"]
