"""Threads end to end through the app: phone registration, opt-in, inbound, outbound, dedupe."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from ember_engine.scenario import load_scenario
from ember_engine.state import validate_state
from residents.app import create_app
from residents.config import CONTRACTS
from residents.photon import parse_inbound
from residents.threads import normalize_handle
from tests.fake_photon import LINE, FakePhoton, received

JUDGE_PHONE = "+16175550120"
OPERATOR_PHONE = "+16175550140"


@pytest.fixture
def fp():
    return FakePhoton()


@pytest.fixture
def app_client(settings, fp, monkeypatch):
    monkeypatch.setattr("residents.photon._backoff", _no_sleep)
    s = replace(settings, photon_enabled=True, photon_listen=False)  # inbound driven by hand below
    with TestClient(create_app(s, photon_client=fp.client())) as c:
        yield c


def deliver(client, obj):
    """What the Photon listener does with a message.received event."""
    return client.portal.call(client.app.state.messenger.handle_inbound, parse_inbound(obj))


def test_normalize_handle():
    assert normalize_handle("6175550120") == normalize_handle("+1 (617) 555-0120") == normalize_handle("16175550120") == JUDGE_PHONE
    assert normalize_handle("Judge@Example.com") == "judge@example.com"
    with pytest.raises(ValueError):
        normalize_handle("12345")


def test_register_phones_creates_assignments_and_resolves_threads(app_client, fp, fixture_state):
    r = app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    assert r.status_code == 200, r.text
    p = r.json()
    judge = next(h for h in fixture_state["households"] if h.get("judge"))
    assert p["handle"] == JUDGE_PHONE and p["assigned_number"] == LINE and p["assignment_id"] == "asg-0120"
    assert p["thread"] == {"household_id": judge["household_id"]} and p["opted_in"] is False
    p = app_client.post("/phones", json={"role": "operator", "handle": "617-555-0140"}).json()
    hosp = next(f for f in fixture_state["facilities"] if f["type"] == "hospital" and f.get("critical"))
    assert p["thread"] == {"facility_id": hosp["id"]}
    assert [x["role"] for x in app_client.get("/phones").json()] == ["operator", "resident"]


def test_occupied_default_household_does_not_replace_the_phone(app_client):
    app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    assert app_client.post("/phones", json={"role": "resident", "handle": "4135550199"}).status_code == 409
    assert [p["handle"] for p in app_client.get("/phones").json()] == [JUDGE_PHONE]


def test_bad_phone_and_role_rejected(app_client):
    assert app_client.post("/phones", json={"role": "resident", "handle": "123"}).status_code == 422
    assert app_client.post("/phones", json={"role": "mayor", "handle": "6175550120"}).status_code == 422


def test_no_send_before_opt_in(app_client, fp, fixture_state):
    app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    judge = next(h for h in fixture_state["households"] if h.get("judge"))
    r = app_client.post("/messages", json={"thread": {"household_id": judge["household_id"]}, "text": "Stay put.", "plan_version": 3})
    body = r.json()
    assert body["delivery"] == "not_opted_in" and fp.sends() == []
    assert body["message"]["text"] == "[EMBER drill] Stay put."  # stored + shown anyway


def test_inbound_opts_in_then_outbound_is_sent(app_client, fp, fixture_state):
    app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    judge_id = next(h for h in fixture_state["households"] if h.get("judge"))["household_id"]
    with app_client.websocket_connect("/ws") as ws:
        ws.receive_json()  # state
        msg = deliver(app_client, received("pho_msg_in1", JUDGE_PHONE, "hi"))
        ev = ws.receive_json()
    assert ev["type"] == "message" and ev["data"] == msg
    assert msg["thread"] == {"household_id": judge_id} and msg["direction"] == "in" and msg["text"] == "hi"
    phone = app_client.get("/phones").json()[0]
    assert phone["opted_in"] and phone["space_id"] == "pho_spc_0120" and phone["agent_user_id"] == "pho_usr_line"

    r = app_client.post("/messages", json={"thread": {"household_id": judge_id}, "text": "Van 3 is coming.",
                                           "plan_version": 3, "assignment_id": "a-x"}).json()
    assert r["delivery"] == "sent"
    [send] = fp.sends()
    assert send["spaceId"] == "pho_spc_0120" and send["senderId"] == "pho_usr_line"
    assert send["content"]["text"] == "[EMBER drill] Van 3 is coming." and send["_key"] == f"ember-{r['message']['id']}"
    store = app_client.app.state.store
    assert store.message_delivery(r["message"]["id"]) == ("sent", "pho_msg_out1")


def test_duplicate_and_unknown_inbound_ignored(app_client):
    app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    n0 = len(app_client.get("/state").json()["messages"])
    assert deliver(app_client, received("pho_msg_in1", JUDGE_PHONE, "hi")) is not None
    assert deliver(app_client, received("pho_msg_in1", JUDGE_PHONE, "hi")) is None          # redelivery
    assert deliver(app_client, received("pho_msg_in2", "+19995550000", "who dis")) is None  # not a tester
    assert len(app_client.get("/state").json()["messages"]) == n0 + 1


def test_inbound_records_the_plan_version_it_answers(app_client, fixture_state):
    app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    judge_id = next(h for h in fixture_state["households"] if h.get("judge"))["household_id"]
    deliver(app_client, received("pho_msg_in1", JUDGE_PHONE, "hi"))
    app_client.post("/messages", json={"thread": {"household_id": judge_id}, "text": "q", "plan_version": 7})
    msg = deliver(app_client, received("pho_msg_in2", JUDGE_PHONE, "2 people, one wheelchair"))
    assert msg["plan_version"] == 7


def test_failed_send_is_recorded_not_raised(app_client, fp, fixture_state):
    app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    judge_id = next(h for h in fixture_state["households"] if h.get("judge"))["household_id"]
    deliver(app_client, received("pho_msg_in1", JUDGE_PHONE, "hi"))
    fp.fail_sends = 99
    r = app_client.post("/messages", json={"thread": {"household_id": judge_id}, "text": "x", "plan_version": 3})
    assert r.status_code == 200 and r.json()["delivery"] == "failed"
    fp.fail_sends, fp.reject_sends = 0, True
    assert app_client.post("/messages", json={"thread": {"household_id": judge_id}, "text": "y"}).json()["delivery"] == "failed"


def test_thread_without_phone_is_stored_not_sent(app_client, fp, fixture_state):
    other = next(h for h in fixture_state["households"] if not h.get("judge"))
    r = app_client.post("/messages", json={"thread": {"household_id": other["household_id"]}, "text": "x"}).json()
    assert r["delivery"] == "no_phone" and fp.sends() == []


def test_message_thread_validation(app_client):
    assert app_client.post("/messages", json={"thread": {}, "text": "x"}).status_code == 422
    assert app_client.post("/messages", json={"thread": {"household_id": 1, "facility_id": "a"}, "text": "x"}).status_code == 422
    assert app_client.post("/messages", json={"thread": {"household_id": 1}, "text": ""}).status_code == 422


def test_state_still_valid_with_new_messages(app_client, town):
    app_client.post("/phones", json={"role": "operator", "handle": "6175550140"})
    deliver(app_client, received("pho_msg_in1", OPERATOR_PHONE, "about 6 hours of diesel left"))
    app_client.post("/dev/inbound", json={"role": "resident", "text": "we are 3, my mom uses a wheelchair"})
    st = app_client.get("/state").json()
    assert validate_state(st, load_scenario(CONTRACTS / "fixtures" / "scenario.fixture.json"), town) == []
    assert [m["text"] for m in st["messages"][-2:]] == ["about 6 hours of diesel left", "we are 3, my mom uses a wheelchair"]


def test_phones_survive_reset(app_client):
    app_client.post("/phones", json={"role": "resident", "handle": "6175550120"})
    deliver(app_client, received("pho_msg_in1", JUDGE_PHONE, "hi"))
    app_client.post("/dev/reset")
    assert app_client.get("/phones").json()[0]["opted_in"] is True


def test_dev_mode_never_calls_photon(client):
    r = client.post("/messages", json={"thread": {"household_id": 492}, "text": "x"}).json()
    assert r["delivery"] == "dev" and r["message"]["text"].startswith("[EMBER drill]")


def test_inbound_hooks_run(app_client):
    seen = []
    async def hook(msg, role):
        seen.append((role, msg["text"]))
    app_client.app.state.messenger.inbound_hooks.append(hook)
    app_client.post("/dev/inbound", json={"role": "resident", "text": "hello"})
    assert seen == [("resident", "hello")]


async def _no_sleep(*_a, **_k):
    return None
