"""EngineSession: the backend's calls (start, report → replan, road closure, state, compare, optimize, resume)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ember_engine.api import EngineSession, assignment_events
from ember_engine.daytona.pool import LocalPool
from ember_engine.state import validate_state
from ember_engine.world import World

FX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


@pytest.fixture(scope="module")
def town() -> dict:
    return json.loads((FX / "town.fixture.json").read_text())


@pytest.fixture(scope="module")
def session(town):
    s = EngineSession(FX / "scenario.fixture.json", world=World.from_dict(town))
    s.start()
    return s


def test_start_gives_a_valid_seed(session, town):
    st = session.state_at(0.0)
    assert st["plan_version"] == 1 and st["t_s"] == 0.0
    assert validate_state(st, session.scn, town) == []


def test_report_replans_and_events_match_changes(town):
    s = EngineSession(FX / "scenario.fixture.json", world=World.from_dict(town))
    s.start()
    rep = s.make_report("facility_status", 3000, source="operator", facility_id="mt_auburn", payload={"set": {"backup_endurance_s": 600}})
    out = s.add_report(rep)
    plan = out["plan"]
    assert plan["version"] == 2 and plan["parent_version"] == 1
    ev = out["assignment_events"]
    assert [e["assignment_id"] for e in ev] == [c["assignment_id"] for c in plan["changes"]]
    assert all((e["assignment"] is None) == (e["change"] == "removed") for e in ev)
    assert any(e["assignment"] and e["assignment"]["target"].get("facility_id") == "mt_auburn" for e in ev)
    assert validate_state(out["state"], s.scn, town) == []
    assert out["state"]["t_s"] == 3000


def test_close_road_and_edge_helpers(town):
    s = EngineSession(FX / "scenario.fixture.json", world=World.from_dict(town))
    s.start()
    judge = next(h for h in s.scn["households"] if h.get("judge"))["household_id"]
    edges = s.edges_by_name("Riverside Place", near_household=judge, radius_m=150)
    assert edges
    out = s.close_road(edges, t_now=1800, household_id=judge)
    assert out["plan"]["version"] == 2
    assert {c["edge_id"] for c in out["state"]["closures"] if c["source"] == "report"} >= set(edges)
    assert s.edges_by_name("Western Avenue")


def test_compare_and_optimize(session):
    c = session.compare(seeds=2)
    assert c["scenario_id"] == session.scn["scenario_id"] and len(c["per_seed"]) == 2
    pts = []
    out = session.optimize(on_point=pts.append, seeds=3, k=2, pool=LocalPool(1, world=session.world))
    robust = out["plan"]["search"]["robust"]
    assert "c00-trip" in robust["candidates"]  # published version preserves the new generator's timing comparison
    assert len(pts) == robust["jobs"] == 12  # two candidates + delayed staging + baseline, three paired worlds each
    assert all(p["n_total"] == 12 for p in pts)
    v = out["plan"]["version"]   # optimize at t=0 replaces the current version: points carry the new one
    assert all(p["plan_version"] == v and p["batch_id"] == f"v{v}" for p in pts)
    assert out["plan"]["search"]["robust"]["batch_id"] == f"v{v}"


def test_resume_after_restart(session, town):
    plan, reports = session.plan, session.reports
    s2 = EngineSession(FX / "scenario.fixture.json", world=World.from_dict(town))
    s2.resume(plan, reports)
    assert validate_state(s2.state_at(600), s2.scn, town) == []


def test_assignment_events_shape():
    plan = {"version": 3, "assignments": [{"id": "a1"}], "changes": [{"assignment_id": "a1", "change": "added"},
                                                                    {"assignment_id": "a0", "change": "removed", "note": "x"}]}
    ev = assignment_events(plan)
    assert ev[0]["assignment"] == {"id": "a1"} and ev[1]["assignment"] is None and ev[1]["note"] == "x"


def test_moves_budget_reaches_the_allocator(town):
    s = EngineSession(FX / "scenario.fixture.json", world=World.from_dict(town), moves=5)
    s.start()
    assert s.plan["search"]["moves_scored"] <= 5
    out = s.add_report(s.make_report("facility_status", 3000, source="operator", facility_id="mt_auburn",
                                     payload={"set": {"backup_endurance_s": 600}}))
    assert out["plan"]["search"]["moves_scored"] <= 5
    assert validate_state(out["state"], s.scn, town) == []
