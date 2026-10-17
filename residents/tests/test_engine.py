"""Engine mode on the real demo scenario (allston_flood_v1): bootstrap, reports → replan → WS events,
disruptions, clock, comparison. The allocator runs for real (local search shortened for speed)."""
import asyncio
import json
from dataclasses import replace

import jsonschema
import pytest
from fastapi.testclient import TestClient
from referencing import Registry, Resource

from ember_engine.state import validate_state
from residents.app import create_app
from residents.config import CONTRACTS, REPO_ROOT
from residents.contracts import errors
from residents.engine_bridge import EngineBridge

SCENARIO = REPO_ROOT / "scenarios" / "allston_flood_v1" / "scenario.json"
JUDGE = 10296


@pytest.fixture(scope="session")
def bridge():
    """Small search budget for speed. Demo-beat tests use `full_bridge` (the engine's default search)."""
    return EngineBridge(SCENARIO, moves=10)


@pytest.fixture(scope="session")
def full_bridge():
    return EngineBridge(SCENARIO)


@pytest.fixture
def esettings(settings):
    return replace(settings, scenario=SCENARIO)


@pytest.fixture
def ec(esettings, bridge):
    with TestClient(create_app(esettings, bridge=bridge)) as c:
        yield c


@pytest.fixture(scope="session")
def ws_validator():
    path = CONTRACTS / "ws-events.schema.json"
    reg = Registry()
    for p in CONTRACTS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        reg = reg.with_resource(s["$id"], Resource.from_contents(s))
    return jsonschema.Draft202012Validator(json.loads(path.read_text()), registry=reg)


def judge_need(**payload):
    return {"source": "judge", "kind": "need", "household_id": JUDGE, "text": "we are 2, one wheelchair",
            "payload": {"people": 2, "mobility": True, "accessible_vehicle": True, **payload}}


def drain(ws, n):
    return [ws.receive_json() for _ in range(n)]


def test_bootstrap_on_allston(ec, bridge, town):
    h = ec.get("/health").json()
    assert (h["mode"], h["scenario_id"], h["plan_version"], h["t_s"]) == ("engine", "allston_flood_v1", 1, 0.0)
    st = ec.get("/state").json()
    assert validate_state(st, bridge.scenario, town) == []
    assert len(st["households"]) == 40 and st["plan"]["version"] == 1 and st["plan"]["assignments"]
    assert all(a["route"] for a in st["plan"]["assignments"] if a["route_edges"])  # the map needs coordinates
    judge = next(x for x in st["households"] if x["household_id"] == JUDGE)
    assert judge["needs"] == "unknown" and judge["judge"]
    assert ec.get("/plan/current").json() == st["plan"]
    assert ec.get("/plan/1").json()["version"] == 1  # raw allocator plan


def test_judge_report_replans_and_broadcasts_in_order(ec, bridge, town, ws_validator):
    with ec.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        r = ec.post("/reports", json=judge_need())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["replanned"] and body["plan_version"] == 2
        changes = body["changes"]
        events = drain(ws, 3 + len(changes))  # report, plan, one assignment per change, metrics
    types = [e["type"] for e in events]
    assert types == ["report", "plan"] + ["assignment"] * len(changes) + ["metrics"]
    assert [e["seq"] for e in events] == list(range(first["seq"] + 1, first["seq"] + 1 + len(events)))
    for e in events:
        assert not list(ws_validator.iter_errors(e)), (e["type"], [x.message[:120] for x in ws_validator.iter_errors(e)])
    assert events[1]["data"]["version"] == 2 and events[1]["data"]["parent_version"] == 1
    lat = events[1]["data"]["metrics"]["replan_latency_s"]
    assert isinstance(lat, float) and 0 < lat < 5 and events[-1]["data"]["replan_latency_s"] == lat
    assert [e["data"]["assignment_id"] for e in events[2:-1]] == [c["assignment_id"] for c in changes]

    st = ec.get("/state").json()
    assert validate_state(st, bridge.scenario, town) == []
    judge = next(x for x in st["households"] if x["household_id"] == JUDGE)
    assert judge["needs"]["accessible_vehicle"] is True and judge["needs_source"] == "report"
    live = [x for x in st["reports"] if x["id"] == body["report"]["id"]]
    assert live and live[0]["resolved"] and live[0]["text"] == "we are 2, one wheelchair"  # backend copy keeps the text


