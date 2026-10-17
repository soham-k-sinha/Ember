"""Task 5: YES / NO to an offered instruction (by text or via the API), stale replies, and declines that
are never re-offered. Real allocator on allston_flood_v1; the LLM is faked."""
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from tests.test_engine import JUDGE, SCENARIO, bridge, judge_need  # noqa: F401
from tests.test_extract import FakeLLM, ex, fact

JT = {"household_id": JUDGE}


@pytest.fixture
def cc(settings, bridge):  # noqa: F811
    llm = FakeLLM({"yes": ex(fact("confirm")), "no thanks": ex(fact("reject")), "YES": ex(fact("confirm"))})
    s = replace(settings, scenario=SCENARIO, extract_enabled=True)
    with TestClient(create_app(s, bridge=bridge, llm=llm)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        c.post("/reports", json=judge_need())             # v2: Accessible Van 3 offered to the judge
        yield c


def outs(c):
    return [m for m in c.get("/state").json()["messages"] if m["direction"] == "out" and m["thread"] == JT]


def judge_asg(c):
    st = c.get("/state").json()
    return next(a for a in st["plan"]["assignments"] if a["target"] == JT and a["status"] not in ("cancelled",))


def text(c, t):
    return c.post("/dev/inbound", json={"role": "resident", "text": t}).json()["message"]


def test_yes_confirms_acks_and_sticks(cc):
    offer = outs(cc)[-1]
    assert judge_asg(cc)["status"] == "offered"
    text(cc, "yes")
    st = cc.get("/state").json()
    a = judge_asg(cc)
    assert a["id"] == offer["assignment_id"] and a["status"] == "confirmed"
    assert next(h for h in st["households"] if h["household_id"] == JUDGE)["status"] == "confirmed"
    rep = next(r for r in st["reports"] if r["kind"] == "confirm")
    assert rep["assignment_id"] == offer["assignment_id"] and rep["plan_version"] == 2
    assert outs(cc)[-1]["text"].startswith("[EMBER drill] Confirmed: Accessible Van 3 is coming to you")
    cc.post("/replan")                                     # the allocator keeps confirmed work
    a2 = judge_asg(cc)
    assert (a2["id"], a2["resource_id"], a2["status"]) == (a["id"], a["resource_id"], "confirmed")
    later = outs(cc)[2:]
    # the allocator may move confirmed work earlier (ETA change ≥ 10 min → an update text), but never re-asks
    assert all(m["text"].startswith("[EMBER drill] Update: Accessible Van 3 is now arriving") for m in later)
    assert len(later) <= 1


def test_no_rejects_replans_and_never_reoffers_that_vehicle(cc):
    offer = outs(cc)[-1]
    text(cc, "no thanks")
    st = cc.get("/state").json()
    assert st["plan_version"] == 3                         # reject → replan
    acks = [m["text"] for m in outs(cc)[1:]]
    assert acks[0].startswith("[EMBER drill] Understood, we won't send Accessible Van 3")
    assert not any("Accessible Van 3 will pick you up" in t for t in acks)     # never re-offered
    van3 = [a for a in st["plan"]["assignments"] if a["target"] == JT and a["resource_id"] == "van-3"]
    assert all(a["status"] == "rejected" for a in van3)   # if the allocator re-proposes it, it stays declined
    assert json.loads(cc.app.state.store.kv_get(f"rejected:household:{JUDGE}")) == ["van-3"]
    assert any(r["kind"] == "reject" and r["assignment_id"] == offer["assignment_id"] for r in st["reports"])


def _retarget_in_current_plan(c, assignment_id, new_resource):
    """Simulate the allocator having moved this assignment to another vehicle in a newer version."""
    c.post("/replan")                                      # v3
    store = c.app.state.store
    v = store.meta()["plan_version"]
    db = store._db
    row = db.execute("SELECT data FROM assignments WHERE plan_version=? AND id=?", (v, assignment_id)).fetchone()
    a = json.loads(row["data"]); a["resource_id"] = new_resource
    db.execute("UPDATE assignments SET resource_id=?, data=? WHERE plan_version=? AND id=?", (new_resource, json.dumps(a), v, assignment_id))
    return v


def test_stale_yes_is_not_applied_and_gets_the_latest(cc):
    offer = outs(cc)[-1]
    v = _retarget_in_current_plan(cc, offer["assignment_id"], "van-1")
    r = cc.post(f"/assignments/{offer['assignment_id']}/confirm", json={"plan_version": 2})
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    n = len(outs(cc))
    text(cc, "YES")                                        # their reply carries plan_version 2 (the offer's)
    raw = cc.app.state.store.plan(v)
    assert next(a for a in raw["assignments"] if a["id"] == offer["assignment_id"])["status"] != "confirmed"
    assert len(outs(cc)) == n + 1                          # the latest instruction, re-sent


def test_old_version_but_unchanged_assignment_is_applied(cc):
    offer = outs(cc)[-1]
    cc.post("/replan")                                     # v3, same assignment
    r = cc.post(f"/assignments/{offer['assignment_id']}/confirm", json={"plan_version": 2})
    assert r.status_code == 200 and r.json()["applied"] and r.json()["assignment"]["status"] == "confirmed"


def test_api_errors_and_idempotence(cc):
    aid = outs(cc)[-1]["assignment_id"]
    assert cc.post("/assignments/nope/confirm").status_code == 409
    assert cc.post(f"/assignments/{aid}/confirm").json()["applied"] is True
    again = cc.post(f"/assignments/{aid}/confirm")
    assert again.status_code == 200 and again.json()["applied"] is False and again.json()["reason"] == "already confirmed"
    r = cc.post(f"/assignments/{aid}/reject")             # changing their mind after confirming is allowed
    assert r.json()["applied"] and r.json()["plan_version"] == 3


def test_confirmation_survives_restart(settings, bridge):  # noqa: F811
    s = replace(settings, scenario=SCENARIO)
    with TestClient(create_app(s, bridge=bridge)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        c.post("/reports", json=judge_need())
        aid = outs(c)[-1]["assignment_id"]
        c.post(f"/assignments/{aid}/confirm")
    with TestClient(create_app(s, bridge=bridge)) as c:
        assert next(a for a in c.get("/state").json()["plan"]["assignments"] if a["id"] == aid)["status"] == "confirmed"
        c.post("/replan")
        assert next(a for a in c.get("/state").json()["plan"]["assignments"] if a["id"] == aid)["status"] == "confirmed"
