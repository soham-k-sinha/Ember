"""Task 4: after a replan, each opted-in phone gets a text only when ITS instruction materially changed;
plan info_requests are asked once. Plus POST /optimize streaming scatter points (local pool)."""
import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.messaging import DISCLOSURE
from residents.outbound import ASK_NEEDS
from residents.outbound import MATERIAL_ETA_S, Outbound
from tests.helpers import JUDGE, SCENARIO, FakeLLM, ex, fact, judge_need


@pytest.fixture
def oc(settings, bridge):
    s = replace(settings, scenario=SCENARIO)
    with TestClient(create_app(s, bridge=bridge)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})   # Photon off → delivery "dev"
        c.post("/phones", json={"role": "operator", "handle": "6175550140"})
        yield c


def outs(c, thread):
    return [m for m in c.get("/state").json()["messages"] if m["direction"] == "out" and m["thread"] == thread]


def test_judge_gets_one_instruction_with_version_and_assignment(oc):
    oc.post("/reports", json=judge_need())
    st = oc.get("/state").json()
    [m] = outs(oc, {"household_id": JUDGE})
    a = next(x for x in st["plan"]["assignments"] if x["id"] == m["assignment_id"])
    assert a["target"] == {"household_id": JUDGE} and a["status"] == "confirmed"  # it reached them: we proceed (D99)
    assert m["plan_version"] == st["plan_version"] == 2
    assert m["text"].startswith(f"{DISCLOSURE} Accessible Van 3 is coming to your door") and "(plan v2)" in m["text"]
    assert "Reply" not in m["text"]


def test_no_text_when_nothing_material_changed(oc):
    oc.post("/reports", json=judge_need())
    oc.post("/replan")           # v3: same assignment for the judge
    oc.post("/replan")           # v4
    assert len(outs(oc, {"household_id": JUDGE})) == 1


def test_confirmed_status_survives_the_next_replan(oc):
    oc.post("/reports", json=judge_need())
    aid = outs(oc, {"household_id": JUDGE})[0]["assignment_id"]
    oc.post("/replan")
    a = next(x for x in oc.get("/state").json()["plan"]["assignments"] if x["id"] == aid)
    assert a["status"] in ("confirmed", "en_route", "working", "done")  # not back to "proposed"


def test_phone_less_households_get_nothing(oc):
    oc.post("/reports", json=judge_need())
    st = oc.get("/state").json()
    assert {json.dumps(m["thread"]) for m in st["messages"] if m["direction"] == "out"} <= {
        json.dumps({"household_id": JUDGE}), json.dumps({"facility_id": "mt-auburn"})}


def view(assignments, version=5, info=()):
    return {"version": version, "assignments": assignments, "info_requests": list(info)}


def rescue(aid="a-van-3-10296", res="van-3", eta=6000.0, status="proposed"):
    return {"id": aid, "resource_id": res, "task": "rescue", "target": {"household_id": JUDGE}, "eta_s": eta,
            "status": status, "dropoff_facility_id": "treehouse-shelter"}


def test_material_change_rules(oc):
    ob: Outbound = oc.app.state.outbound
    run = lambda v: oc.portal.call(ob.sync, v)  # noqa: E731
    assert len(run(view([rescue()]))) == 1                                   # first instruction
    assert run(view([rescue(eta=6000 + MATERIAL_ETA_S - 1)])) == []          # small ETA drift: quiet
    [m] = run(view([rescue(eta=6000 + MATERIAL_ETA_S + 60)]))                # big ETA move: tell them
    assert "in about" in m["text"]
    [m] = run(view([rescue(aid="a-van-1-10296", res="van-1")]))              # different vehicle
    assert m["text"].startswith("Your pickup changed because ") and " Van 1 picks you up " in m["text"]
    assert m["assignment_id"] == "a-van-1-10296"
    [m] = run(view([rescue(aid="a-van-1-10296", res="van-1", status="cancelled")]))  # no longer coming
    assert "no longer coming" in m["text"]
    assert run(view([])) == []                                               # and we don't repeat it


def test_generator_instruction_goes_to_the_operator(oc):
    ob: Outbound = oc.app.state.outbound
    gen = {"id": "a-gen-1-mt-auburn", "resource_id": "gen-1", "task": "protect", "target": {"facility_id": "mt-auburn"},
           "eta_s": 6000.0, "status": "proposed", "dropoff_facility_id": None}
    [m] = oc.portal.call(ob.sync, view([gen]))
    assert m["thread"] == {"facility_id": "mt-auburn"} and m["text"].startswith(f"{DISCLOSURE} Generator 1 (500 kW, camlock) is on its way")


def test_info_request_asked_once_after_hi(settings, bridge):
    llm = FakeLLM({"hi": ex(fact("other")), "hello?": ex(fact("other"))})
    s = replace(settings, scenario=SCENARIO, extract_enabled=True)
    with TestClient(create_app(s, bridge=bridge, llm=llm)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        assert any(q["to"] == {"household_id": JUDGE} for q in c.get("/state").json()["plan"]["info_requests"])
        c.post("/dev/inbound", json={"role": "resident", "text": "hi"})
        assert [m["text"] for m in outs(c, {"household_id": JUDGE})] == [f"{DISCLOSURE} {ASK_NEEDS}"]
        c.post("/dev/inbound", json={"role": "resident", "text": "hello?"})
        assert len(outs(c, {"household_id": JUDGE})) == 1                    # not asked twice
        c.post("/dev/reset")
        c.post("/dev/inbound", json={"role": "resident", "text": "hi"})
        assert len(outs(c, {"household_id": JUDGE})) == 1                    # a new run asks again


def test_optimize_streams_points_then_plan(oc):
    with oc.websocket_connect("/ws") as ws:
        ws.receive_json()
        r = oc.post("/optimize?seeds=2&k=2")
        assert r.status_code == 202
        assert oc.post("/optimize?seeds=2&k=2").status_code == 409             # one at a time
        types, points = [], []
        while "plan" not in types:
            e = ws.receive_json()
            types.append(e["type"])
            if e["type"] == "scatter_point":
                points.append(e["data"])
    assert types.index("plan") > max(i for i, t in enumerate(types) if t == "scatter_point")  # all points first
    assert len(points) == points[0]["n_total"] == (2 + 1) * 2                  # (k + baseline) × seeds
    for _ in range(100):
        last = oc.get("/optimize").json()
        if not last["running"]:
            break
        time.sleep(0.05)
    assert last["last"]["error"] is None and last["last"]["points"] == 6
    st = oc.get("/state").json()
    assert st["plan_version"] == last["last"]["plan_version"] == 2 and st["plan"]["search"]["robust"]
    assert oc.post("/optimize?seeds=0").status_code == oc.post("/optimize?seeds=2001").status_code == 422
    assert oc.post("/optimize?seeds=2&k=9").status_code == 422
