"""Regression for the live incident (2026-10-17): after /dev/reset, with the socket down, the poller
re-fetched the tester's old texts (stale `since` marker; the reset had emptied the dedupe table) and EMBER
answered each one on the real phone. Three independent guards; each test disables nothing else."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.photon import PhotonListener, parse_inbound
from tests.fake_photon import FakePhoton, received
from tests.test_engine import JUDGE, SCENARIO, bridge  # noqa: F401
from tests.test_extract import FakeLLM, ex, fact

PHONE = "+16175550120"


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def live(settings, bridge, monkeypatch):  # noqa: F811
    async def no_wait(*_a, **_k):
        return None
    monkeypatch.setattr("residents.photon._backoff", no_wait)
    fp = FakePhoton()
    llm = FakeLLM({"Hi": ex(fact("other")), "2 of us, my mom uses a wheelchair": ex(fact("need", people=2, mobility=True, accessible_vehicle=True)),
                   "new text": ex(fact("other"))})
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, photon_enabled=True, photon_listen=False)
    with TestClient(create_app(s, photon_client=fp.client(), bridge=bridge, llm=llm)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        yield c, fp


def texts_out(c):
    return [m for m in c.get("/state").json()["messages"] if m["direction"] == "out"]


def test_texts_from_before_a_reset_are_never_answered(live):
    c, fp = live
    old = [received("old1", PHONE, "Hi", created=iso(datetime.now(timezone.utc) - timedelta(minutes=3))),
           received("old2", PHONE, "2 of us, my mom uses a wheelchair", created=iso(datetime.now(timezone.utc) - timedelta(minutes=2)))]
    c.post("/dev/reset")                                  # the run starts now; those texts are from the last one
    n = len(texts_out(c))
    for obj in old:
        assert c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(obj)) is None
    assert len(texts_out(c)) == n and c.get("/state").json()["plan_version"] == 1
    # a text sent after the reset is handled normally
    assert c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(received("new1", PHONE, "new text"))) is not None


def test_seen_ids_survive_a_reset(live):
    c, fp = live
    obj = received("m-same", PHONE, "Hi")
    assert c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(obj)) is not None
    c.post("/dev/reset")                                   # empties the messages table (the old dedupe)
    c.app.state.store.kv_delete("run_started_at")          # take the run boundary out: only the seen table is left
    assert c.get("/state").json()["households"]            # the thread resolves, so only dedupe can stop it
    n = len(texts_out(c))
    assert c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(obj)) is None
    assert len(texts_out(c)) == n
    # control: a different id from the same phone IS handled, so the None above is the dedupe
    assert c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(received("m-other", PHONE, "Hi"))) is not None


def test_poll_window_is_capped_and_kept_fresh(live):
    c, fp = live
    store = c.app.state.store
    store.kv_set(PhotonListener.POLL_SINCE_KEY, "2026-01-01T00:00:00+00:00")   # very stale marker
    lst = PhotonListener(fp.client(), store, c.app.state.messenger.handle_inbound)
    c.portal.call(lst.poll_once)
    since = datetime.fromisoformat(dict(fp.requests[-1].url.params)["createdSince"].replace("Z", "+00:00"))
    assert datetime.now(timezone.utc) - since <= timedelta(seconds=PhotonListener.MAX_LOOKBACK_S + 10)
    lst.subscribed = True                                   # while the socket is healthy the marker tracks now
    lst._mark_polled_now()
    assert datetime.now(timezone.utc) - datetime.fromisoformat(store.kv_get(PhotonListener.POLL_SINCE_KEY)) < timedelta(seconds=5)
