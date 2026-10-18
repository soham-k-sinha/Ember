"""The two demo beats on the real scenario (scenarios/allston_flood_v1 + the shared town). If one of these
fails, the demo story broke: fix the engine or re-tune the scenario before the run-through."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from ember_engine.allocator import allocate
from ember_engine.baseline import baseline_plan
from ember_engine.scenario import load_scenario
from ember_engine.sim import simulate
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


def test_sustainability_beat_reactive_generator_overflows_ember_does_not(world, scn):
    """Baseline sends the generator when the station fails → overflow; EMBER pre-positions it → none."""
    b = simulate(world, scn, baseline_plan(world, scn), record=False).metrics
    e = simulate(world, scn, allocate(world, scn), record=False).metrics
    assert b["overflow_m3"] > 1000 and e["overflow_m3"] == 0


def test_medical_needs_ride_the_ambulance_when_it_is_on_time(world, scn):
    """D114: every medical household Ambulance 1 can carry rides it before its deadline, and the rationale says why;
    a medical household larger than the ambulance, and every non-medical one, rides something else."""
    plan = allocate(world, scn)
    res = {r["id"]: r for r in scn["resources"]}
    amb = next(r for r in scn["resources"] if r["kind"] == "ambulance")
    needs = {h["household_id"]: h["needs"] for h in scn["households"] if h["needs"] != "unknown"}
    rescues = {a["target"]["household_id"]: a for a in plan["assignments"] if a["task"] == "rescue"}
    for hid, n in needs.items():
        a = rescues.get(hid)
        if n.get("medical") and n["people"] <= amb["capacity_people"]:
            assert a and a["resource_id"] == amb["id"] and a["eta_s"] <= a["deadline_s"], (hid, a)
            assert f"medical need → {amb['name']}" in a["rationale"]
        elif a:
            assert res[a["resource_id"]]["kind"] != "ambulance", (hid, a)


def test_judge_beat_one_reply_changes_a_rescue_and_the_generator(world, scn):
    """At minute 5 the judge texts '2 people, wheelchair, River St blocked': the judge gets the accessible van
    before the deadline AND the generator's route/ETA changes (it was going through the judge's corner)."""
    from ember_engine.api import EngineSession
    judge = next(h for h in scn["households"] if h.get("judge"))["household_id"]
    s = EngineSession(SCN, world=world)
    s.start()
    v1 = s.plan
    river_st = s.edges_by_name("River Street", near_household=judge, radius_m=150)
    need = s.make_report("need", 300, source="judge", household_id=judge,
                         payload={"people": 2, "mobility": True, "accessible_vehicle": True})
    road = s.make_report("closure_report", 300, source="judge", household_id=judge, payload={"edge_ids": river_st})
    out = s.add_reports([need, road], t_now=300)
    v2 = out["plan"]
    mine = [a for a in v2["assignments"] if a["target"].get("household_id") == judge and a.get("status") != "cancelled"]
    assert mine, [u for u in v2["unresolved"] if u["target"].get("household_id") == judge]
    spec = next(r for r in scn["resources"] if r["id"] == mine[0]["resource_id"])
    assert spec["kind"] == "accessible_van" and mine[0]["eta_s"] <= mine[0]["deadline_s"]   # no medical need: not the ambulance
    gen_before = {a["id"]: a for a in v1["assignments"] if a["task"] == "protect"}
    gen_after = {a["id"]: a for a in v2["assignments"] if a["task"] == "protect"}
    changed = any(i not in gen_after or abs(gen_after[i]["eta_s"] - a["eta_s"]) > 120 for i, a in gen_before.items()) \
        or set(gen_after) != set(gen_before)
    assert changed, "the judge's report no longer affects the generator"
    assert any(e["assignment_id"].startswith("a-gen-") for e in out["assignment_events"])
    assert v2["search"]["wall_s"] < 2.0


def test_operator_beat_at_minute_15_moves_the_generator_to_the_hospital(world, scn):
    """After the judge beat, at minute 15 Mount Auburn reports 'on backup, 10 minutes left': Generator 1 is
    re-targeted to the hospital (outage ≈ 16 min instead of hours) and the overflow cost shows in the metrics."""
    from ember_engine.api import EngineSession
    judge = next(h for h in scn["households"] if h.get("judge"))["household_id"]
    s = EngineSession(SCN, world=world)
    s.start()
    river_st = s.edges_by_name("River Street", near_household=judge, radius_m=150)
    s.add_reports([s.make_report("need", 300, source="judge", household_id=judge,
                                 payload={"people": 2, "mobility": True, "accessible_vehicle": True}),
                   s.make_report("closure_report", 300, source="judge", household_id=judge,
                                 payload={"edge_ids": river_st})], t_now=300)
    out = s.add_report(s.make_report("facility_status", 900, source="operator", facility_id="mt-auburn",
                                     payload={"set": {"state": "backup", "backup_endurance_s": 600}}), 900)
    plan = out["plan"]
    gen = [a for a in plan["assignments"] if a["task"] == "protect" and a.get("status") != "cancelled"]
    assert [a["target"].get("facility_id") for a in gen] == ["mt-auburn"]
    assert "down at 25 min" in gen[0]["rationale"]
    m = plan["metrics"]
    assert m["hospital_outage_s"] < 1200 and m["overflow_m3"] > 1000
    assert any(u["target"].get("facility_id") == "cottage-farm" for u in plan["unresolved"])


def test_late_operator_report_still_moves_the_generator_when_no_people_are_at_stake(world, scn):
    """At minute 40 Generator 1 is already committed to Cottage Farm. Moving it to the hospital changes no rescue,
    so the lexicographic objective (people, hospital outage, overflow) must pick the move, and the plan must say
    what it costs."""
    from ember_engine.api import EngineSession
    s = EngineSession(SCN, world=world)
    s.start()
    out = s.add_report(s.make_report("facility_status", 2400, source="operator", facility_id="mt-auburn",
                                     payload={"set": {"state": "backup", "backup_endurance_s": 600}}), 2400)
    plan = out["plan"]
    gen = [a for a in plan["assignments"] if a["task"] == "protect" and a.get("status") != "cancelled"]
    assert [a["target"].get("facility_id") for a in gen] == ["mt-auburn"]
    assert plan["metrics"]["hospital_outage_s"] < 1800
    cf = next(u for u in plan["unresolved"] if u["target"].get("facility_id") == "cottage-farm")
    assert "instead" in cf["blocked_by"] and "overflow" in cf["blocked_by"]
    assert "chosen over" in gen[0]["rationale"]
    assert plan["search"]["wall_s"] < 2.0
