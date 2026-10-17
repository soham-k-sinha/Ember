"""PhotonListener: serial processing, durable cursor, replay skipping, polling fallback."""
import asyncio

import pytest

from residents.db import Store
from residents.photon import PhotonListener
from tests.fake_photon import FakePhoton, received


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "l.db")


def event(seq_obj, kind="message.received"):
    return {"id": "evt", "type": kind, "apiVersion": "2026-07-01", "data": {"projectId": "p", "object": seq_obj}}


async def run_worker(listener, items):
    task = asyncio.create_task(listener._worker())
    for ev, meta in items:
        await listener._queue.put((ev, meta))
    await listener._queue.join()
    task.cancel()


async def test_worker_handles_in_order_and_saves_cursor(store):
    got = []
    async def on_message(i):
        got.append(i.text)
    lst = PhotonListener(FakePhoton().client(), store, on_message)
    await run_worker(lst, [(event(received("m1", "+14133620520", "one")), {"seq": 5}),
                           (event({"status": "received", "content": {"type": "space.typing.update"}}), {"seq": 6}),
                           (event(received("m2", "+14133620520", "two")), {"seq": 9})])
    assert got == ["one", "two"] and lst.cursor == 9


async def test_replayed_seq_is_skipped(store):
    got = []
    async def on_message(i):
        got.append(i.text)
    store.kv_set(PhotonListener.CURSOR_KEY, "9")
    lst = PhotonListener(FakePhoton().client(), store, on_message)
    await run_worker(lst, [(event(received("m1", "+1", "old")), {"seq": 9}), (event(received("m3", "+14133620520", "new")), {"seq": 10})])
    assert got == ["new"] and lst.cursor == 10


async def test_handler_failure_does_not_block_the_stream(store, monkeypatch):
    monkeypatch.setattr("residents.photon.asyncio.sleep", _no_sleep)
    got = []
    async def on_message(i):
        if i.text == "bad":
            raise RuntimeError("boom")
        got.append(i.text)
    lst = PhotonListener(FakePhoton().client(), store, on_message)
    await run_worker(lst, [(event(received("m1", "+14133620520", "bad")), {"seq": 1}),
                           (event(received("m2", "+14133620520", "good")), {"seq": 2})])
    assert got == ["good"] and lst.cursor == 2


async def test_poll_once_hands_texts_over_and_advances(store):
    fp = FakePhoton()
    fp.received_items = [received("m1", "+14133620520", "hi", created="2026-10-17T12:00:01Z"),
                         received("m2", "+14133620520", "", created="2026-10-17T12:00:02Z", content_type="message.read"),
                         received("m3", "+14134094408", "6 hours", created="2026-10-17T12:00:03Z")]
    got = []
    async def on_message(i):
        got.append(i.external_id)
    store.kv_set(PhotonListener.POLL_SINCE_KEY, "2026-10-17T12:00:00+00:00")
    lst = PhotonListener(fp.client(), store, on_message)
    assert await lst.poll_once() == 2 and got == ["m1", "m3"]
    assert store.kv_get(PhotonListener.POLL_SINCE_KEY) == "2026-10-17T12:00:03+00:00"


async def test_polling_only_while_socket_down(store):
    lst = PhotonListener(FakePhoton().client(), store, _no_sleep, poll_after_down_s=0.0)
    loop = asyncio.get_running_loop()
    lst.subscribed, lst.down_since = True, None
    assert not lst._polling_active()
    lst._mark_down()
    assert lst._polling_active()
    lst.poll_after_down_s = 60.0
    assert not lst._polling_active()  # down for less than a minute


async def _no_sleep(*_a, **_k):
    return None


class FakeSio:
    """Stands in for socketio.AsyncClient: records handlers, 'connects', acks subscribe."""
    def __init__(self):
        self.handlers, self.calls = {}, []

    def event(self, f):
        self.handlers[f.__name__] = f
        return f

    def on(self, name):
        def deco(f):
            self.handlers[name] = f
            return f
        return deco

    async def connect(self, url, **kw):
        self.url, self.kw = url, kw
        await self.handlers["connect"]()

    async def call(self, name, data, timeout):
        self.calls.append((name, data))
        return {"ok": True, "connectionId": "c1"}

    async def wait(self):
        await asyncio.Event().wait()

    async def disconnect(self):
        pass


def test_health_with_live_listener(settings, tmp_path):
    """Regression: /health runs in a worker thread; listener.status() must not need an event loop."""
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from residents.app import create_app
    fp, sio = FakePhoton(), FakeSio()
    app = create_app(replace(settings, photon_enabled=True, photon_listen=True), photon_client=fp.client())
    import residents.app as app_mod
    orig = app_mod.PhotonListener
    app_mod.PhotonListener = lambda *a, **k: orig(*a, **k, sio_factory=lambda: sio)
    try:
        with TestClient(app) as c:
            for _ in range(50):
                h = c.get("/health").json()
                if h["photon_listener"]["socket"] == "subscribed":
                    break
                c.portal.call(asyncio.sleep, 0.01)
            assert h["photon"] == "enabled" and h["photon_listener"]["socket"] == "subscribed"
            assert sio.calls == [("subscribe", {"startSeq": 0, "apiVersion": "2026-07-01"})]
            assert sio.kw["socketio_path"] == "/v1/projects/pho_prj_0test00000000000000000000000/events/ws"
            assert sio.kw["headers"] == {"Authorization": "Bearer pho_sk_test"} and sio.kw["transports"] == ["websocket"]
            # a delivery through the socket handler reaches the thread
            c.post("/phones", json={"role": "resident", "handle": "4133620520"})
            c.portal.call(sio.handlers["delivery"], event(received("m1", "+14133620520", "hi from socket")), {"seq": 3})
            for _ in range(50):
                if c.get("/state").json()["messages"][-1]["text"] == "hi from socket":
                    break
                c.portal.call(asyncio.sleep, 0.01)
            assert c.get("/state").json()["messages"][-1]["text"] == "hi from socket"
            assert c.get("/health").json()["photon_listener"]["cursor"] == 3
            # socket drops: /health must still answer (this is the path that crashed live) and report it
            c.portal.call(sio.handlers["disconnect"])
            r = c.get("/health")
            assert r.status_code == 200 and r.json()["photon_listener"]["socket"] == "down"
    finally:
        app_mod.PhotonListener = orig
