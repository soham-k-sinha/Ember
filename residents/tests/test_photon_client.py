"""PhotonClient request shapes, retries and idempotency; parse_inbound."""
import json

import httpx
import pytest

from residents.photon import PhotonClient, PhotonError, parse_inbound
from tests.fake_photon import LINE, PROJECT, FakePhoton, received


async def test_create_assignment_request_shape():
    fp = FakePhoton(); c = fp.client()
    a = await c.create_assignment("+16175550120")
    r = fp.requests[0]
    assert r.method == "POST" and r.url.path == f"/v1/projects/{PROJECT}/platforms/imessage/assignments"
    assert json.loads(r.content) == {"handle": "+16175550120"}
    assert r.headers["authorization"] == "Bearer pho_sk_test"
    assert r.headers["idempotency-key"] == "ember-assign-+16175550120"
    assert a["assignedPhoneNumber"] == LINE


async def test_send_text_shape():
    fp = FakePhoton(); c = fp.client()
    res = await c.send_text("pho_spc_1", "pho_usr_line", "[EMBER drill] hi", idempotency_key="ember-m-1")
    assert res["id"] == "pho_msg_out1"
    assert fp.sends() == [{"spaceId": "pho_spc_1", "senderId": "pho_usr_line",
                           "content": {"type": "text", "format": "plain", "text": "[EMBER drill] hi"}, "_key": "ember-m-1"}]


async def test_retry_on_503_reuses_the_idempotency_key(monkeypatch):
    monkeypatch.setattr("residents.photon._backoff", _no_sleep)
    fp = FakePhoton(); fp.fail_sends = 2; c = fp.client()
    await c.send_text("s", "u", "t", idempotency_key="ember-m-9")
    keys = [r.headers["idempotency-key"] for r in fp.requests]
    assert keys == ["ember-m-9"] * 3 and fp.n_sent == 1


async def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("residents.photon._backoff", _no_sleep)
    fp = FakePhoton(); fp.fail_sends = 10; c = fp.client()
    with pytest.raises(PhotonError) as e:
        await c.send_text("s", "u", "t", idempotency_key="k")
    assert e.value.status == 503 and len(fp.requests) == 3


async def test_4xx_is_not_retried():
    fp = FakePhoton(); fp.reject_sends = True; c = fp.client()
    with pytest.raises(PhotonError) as e:
        await c.send_text("s", "u", "t", idempotency_key="k")
    assert e.value.status == 403 and "SHARED_LINE_NOT_OPTED_IN" in str(e.value) and len(fp.requests) == 1


async def test_network_error_retried(monkeypatch):
    monkeypatch.setattr("residents.photon._backoff", _no_sleep)
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(202, json={"id": "x"})
    c = PhotonClient("k", PROJECT, transport=httpx.MockTransport(handler))
    assert (await c.send_text("s", "u", "t", idempotency_key="k"))["id"] == "x" and calls["n"] == 2


async def test_list_received_params():
    from datetime import datetime, timezone
    fp = FakePhoton(); c = fp.client()
    await c.list_received(datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc))
    q = dict(fp.requests[0].url.params)
    assert q["direction"] == "received" and q["order"] == "asc" and q["createdSince"] == "2026-10-17T12:00:00Z"


def test_parse_inbound_text():
    i = parse_inbound(received("pho_msg_1", "+16175550120", "we need an accessible van"))
    assert (i.external_id, i.handle, i.text, i.space_id, i.peer_user_id, i.agent_user_id) == \
        ("pho_msg_1", "+16175550120", "we need an accessible van", "pho_spc_0120", "pho_usr_0120", "pho_usr_line")


def test_parse_inbound_ignores_non_text_and_sent():
    assert parse_inbound(received("a", "+16175550120", "", content_type="space.typing.update")) is None
    assert parse_inbound(received("a", "+16175550120", "   ")) is None
    assert parse_inbound(dict(received("a", "+16175550120", "hi"), status="delivered")) is None
    assert parse_inbound({"status": "received", "content": {"type": "text", "text": "hi"}}) is None  # no ids


def test_parse_inbound_agent_from_participants_when_receivedBy_missing():
    obj = received("a", "+16175550120", "hi"); del obj["receivedBy"]
    assert parse_inbound(obj).agent_user_id == "pho_usr_line"


async def _no_sleep(*_a, **_k):
    return None