@pytest.mark.parametrize("bad, why", [
    ({"source": "judge", "kind": "need", "household_id": JUDGE}, "payload"),
    ({"source": "judge", "kind": "need", "household_id": 1, "payload": {"people": 1}}, "not an assisted household"),
    ({"source": "operator", "kind": "facility_status", "facility_id": "nope", "payload": {"set": {"x": 1}}}, "not in allston"),
    ({"source": "judge", "kind": "closure_report", "payload": {"road_hint": "Western Ave"}}, "edge_ids"),
    ({"source": "judge", "kind": "closure_report", "payload": {"edge_ids": [999999]}}, "not in town"),
    ({"source": "martian", "kind": "need", "household_id": JUDGE, "payload": {"people": 1}}, "source"),
])
def test_bad_reports_rejected_without_side_effects(ec, bad, why):
    r = ec.post("/reports", json=bad)
    assert r.status_code == 422 and why in r.text, r.text
    assert ec.get("/health").json()["plan_version"] == 1 and ec.get("/state").json()["reports"] == []


def test_duplicate_report_id_rejected(ec):
    assert ec.post("/reports", json=judge_need() | {"id": "r-same"}).status_code == 200
    r = ec.post("/reports", json=judge_need() | {"id": "r-same"})
    assert r.status_code == 422 and "already exists" in r.text
    assert ec.get("/health").json()["plan_version"] == 2


def test_non_fact_report_is_stored_without_replan(ec):
    r = ec.post("/reports", json={"source": "resident", "kind": "question", "household_id": JUDGE, "text": "is the bridge open?"}).json()
    assert not r["replanned"] and r["plan_version"] == 1
    assert ec.get("/state").json()["reports"][-1]["kind"] == "question"


def test_close_road_closes_both_directions_and_replans(ec, bridge):
    e = next(x for x in bridge.town["edges"] if any(y["u"] == x["v"] and y["v"] == x["u"] for y in bridge.town["edges"]))
    twin = next(y["id"] for y in bridge.town["edges"] if y["u"] == e["v"] and y["v"] == e["u"])
    r = ec.post("/disruption", json={"close_edges": [e["id"]]}).json()
    assert sorted(r["report"]["payload"]["edge_ids"]) == sorted([e["id"], twin])
    assert r["report"]["source"] == "judge" and r["report"]["kind"] == "closure_report" and r["plan_version"] == 2
    closed = {c["edge_id"]: c for c in ec.get("/state").json()["closures"]}
    assert e["id"] in closed and twin in closed and closed[e["id"]]["source"] == "report"


def test_disruption_facility_and_bad_bodies(ec):
    r = ec.post("/disruption", json={"facility_id": "mt-auburn", "set": {"backup_endurance_s": 600}, "note": "fuel leak"})
    assert r.status_code == 200 and r.json()["report"]["kind"] == "facility_status" and r.json()["plan_version"] == 2
    assert ec.post("/disruption", json={}).status_code == 422
    assert ec.post("/disruption", json={"close_edges": [1], "facility_id": "mt-auburn", "set": {"a": 1}}).status_code == 422
    assert ec.post("/disruption", json={"facility_id": "mt-auburn", "set": {}}).status_code == 422
    assert ec.post("/disruption", json={"close_edges": [10**6]}).status_code == 422


def test_clock_moves_the_flood(ec, bridge):
    with ec.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert ec.get("/state").json()["closures"] == []  # dry at t=0
        r = ec.post("/clock", json={"t_s": 7200})
        assert r.status_code == 200 and r.json()["t_s"] == 7200
        ev = ws.receive_json()
    assert ev["type"] == "state" and ev["data"]["t_s"] == 7200 and ev["data"]["closures"]
    assert ec.post("/clock", json={"t_s": bridge.t_end_s + 1}).status_code == 422
    assert ec.post("/clock", json={"t_s": -5}).status_code == 422


def test_report_is_observed_at_the_clock(ec):
    ec.post("/clock", json={"t_s": 3000})
    rep = ec.post("/reports", json=judge_need()).json()["report"]
    assert rep["observed_at_t_s"] == 3000


