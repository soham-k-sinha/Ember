"""Models (facilities, wastewater, movement) and the plan simulator, on the example scenario."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import numpy as np
import pytest

from ember_engine.models import FacilityModel, Mover, Wastewater, compatible
from ember_engine.sim import example_plan, simulate
from ember_engine.state import validate_state
from ember_engine.world import World

FX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


@pytest.fixture(scope="module")
def town() -> dict:
    return json.loads((FX / "town.fixture.json").read_text())


@pytest.fixture(scope="module")
def world(town) -> World:
    return World.from_dict(town)


@pytest.fixture(scope="module")
def scn() -> dict:
    return json.loads((FX / "scenario.fixture.json").read_text())


def plan_of(*assignments) -> dict:
    return {"version": 1, "assignments": [dict(a, id=a.get("id", f"a{i}")) for i, a in enumerate(assignments)]}


def protect(gen: str, fac: str = "cottage_farm") -> dict:
    return {"id": f"p-{gen}", "resource_id": gen, "task": "protect", "target": {"facility_id": fac}}


def rescue(res: str, hid: int) -> dict:
    return {"id": f"r-{res}-{hid}", "resource_id": res, "task": "rescue", "target": {"household_id": hid}, "dropoff_facility_id": "ems14"}


def ev(r, kind):
    return [e for e in r.events if e["kind"] == kind]


# ---------- facilities ----------
def test_substation_failure_puts_hospital_on_backup_and_endurance_counts_down(scn):
    fm = FacilityModel(scn["facilities"])
    t = 0.0
    while t < 4800:
        fm.step(t, 60.0); t += 60.0
    assert fm.state["sub_putnam_ave"] == "down" and fm.state["mt_auburn"] == "backup"
    assert fm.endurance_left("mt_auburn") == pytest.approx(32400 - 300)
    fm.apply_status("mt_auburn", {"backup_endurance_s": 120})     # operator: "2 minutes left"
    fm.step(t, 60.0); fm.step(t + 60, 60.0); fm.step(t + 120, 60.0)
    assert fm.state["mt_auburn"] == "down"
    fm.connect_generator("mt_auburn", "gen-1"); fm.step(t + 180, 60.0)
    assert fm.state["mt_auburn"] == "ok"


def test_reported_backup_counts_down_while_the_grid_is_up(scn):
    """Operator: 'we're on backup, 10 minutes left' before the substation fails → down 10 min later, not at
    the substation failure."""
    fm = FacilityModel(scn["facilities"])
    fm.step(0.0, 60.0)
    assert fm.state["sub_putnam_ave"] == "ok"
    fm.apply_status("mt_auburn", {"state": "backup", "backup_endurance_s": 600})
    t = 60.0
    while t < 600:
        fm.step(t, 60.0); t += 60.0
    assert fm.state["mt_auburn"] == "backup"
    fm.step(t, 60.0); fm.step(t + 60, 60.0)
    assert fm.state["mt_auburn"] == "down" and fm.state["sub_putnam_ave"] == "ok"
    fm.apply_status("mt_auburn", {"state": "ok"})                 # grid restored
    fm.step(t + 120, 60.0)
    assert fm.state["mt_auburn"] == "ok"


def test_compatibility_rules(scn):
    gens = {r["id"]: r for r in scn["resources"] if r["kind"] == "generator"}
    cf = next(f for f in scn["facilities"] if f["id"] == "cottage_farm")
    assert compatible(gens["gen-1"], cf)[0]
    ok, why = compatible(gens["gen-2"], cf)
    assert not ok and "connector" in why


# ---------- wastewater ----------
def test_wastewater_math():
    w = Wastewater({"storage_m3": 0, "storage_max_m3": 100, "inflow_m3ph": 600, "pump_m3ph": 300})
    for k in range(20):                          # unpowered: +10 m³/min → full at 10 min, then spills 10/min
        w.step(k * 60.0, 60.0, powered=False)
    assert w.storage == pytest.approx(100) and w.overflow == pytest.approx(100) and w.overflow_started_t == pytest.approx(600)
    w.step(1200.0, 60.0, powered=True)          # powered: net +5 m³/min, still full → spills 5
    assert w.overflow == pytest.approx(105)


def test_unpowered_station_overflows_at_the_predicted_minute(world, scn):
    # Putnam Substation fails at 5400 (no backup): storage from ~0 at 3000 m³/h until 7200 (1500 m³),
    # then 4500 m³/h: the remaining 2500 m³ take 2000 s → first spill in the tick starting at 9180 s.
    r = simulate(world, scn, plan_of())
    start = ev(r, "overflow_started")[0]["t_s"]
    assert start == pytest.approx(9180, abs=60) and r.metrics["overflow_m3"] > 0


def test_compatible_generator_prevents_overflow(world, scn):
    r = simulate(world, scn, plan_of(protect("gen-1")))
    assert r.metrics["overflow_m3"] == 0
    con = ev(r, "generator_connected")[0]
    arrive = next(o for o in r.outcomes if o["assignment_id"] == "p-gen-1")["arrive_t"]
    assert con["t_s"] == pytest.approx(arrive + 900, abs=60)          # travel + connect_s


def test_late_generator_stops_overflow_after_travel_plus_connect(world, scn):
    dry = copy.deepcopy(scn)
    dry["hazard"]["keyframes"] = []              # keep the route open; only the power failure matters here
    base = simulate(world, dry, plan_of())
    on_time = next(o for o in simulate(world, dry, plan_of(protect("gen-1"))).outcomes)["arrive_t"]
    mult = 9000.0 / on_time                      # arrive ≈ 150 min, connected ≈ 165 min: mid-overflow
    late = simulate(world, dry, plan_of(protect("gen-1")), perturbation={"travel_time_mult": mult})
    con = ev(late, "generator_connected")
    assert con, "generator never connected"
    assert 0 < late.metrics["overflow_m3"] < base.metrics["overflow_m3"]
    ser = np.array(late.timeline["ww"]["cottage_farm"]["overflow_m3"])
    after = ser[late.tick_index(con[0]["t_s"]) + 1:]
    assert np.all(after == after[0])                                   # no more spill once powered


def test_incompatible_generator_changes_nothing(world, scn):
    base = simulate(world, scn, plan_of())
    r = simulate(world, scn, plan_of(protect("gen-2")))
    o = r.outcomes[0]
    assert o["status"] == "infeasible" and "connector" in o["reason"]
    assert r.metrics["overflow_m3"] == base.metrics["overflow_m3"] and r.metrics["infeasible_assignments"] == 1


# ---------- movement ----------
def test_mover_reroutes_turns_back_and_stalls(world):
    closed = np.zeros(world.n_edges, dtype=bool)
    a, b = 0, world.n_nodes - 1
    path, tt = world.route(a, b)
    assert path
    m = Mover(world, "x", a)
    m.go(b, closed)
    first = m.route[0]
    m.advance(1.0, closed)                         # now on the first edge
    closed2 = closed.copy(); closed2[first] = True
    m.advance(1.0, closed2)                        # water on our edge → turn back toward the start
    assert m.toward == a
    for _ in range(100):
        if m.edge < 0:
            break
        m.advance(10.0, closed2)
    assert m.node == a
    cut = np.ones(world.n_edges, dtype=bool)
    assert m.advance(10.0, cut) == "stalled" and m.stall_s > 0


# ---------- rescues ----------
def _known(scn, mobility: bool):
    return next(h for h in scn["households"] if h["needs"] != "unknown" and bool(h["needs"].get("mobility")) == mobility)


def test_pickup_rules(world, scn):
    mob = _known(scn, True)["household_id"]
    r = simulate(world, scn, plan_of(rescue("van-1", mob)))
    assert r.outcomes[0]["status"] == "infeasible" and "accessible" in r.outcomes[0]["reason"]
    r = simulate(world, scn, plan_of(rescue("avan-1", mob)))
    o = r.outcomes[0]
    assert o["status"] == "done" and o["pickup_t"] is not None and o["complete_t"] > o["pickup_t"]
    judge = next(h for h in scn["households"] if h.get("judge"))["household_id"]
    r = simulate(world, scn, plan_of(rescue("van-1", judge)))
    assert r.outcomes[0]["status"] == "incomplete" and "unknown" in r.outcomes[0]["reason"]


def test_need_report_reveals_needs(world, scn):
    judge = next(h for h in scn["households"] if h.get("judge"))["household_id"]
    rep = {"id": "r-judge", "source": "judge", "kind": "need", "household_id": judge, "observed_at_t_s": 0,
           "payload": {"people": 2, "mobility": True, "accessible_vehicle": True}}
    r = simulate(world, scn, plan_of(rescue("avan-1", judge)), reports=[rep])
    assert r.outcomes[0]["status"] == "done" and r.outcomes[0]["people"] == 2


def test_closure_report_blocks_and_crew_clears(world, scn):
    hid = _known(scn, False)["household_id"]
    first = simulate(world, scn, plan_of(rescue("van-1", hid)))
    route = first.outcomes[0]["route_edges"]
    assert route
    block = {"id": "c1", "source": "resident", "kind": "closure_report", "observed_at_t_s": 0, "payload": {"edge_ids": route}}
    blocked = simulate(world, scn, plan_of(rescue("van-1", hid)), reports=[block])
    assert blocked.outcomes[0]["route_edges"] != route
    crew = {"id": "clr", "resource_id": "crew-1", "task": "clear_road", "target": {"edge_ids": route[:1]}}
    cleared = simulate(world, scn, plan_of(crew), reports=[block])
    assert cleared.outcomes[0]["status"] == "done" and ev(cleared, "road_cleared")


def test_resource_failure_perturbation(world, scn):
    hid = _known(scn, False)["household_id"]
    r = simulate(world, scn, plan_of(rescue("van-1", hid)), perturbation={"resource_failure": {"resource_id": "van-1", "t_s": 0}})
    assert r.outcomes[0]["status"] == "incomplete" and ev(r, "resource_failed")


# ---------- whole plan ----------
def test_example_plan_simulates_fast_and_deterministically(world, scn):
    plan = example_plan(world, scn)
    t = time.time()
    a = simulate(world, scn, plan)
    assert time.time() - t < 1.0
    b = simulate(world, scn, copy.deepcopy(plan))
    assert a.metrics == b.metrics and a.outcomes == b.outcomes
    assert a.metrics["people_reached_before_deadline"] > 0 and a.metrics["overflow_m3"] == 0


@pytest.mark.parametrize("t_s", [0.0, 1800.0, 4800.0, 10740.0])
def test_snapshots_validate(world, scn, town, t_s):
    r = simulate(world, scn, example_plan(world, scn))
    assert validate_state(r.state_at(t_s), scn, town) == []
