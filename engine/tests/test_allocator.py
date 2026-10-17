"""Baseline, allocator (initial + replan), compare — on the example scenario and the town fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ember_engine.allocator import allocate
from ember_engine.allocator.rolling import run_ember
from ember_engine.baseline import baseline_plan
from ember_engine.compare import compare
from ember_engine.sim import simulate
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


@pytest.fixture(scope="module")
def v1(world, scn) -> dict:
    return allocate(world, scn)


def _spec(scn, rid):
    return next(r for r in scn["resources"] if r["id"] == rid)


def _need(scn, hid):
    return next(h for h in scn["households"] if h["household_id"] == hid)["needs"]


def test_baseline_is_reactive(world, scn):
    p = baseline_plan(world, scn)
    gens = [a for a in p["assignments"] if a["task"] == "protect"]
    assert gens and all(a["not_before_t_s"] == 5400 for a in gens)          # dispatched when the station goes down
    revealed = {r["household_id"]: r["t_s"] for r in scn["scripted_reports"] if r["kind"] == "need"}
    for a in p["assignments"]:
        hid = a["target"].get("household_id")
        if hid in revealed:
            assert a["not_before_t_s"] == revealed[hid]                       # dispatched when the report arrives


def test_plan_respects_hard_constraints(scn, v1):
    for a in v1["assignments"]:
        if a["task"] != "rescue":
            continue
        need, spec = _need(scn, a["target"]["household_id"]), _spec(scn, a["resource_id"])
        assert need != "unknown"
        assert spec["capacity_people"] >= need["people"]
        assert spec.get("accessible") or not (need.get("mobility") or need.get("accessible_vehicle"))
    used = {a["resource_id"] for a in v1["assignments"]}
    assert not set(v1["reserved"]) & used
    assert v1["metrics"]["replan_latency_s"] < 2.0


def test_allocate_is_deterministic(world, scn, v1):
    again = allocate(world, scn)
    assert [a["id"] for a in again["assignments"]] == [a["id"] for a in v1["assignments"]]
    assert again["metrics"] == {**v1["metrics"], "replan_latency_s": again["metrics"]["replan_latency_s"]}


def test_ember_beats_baseline(world, scn):
    ember, _ = run_ember(world, scn)
    e = simulate(world, scn, ember, record=False).metrics
    b = simulate(world, scn, baseline_plan(world, scn), record=False).metrics
    assert e["people_unreached"] < b["people_unreached"]
    assert e["people_reached_before_deadline"] > b["people_reached_before_deadline"]
    assert e["overflow_m3"] <= b["overflow_m3"]


def test_replan_never_does_worse_than_keeping_the_plan(world, scn, v1):
    """No new facts (before the first scripted report): the previous plan is always a candidate, so the
    replan's objective is never worse than keeping it; the version chain is linked."""
    from ember_engine.allocator.search import objective
    v2 = allocate(world, scn, t_now=1200, prev=v1, prev_reports=[])
    assert v2["version"] == 2 and v2["parent_version"] == 1
    keep = simulate(world, scn, v1, record=False).metrics
    assert tuple(v2["search"]["objective"]) <= objective(keep, 0)


def test_operator_report_moves_the_generator_to_the_hospital(world, scn, v1):
    rep = {"id": "op-1", "source": "operator", "kind": "facility_status", "facility_id": "mt_auburn", "observed_at_t_s": 3000,
           "payload": {"set": {"backup_endurance_s": 600}}}
    v2 = allocate(world, scn, reports=[rep], t_now=3000, prev=v1, prev_reports=[])
    gens = {a["target"]["facility_id"]: a for a in v2["assignments"] if a["task"] == "protect"}
    assert gens["cottage_farm"]["status"] == "cancelled" and gens["cottage_farm"]["cancelled_at_t_s"] == 3000
    assert "mt_auburn" in gens and gens["mt_auburn"]["resource_id"] == "gen-1"
    assert "re-targeted to mt_auburn" in gens["cottage_farm"]["rationale"]
    before = simulate(world, scn, v1, reports=[rep], record=False).metrics
    after = simulate(world, scn, v2, reports=[rep], record=False).metrics
    assert before["hospital_outage_s"] > 0 and after["hospital_outage_s"] == 0
    assert v2["search"]["wall_s"] < 2.0
    assert {c["change"] for c in v2["changes"]} >= {"added", "removed"}


def test_judge_answer_turns_unknown_into_a_decision(world, scn, v1, town):
    judge = next(h for h in scn["households"] if h.get("judge"))["household_id"]
    assert any(u["target"].get("household_id") == judge and u["blocked_by"] == "needs unknown" for u in v1["unresolved"])
    rep = {"id": "j-1", "source": "judge", "kind": "need", "household_id": judge, "observed_at_t_s": 2400,
           "payload": {"people": 2, "mobility": True, "accessible_vehicle": True}}
    v2 = allocate(world, scn, reports=[rep], t_now=2400, prev=v1, prev_reports=[])
    mine = [a for a in v2["assignments"] if a["target"].get("household_id") == judge and a.get("status") != "cancelled"]
    blocked = [u for u in v2["unresolved"] if u["target"].get("household_id") == judge]
    assert mine or (blocked and blocked[0]["blocked_by"] != "needs unknown")
    if mine:
        assert _spec(scn, mine[0]["resource_id"]).get("accessible")
    st = simulate(world, scn, v2, reports=[rep]).state_at(3600)
    assert validate_state(st, scn, town) == []


def test_compare_is_paired_and_honest(world, scn):
    c = compare(world, scn, seeds=2)
    assert [r["seed"] for r in c["per_seed"]] == [1, 2]
    assert c["per_seed"][0]["perturbation"] != c["per_seed"][1]["perturbation"]
    row = {r["metric"]: r for r in c["metrics"]}
    assert row["people_unreached"]["ember_better_seeds"] == 2
    for r in c["metrics"]:
        if r["ember_worse_seeds"]:
            assert "worse" in r["sentence"]