def test_replan_chain_and_history(ec, esettings):
    a = ec.post("/reports", json=judge_need()).json()["report"]["id"]
    b = ec.post("/disruption", json={"facility_id": "mt-auburn", "set": {"backup_endurance_s": 1200}}).json()["report"]["id"]
    assert ec.get("/health").json()["plan_version"] == 3
    v3 = ec.get("/plan/3").json()
    assert v3["parent_version"] == 2 and ec.get("/plan/2").json()["parent_version"] == 1
    assert set(ec.app.state.store.plan_reports_used(3)) == {a, b}
    assert ec.post("/replan").json()["plan_version"] == 4


def test_concurrent_reports_are_serialized(ec):
    planner = ec.app.state.planner

    async def both():
        return await asyncio.gather(planner.submit_report(judge_need()),
                                    planner.submit_report({"source": "operator", "kind": "facility_status", "facility_id": "mt-auburn",
                                                           "payload": {"set": {"backup_endurance_s": 900}}}))
    (_, p1), (_, p2) = ec.portal.call(both)
    assert sorted([p1["version"], p2["version"]]) == [2, 3]
    assert ec.app.state.store.plan_versions() == [1, 2, 3]
    assert ec.get("/plan/3").json()["parent_version"] == 2


def test_comparison_is_valid_and_cached(ec):
    c = ec.get("/comparison?seeds=2")
    assert c.status_code == 200
    assert errors("comparison", c.json()) == []
    planner = ec.app.state.planner
    assert planner._comparison[1] is ec.app.state.planner._comparison[1]
    cached = planner._comparison[1]
    ec.get("/comparison?seeds=2")
    assert planner._comparison[1] is cached           # same plan version → cached
    ec.post("/reports", json=judge_need())
    assert planner._comparison is None                # a new plan invalidates it
    assert ec.get("/comparison?seeds=0").status_code == 422


def test_plan_hooks_get_the_new_version(ec):
    seen = []
    async def hook(view, raw):
        seen.append((view["version"], raw["version"], len(view.get("changes", []))))
    ec.app.state.planner.plan_hooks.append(hook)
    ec.post("/reports", json=judge_need())
    assert seen and seen[0][:2] == (2, 2)


def test_restart_keeps_plans_reset_replans(esettings, bridge):
    with TestClient(create_app(esettings, bridge=bridge)) as c:
        c.post("/reports", json=judge_need())
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
    with TestClient(create_app(esettings, bridge=bridge)) as c:  # restart: same DB, no reseed
        assert c.get("/health").json()["plan_version"] == 2 and len(c.get("/state").json()["reports"]) == 1
        assert c.post("/dev/reset").json()["plan_version"] == 1
        st = c.get("/state").json()
        assert st["reports"] == []
        q = next(q for q in st["plan"]["info_requests"] if q["to"] == {"household_id": JUDGE})
        # the only message after a reset: v1's open question to the (still registered) judge phone (DEMO.md step 6)
        assert [(m["direction"], m["text"]) for m in st["messages"]] == [("out", f"[EMBER drill] {q['question']}")]
        assert c.get("/phones").json()[0]["thread"] == {"household_id": JUDGE}  # phones survive, resolve to the Allston judge


def test_fresh_start_asks_the_judge(esettings, bridge):
    from dataclasses import replace as _r
    with TestClient(create_app(esettings, bridge=bridge)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
    with TestClient(create_app(_r(esettings, reset_on_start=True), bridge=bridge)) as c:  # RESET_ON_START=1 (DEMO.md)
        outs = [m for m in c.get("/state").json()["messages"] if m["direction"] == "out"]
        assert len(outs) == 1 and "wheelchair-accessible vehicle" in outs[0]["text"] and outs[0]["thread"] == {"household_id": JUDGE}


def test_switching_scenario_reseeds(settings, esettings, bridge):
    with TestClient(create_app(settings)) as c:                  # static: example_flood fixture
        assert c.get("/health").json()["scenario_id"] == "example_flood"
    with TestClient(create_app(esettings, bridge=bridge)) as c:  # same DB, engine on allston
        h = c.get("/health").json()
        assert (h["scenario_id"], h["plan_version"]) == ("allston_flood_v1", 1)
