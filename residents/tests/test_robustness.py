"""Task 8: two texts at once, double-sent facts, the planner throwing, Photon down for sends, and the
same inbound message arriving by polling and by the socket."""
import asyncio
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.intake import PLANNER_DOWN
from residents.messaging import plain
from residents.photon import PhotonListener, parse_inbound
from tests.fake_photon import FakePhoton, received
from tests.helpers import JUDGE, SCENARIO, FakeLLM, ex, fact

JT = {"household_id": JUDGE}
TWO = "2 of us"
WHEELCHAIR = "she uses a wheelchair"
SCRIPT = {TWO: ex(fact("need", people=2)),
          WHEELCHAIR: ex(fact("need", mobility=True, accessible_vehicle=True)),
          "2 of us, wheelchair": ex(fact("need", people=2, mobility=True, accessible_vehicle=True))}


@pytest.fixture
def rc(settings, bridge):
    s = replace(settings, scenario=SCENARIO, extract_enabled=True)
    with TestClient(create_app(s, bridge=bridge, llm=FakeLLM(SCRIPT))) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        yield c


def judge(c):
    return next(h for h in c.get("/state").json()["households"] if h["household_id"] == JUDGE)


def outs(c):
    return [m for m in c.get("/state").json()["messages"] if m["direction"] == "out" and m["thread"] == JT]


def test_two_texts_at_once_are_handled_in_order(rc):
    m = rc.app.state.messenger

    async def both():
        await asyncio.gather(m.simulate_inbound("resident", TWO), m.simulate_inbound("resident", WHEELCHAIR))
    rc.portal.call(both)
    # the second text saw the first one's head count: no "how many people?" and nothing dropped
    assert judge(rc)["needs"] == {"people": 2, "mobility": True, "accessible_vehicle": True}
    assert not any("How many people" in o["text"] for o in outs(rc))


def test_double_sent_fact_replans_once(rc):
    rc.post("/dev/inbound", json={"role": "resident", "text": "2 of us, wheelchair"})
    n_out = len(outs(rc))
    rc.post("/dev/inbound", json={"role": "resident", "text": "2 of us, wheelchair"})
    st = rc.get("/state").json()
    assert st["plan_version"] == 2
    assert len([r for r in st["reports"] if r["kind"] == "need" and r["source"] == "resident"]) == 1
    assert len(outs(rc)) == n_out + 1                    # still answered (their status)


def test_planner_failure_is_told_and_survived(rc):
    bridge_ = rc.app.state.planner.bridge
    orig = bridge_.plan

    def boom(*a, **k):
        raise RuntimeError("allocator exploded")
    bridge_.plan = boom
    try:
        r = rc.post("/dev/inbound", json={"role": "resident", "text": "2 of us, wheelchair"})
        assert r.status_code == 200
        assert plain(outs(rc)[-1]["text"]) == PLANNER_DOWN
        st = rc.get("/state").json()
        rep = next(x for x in st["reports"] if x["kind"] == "need" and x["source"] == "resident")
        assert rep["resolved"] is False and st["plan_version"] == 1
        assert rc.get("/health").json()["ok"]
    finally:
        bridge_.plan = orig
    assert rc.post("/replan").json()["plan_version"] == 2   # recovers; the stored report is used
    assert judge(rc)["needs"]["accessible_vehicle"] is True


# ---------- Photon down for sends ----------
@pytest.fixture
def pc(settings, monkeypatch):
    async def no_wait(*_a, **_k):
        return None
    monkeypatch.setattr("residents.photon._backoff", no_wait)
    fp = FakePhoton()
    s = replace(settings, photon_enabled=True, photon_listen=False)
    with TestClient(create_app(s, photon_client=fp.client())) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(received("in1", "+16175550120", "hi")))
        yield c, fp


def test_failed_sends_are_retried_once_photon_is_back(pc):
    c, fp = pc
    fp.fail_sends = 99
    r = c.post("/messages", json={"thread": {"household_id": 492}, "text": "Van 3 is coming", "plan_version": 3}).json()
    assert r["delivery"] == "failed"
    m = c.app.state.messenger
    assert c.portal.call(m.retry_failed) == 0              # still down
    fp.fail_sends = 0
    assert c.portal.call(m.retry_failed) == 1              # back: sent
    assert c.portal.call(m.retry_failed) == 0              # and never again
    keys = [s["_key"] for s in fp.sends()]
    assert set(keys) == {f"ember-{r['message']['id']}"}    # every attempt used the same Idempotency-Key
    assert fp.n_sent == 1
    assert c.app.state.store.message_delivery(r["message"]["id"]) == ("sent", "pho_msg_out1")


def test_stale_failures_are_not_retried(pc):
    c, fp = pc
    fp.fail_sends = 99
    r = c.post("/messages", json={"thread": {"household_id": 492}, "text": "old news"}).json()
    c.app.state.store._db.execute("UPDATE messages SET created_wall = ? WHERE id = ?", (time.time() - 3600, r["message"]["id"]))
    fp.fail_sends = 0
    assert c.portal.call(c.app.state.messenger.retry_failed) == 0


# ---------- inbound by both paths ----------
def test_polled_then_socket_delivery_is_stored_once(pc):
    """Photon socket down → the poller fetches the text; the socket comes back and redelivers it."""
    c, fp = pc
    obj = received("pho_msg_9", "+16175550120", "we're 3", created="2099-01-01T00:00:05Z")
    fp.received_items = [obj]
    lst = PhotonListener(fp.client(), c.app.state.store, c.app.state.messenger.handle_inbound)
    c.app.state.store.kv_set(PhotonListener.POLL_SINCE_KEY, "2099-01-01T00:00:00+00:00")
    assert c.portal.call(lst.poll_once) == 1                                           # via polling
    assert c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(obj)) is None  # via socket: dup
    assert [m["text"] for m in c.get("/state").json()["messages"]].count("we're 3") == 1
