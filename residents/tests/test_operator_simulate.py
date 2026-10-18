"""Task 6 (scripted operator prompts), Task 7 (POST /simulate), and /optimize not blocking the rest."""
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from residents.app import DEFAULT_ASK, create_app
from residents.contracts import def_errors
from tests.helpers import JUDGE, SCENARIO, FakeLLM, ex, fact, judge_need

OP = {"facility_id": "mt-auburn"}


@pytest.fixture
def oc(settings, bridge):
    llm = FakeLLM({"about 90 minutes of diesel": ex(fact("facility_status", endurance_min=90)), "hi": ex(fact("other"))})
    s = replace(settings, scenario=SCENARIO, extract_enabled=True)
    with TestClient(create_app(s, bridge=bridge, llm=llm)) as c:
        c.post("/phones", json={"role": "operator", "handle": "6175550140"})
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        yield c


def outs(c, thread):
    return [m for m in c.get("/state").json()["messages"] if m["direction"] == "out" and m["thread"] == thread]


def metrics_ok(m):
    return def_errors("state", "plan_metrics", m) == []


def test_simulate_ember_and_baseline(oc):
    oc.post("/reports", json=judge_need())
    st = oc.get("/state").json()
    e = oc.post("/simulate", json={"planner": "ember"}).json()
    b = oc.post("/simulate", json={"planner": "baseline"}).json()
    assert e["plan_version"] == b["plan_version"] == st["plan_version"] == 2
    assert metrics_ok(e["metrics"]) and metrics_ok(b["metrics"]) and e["metrics"]["projected"] is True
    for k in ("people_reached_before_deadline", "people_unreached", "overflow_m3", "hospital_outage_s"):
        assert e["metrics"][k] == st["plan"]["metrics"][k], k       # ember = what the state already shows
    assert b["metrics"] != e["metrics"]                              # a different planner on the same facts
    assert not metrics_ok({"people_unreached": -1})                  # the check itself can fail
    assert oc.post("/simulate", json={"planner": "oracle"}).status_code == 422


def test_ask_uses_the_plans_question_and_marks_it(oc):
    q = next(q for q in oc.get("/state").json()["plan"]["info_requests"] if q["to"] == {"household_id": JUDGE})
    r = oc.post("/ask", json={"role": "resident"}).json()
    assert r["info_request"] == q["id"] and r["message"]["text"] == f"[EMBER drill] {q['question']}" and r["delivery"] == "dev"
    oc.post("/dev/inbound", json={"role": "resident", "text": "hi"})
    assert sum(q["question"] in m["text"] for m in outs(oc, {"household_id": JUDGE})) == 1   # not asked again


def test_ask_operator_then_reply_replans(oc):
    r = oc.post("/ask", json={"role": "operator"}).json()
    assert r["message"]["thread"] == OP
    assert r["message"]["text"] in (f"[EMBER drill] {DEFAULT_ASK['operator']}",) or r["info_request"]
    oc.post("/dev/inbound", json={"role": "operator", "text": "about 90 minutes of diesel"})
    st = oc.get("/state").json()
    rep = next(x for x in st["reports"] if x["source"] == "operator")
    assert rep["kind"] == "facility_status" and rep["payload"]["set"]["backup_endurance_s"] == 5400
    assert st["plan_version"] == 2 and outs(oc, OP)[-1]["direction"] == "out"   # and the operator got an answer
    custom = oc.post("/ask", json={"role": "operator", "question": "Is your generator fuelled?"}).json()
    assert custom["message"]["text"] == "[EMBER drill] Is your generator fuelled?" and custom["info_request"] is None


def _slow_optimize(c, seconds):
    real = c.app.state.planner.bridge.optimize
    started = threading.Event()

    def slow(*a, **k):
        started.set()
        time.sleep(seconds)
        return real(*a, **k)
    c.app.state.planner.bridge.optimize = slow
    return real, started


def _wait_done(c, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get("/optimize").json()
        if not r["running"] and r["last"] is not None:
            return r["last"]
        time.sleep(0.05)
    raise AssertionError("optimize never finished")


def test_optimize_does_not_block_clock_or_reports(oc):
    real, started = _slow_optimize(oc, 2.0)
    try:
        assert oc.post("/optimize?seeds=2&k=2").status_code == 202
        assert started.wait(5)
        t0 = time.time()
        assert oc.post("/clock", json={"t_s": 600}).status_code == 200     # the web's play loop keeps working
        assert time.time() - t0 < 1.0
        last = _wait_done(oc)
        assert last["error"] is None and last["plan_version"] == 2
    finally:
        oc.app.state.planner.bridge.optimize = real


def test_report_during_optimize_supersedes_it(oc):
    real, started = _slow_optimize(oc, 2.0)
    try:
        oc.post("/optimize?seeds=2&k=2")
        assert started.wait(5)
        assert oc.post("/reports", json=judge_need()).json()["plan_version"] == 2   # a judge text lands meanwhile
        last = _wait_done(oc)
        assert last["error"] and "superseded" in last["error"]
        st = oc.get("/state").json()
        assert st["plan_version"] == 2 and st["plan"]["trigger"] == "Judge: 2 people, wheelchair"  # the newer facts win
    finally:
        oc.app.state.planner.bridge.optimize = real
