"""Several real phone conversations share a plan, but never each other's identity/context."""
from dataclasses import replace
import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.db import Store
from residents.photon import parse_inbound
from tests.fake_photon import FakePhoton, received
from tests.helpers import JUDGE, SCENARIO, FakeLLM, deliver, ex, fact

PHONE_A = "+16175550101"
PHONE_B = "+16175550102"


@pytest.fixture
def multi(settings, bridge, monkeypatch):
    async def no_wait(*args):
        pass
    monkeypatch.setattr("residents.photon._backoff", no_wait)
    fp = FakePhoton()
    llm = FakeLLM({"hi": ex(fact("other")),
                   "two with wheelchair": ex(fact("need", people=2, accessible_vehicle=True, mobility=True)),
                   "three people": ex(fact("need", people=3)),
                   "wheelchair": ex(fact("need", accessible_vehicle=True, mobility=True)),
                   "yes": ex(fact("confirm")), "no": ex(fact("reject"))})
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, photon_enabled=True, photon_listen=False)
    with TestClient(create_app(s, photon_client=fp.client(), bridge=bridge, llm=llm)) as c:
        other = next(h["household_id"] for h in c.get("/state").json()["households"] if not h.get("judge"))
        yield c, fp, other


def register(c, phone, hid):
    return c.post("/phones", json={"role": "resident", "handle": phone, "household_id": hid})


def test_two_households_do_not_replace_each_other(multi):
    c, fp, other = multi
    assert register(c, PHONE_A, JUDGE).status_code == 200
    assert register(c, PHONE_B, other).status_code == 200
    phones = c.get("/phones").json()
    assert {p["handle"]: p["thread"] for p in phones} == {
        PHONE_A: {"household_id": JUDGE}, PHONE_B: {"household_id": other}}
    before = len(fp.requests)
    conflict = register(c, "+16175550103", JUDGE)
    assert conflict.status_code == 409
    assert len(fp.requests) == before  # fail before creating an external assignment
    assert len(c.get("/phones").json()) == 2


def test_ask_before_opt_in_does_not_consume_question(multi):
    c, fp, _ = multi
    register(c, PHONE_A, JUDGE)
    question = next(q for q in c.get("/state").json()["plan"]["info_requests"] if q["to"] == {"household_id": JUDGE})
    result = c.post("/ask", json={"role": "resident", "household_id": JUDGE}).json()
    assert result["delivery"] == "not_opted_in"
    assert "text" in result["action_needed"].lower()
    assert c.app.state.store.kv_get(f"asked:{question['id']}") is None
    assert fp.sends() == []
    deliver(c, received("first-a", PHONE_A, "hi"))
    assert c.get("/phones").json()[0]["opted_in"] is True
    assert any(question["question"] in s["content"]["text"] for s in fp.sends())


def test_targeted_ask_and_inbound_are_isolated(multi):
    c, fp, other = multi
    register(c, PHONE_A, JUDGE)
    register(c, PHONE_B, other)
    deliver(c, received("hello-a", PHONE_A, "hi"))
    deliver(c, received("hello-b", PHONE_B, "hi"))
    assert c.post("/ask", json={"role": "resident"}).status_code == 422
    assert c.post("/dev/inbound", json={"role": "resident", "text": "hi"}).status_code == 422
    for phone, hid in ((PHONE_A, JUDGE), (PHONE_B, other)):
        r = c.post("/ask", json={"role": "resident", "household_id": hid, "question": f"Question for {hid}?"})
        assert r.status_code == 200 and r.json()["delivery"] == "sent"
        assert fp.sends()[-1]["spaceId"] == f"pho_spc_{phone[-4:]}"
    deliver(c, received("need-a", PHONE_A, "two with wheelchair"))
    deliver(c, received("need-b", PHONE_B, "three people"))
    state = c.get("/state").json()
    a = next(h for h in state["households"] if h["household_id"] == JUDGE)
    b = next(h for h in state["households"] if h["household_id"] == other)
    assert a["needs"]["people"] == 2 and a["needs"]["accessible_vehicle"] is True
    assert b["needs"]["people"] == 3
    for text, hid in (("two with wheelchair", JUDGE), ("three people", other)):
        assert next(m for m in state["messages"] if m["text"] == text)["thread"] == {"household_id": hid}
    assert state["plan_version"] == 3


@pytest.mark.parametrize("body", [
    {"household_id": 999999999},
    {"facility_id": "mt-auburn"},
    {"household_id": JUDGE, "facility_id": "mt-auburn"},
    {"household_id": JUDGE, "opted_in": True},
])
def test_invalid_registration_has_no_side_effects(multi, body):
    c, fp, _ = multi
    r = c.post("/phones", json={"role": "resident", "handle": PHONE_A, **body})
    assert r.status_code == 422
    assert fp.requests == [] and c.get("/phones").json() == []


def test_same_phone_cannot_be_bound_to_two_households(multi):
    c, fp, other = multi
    register(c, PHONE_A, JUDGE)
    deliver(c, received("hello", PHONE_A, "hi"))
    again = register(c, PHONE_A, JUDGE)
    assert again.status_code == 200 and again.json()["opted_in"]
    before = len(fp.requests)
    assert register(c, PHONE_A, other).status_code == 409
    assert len(fp.requests) == before
    assert c.get("/phones").json()[0]["thread"] == {"household_id": JUDGE}


def test_pending_needs_and_simultaneous_texts_are_isolated(multi):
    c, fp, other = multi
    register(c, PHONE_A, JUDGE)
    register(c, PHONE_B, other)
    deliver(c, received("partial-a", PHONE_A, "wheelchair"))
    store = c.app.state.store
    pending_a = store.kv_get(f"pending:household:{JUDGE}")
    assert json.loads(pending_a)["accessible_vehicle"] is True
    deliver(c, received("complete-b", PHONE_B, "three people"))
    assert store.kv_get(f"pending:household:{JUDGE}") == pending_a
    assert store.kv_get(f"pending:household:{other}") is None

    async def both():
        messenger = c.app.state.messenger
        return await asyncio.gather(
            messenger.handle_inbound(parse_inbound(received("complete-a", PHONE_A, "three people"))),
            messenger.handle_inbound(parse_inbound(received("update-b", PHONE_B, "two with wheelchair"))))
    results = c.portal.call(both)
    assert [m["thread"] for m in results] == [{"household_id": JUDGE}, {"household_id": other}]
    state = c.get("/state").json()
    households = {h["household_id"]: h for h in state["households"]}
    assert households[JUDGE]["needs"]["people"] == 3 and households[JUDGE]["needs"]["accessible_vehicle"]
    assert households[other]["needs"]["people"] == 2 and households[other]["needs"]["accessible_vehicle"]
    assert store.kv_get(f"pending:household:{JUDGE}") is None
    assert state["plan_version"] == 4


def test_new_line_requires_new_opt_in(multi):
    c, fp, _ = multi
    register(c, PHONE_A, JUDGE)
    deliver(c, received("hello-a", PHONE_A, "hi"))
    c.app.state.store.upsert_phone(PHONE_A, "resident", assigned_number="+16175550999")
    # FakePhoton returns its usual line: a different one from the saved line above.
    result = register(c, PHONE_A, JUDGE).json()
    assert result["opted_in"] is False
    assert result["space_id"] is None and result["agent_user_id"] is None
    before = len(fp.sends())
    assert c.post("/ask", json={"role": "resident", "household_id": JUDGE}).json()["delivery"] == "not_opted_in"
    assert len(fp.sends()) == before


def test_concurrent_registration_preserves_one_phone_per_household(multi):
    c, fp, _ = multi
    messenger = c.app.state.messenger

    async def both():
        return await asyncio.gather(messenger.register_phone("resident", PHONE_A, JUDGE),
                                    messenger.register_phone("resident", PHONE_B, JUDGE), return_exceptions=True)
    result = c.portal.call(both)
    assert sum(isinstance(r, dict) for r in result) == 1
    assert sum(isinstance(r, ValueError) for r in result) == 1
    assert len(c.get("/phones").json()) == 1
    assert len(fp.requests) == 1


def test_confirm_and_reject_only_affect_the_senders_household(multi):
    c, fp, other = multi
    register(c, PHONE_A, JUDGE)
    register(c, PHONE_B, other)
    deliver(c, received("need-a", PHONE_A, "two with wheelchair"))
    deliver(c, received("hi-b", PHONE_B, "hi"))
    state = c.get("/state").json()
    offer_a = next(m for m in reversed(state["messages"]) if m["direction"] == "out"
                   and m["thread"] == {"household_id": JUDGE} and m["assignment_id"])
    offer_b = next(m for m in reversed(state["messages"]) if m["direction"] == "out"
                   and m["thread"] == {"household_id": other} and m["assignment_id"])
    deliver(c, received("yes-b", PHONE_B, "yes"))
    state = c.get("/state").json()
    # Snapshot statuses describe travel progress (e.g. en_route at t=0). The raw
    # plan preserves the person's confirmation independently of that progress.
    raw = c.get(f"/plan/{state['plan_version']}").json()
    assignments = {a["id"]: a for a in raw["assignments"]}
    assert assignments[offer_b["assignment_id"]]["status"] == "confirmed"
    assert assignments[offer_a["assignment_id"]]["status"] != "confirmed"
    deliver(c, received("no-a", PHONE_A, "no"))    # the only accessible van: "reply NO to decline anyway" (D57)
    assert c.app.state.store.kv_get(f"rejected:household:{JUDGE}") is None
    deliver(c, received("no-a2", PHONE_A, "no"))
    state = c.get("/state").json()
    confirm = next(r for r in state["reports"] if r["kind"] == "confirm")
    reject = next(r for r in state["reports"] if r["kind"] == "reject")
    assert confirm["household_id"] == other and confirm["assignment_id"] == offer_b["assignment_id"]
    assert reject["household_id"] == JUDGE and reject["assignment_id"] == offer_a["assignment_id"]
    assert c.app.state.store.kv_get(f"rejected:household:{other}") is None
    assert c.app.state.store.kv_get(f"rejected:household:{JUDGE}")


def test_unsent_offer_is_not_confirmed_by_first_yes(multi):
    c, fp, _ = multi
    register(c, PHONE_A, JUDGE)
    r = c.post("/dev/inbound", json={"role": "resident", "household_id": JUDGE, "text": "two with wheelchair"})
    assert r.status_code == 200 and fp.sends() == []
    assert c.get("/phones").json()[0]["opted_in"] is False  # dev injection cannot opt a phone in
    store = c.app.state.store
    assert store.kv_get(f"instr:household:{JUDGE}") is None
    assert store.last_outbound_plan_version(f"household:{JUDGE}") is None
    deliver(c, received("yes-before-offer", PHONE_A, "yes"))
    state = c.get("/state").json()
    assert not any(r["kind"] == "confirm" for r in state["reports"])
    assert not any(a["status"] == "confirmed" for a in state["plan"]["assignments"])
    assert fp.sends() and "Reply YES" in fp.sends()[-1]["content"]["text"]


def test_reset_keeps_both_opt_ins_and_targets(multi):
    c, fp, other = multi
    register(c, PHONE_A, JUDGE)
    register(c, PHONE_B, other)
    deliver(c, received("hello-a", PHONE_A, "hi"))
    deliver(c, received("hello-b", PHONE_B, "hi"))
    before = c.get("/phones").json()
    assert c.post("/dev/reset").status_code == 200
    assert c.get("/phones").json() == before
    n = len(fp.sends())
    assert deliver(c, received("hello-a", PHONE_A, "hi")) is None
    assert deliver(c, received("hello-b", PHONE_B, "hi")) is None
    assert len(fp.sends()) == n


def test_legacy_instruction_marker_keeps_offer_without_resending(multi):
    c, fp, _ = multi
    register(c, PHONE_A, JUDGE)
    deliver(c, received("need-a", PHONE_A, "two with wheelchair"))
    store = c.app.state.store
    key = f"instr:household:{JUDGE}"
    marker = json.loads(store.kv_get(key))
    marker.pop("message_id")  # layout written by the old backend
    store.kv_set(key, json.dumps(marker))
    before = len(fp.sends())
    result = c.post("/replan").json()
    raw = c.get(f"/plan/{result['plan_version']}").json()
    assert next(a for a in raw["assignments"] if a["id"] == marker["assignment_id"])["status"] == "offered"
    assert len(fp.sends()) == before


def test_failed_sends_retry_to_the_original_household(multi):
    c, fp, other = multi
    register(c, PHONE_A, JUDGE)
    register(c, PHONE_B, other)
    deliver(c, received("hi-a", PHONE_A, "hi"))
    deliver(c, received("hi-b", PHONE_B, "hi"))
    fp.fail_sends = 99
    attempts = []
    for phone, hid in ((PHONE_A, JUDGE), (PHONE_B, other)):
        result = c.post("/ask", json={"role": "resident", "household_id": hid, "question": f"Retry {hid}?"}).json()
        assert result["delivery"] == "failed"
        attempts.append((result["message"]["id"], phone))
    fp.fail_sends = 0
    before = len(fp.sends())
    assert c.portal.call(c.app.state.messenger.retry_failed) == 2
    assert {(s["_key"], s["spaceId"]) for s in fp.sends()[before:]} == {
        (f"ember-{mid}", f"pho_spc_{phone[-4:]}") for mid, phone in attempts}
    assert c.portal.call(c.app.state.messenger.retry_failed) == 0


def test_operator_and_resident_targets_do_not_cross(multi):
    c, fp, _ = multi
    register(c, PHONE_A, JUDGE)
    op = c.post("/phones", json={"role": "operator", "facility_id": "mt-auburn", "handle": PHONE_B})
    assert op.status_code == 200 and op.json()["thread"] == {"facility_id": "mt-auburn"}
    deliver(c, received("hello-a", PHONE_A, "hi"))
    deliver(c, received("hello-b", PHONE_B, "hi"))
    assert c.post("/ask", json={"role": "resident", "facility_id": "mt-auburn"}).status_code == 422
    assert c.post("/ask", json={"role": "operator", "household_id": JUDGE}).status_code == 422
    assert c.post("/ask", json={"role": "operator", "facility_id": "mt-auburn"}).json()["delivery"] == "sent"
    assert fp.sends()[-1]["spaceId"] == "pho_spc_0102"


def test_binding_does_not_follow_a_different_scenario(multi):
    c, fp, _ = multi
    register(c, PHONE_A, JUDGE)
    deliver(c, received("hello-a", PHONE_A, "hi"))
    store = c.app.state.store
    store.set_meta("scenario_id", "another-scenario")
    assert c.get("/phones").json()[0]["thread"] is None
    before = len(fp.sends())
    assert deliver(c, received("wrong-scenario", PHONE_A, "three people")) is None
    r = c.post("/ask", json={"role": "resident", "household_id": JUDGE}).json()
    assert r["delivery"] == "no_phone" and len(fp.sends()) == before


def test_unknown_target_does_not_send_a_prompt(multi):
    c, fp, _ = multi
    register(c, PHONE_A, JUDGE)
    deliver(c, received("hello-a", PHONE_A, "hi"))
    before = len(fp.sends())
    for endpoint, body in (("/ask", {}), ("/dev/inbound", {"text": "hi"})):
        assert c.post(endpoint, json={"role": "resident", "household_id": 999999999, **body}).status_code == 422
    assert len(fp.sends()) == before


def test_legacy_database_migration_preserves_phone_and_opt_in(settings, state):
    # Build an actual pre-change SQLite file with UNIQUE(role), existing state, and live chat IDs.
    store = Store(settings.db_path)
    store.seed(state)
    store.close()
    with sqlite3.connect(settings.db_path) as db:
        db.execute("DROP TABLE phones")
        db.execute("""CREATE TABLE phones (
            handle TEXT PRIMARY KEY, role TEXT NOT NULL UNIQUE, assignment_id TEXT, assigned_number TEXT,
            peer_user_id TEXT, agent_user_id TEXT, space_id TEXT, last_inbound_at TEXT)""")
        db.execute("INSERT INTO phones VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (PHONE_A, "resident", "assignment-old", "+16175550000", "peer-old", "line-old", "space-old", "2026-10-17T00:00:00Z"))
    judge = next(h["household_id"] for h in state["households"] if h.get("judge"))
    other = next(h["household_id"] for h in state["households"] if not h.get("judge"))
    fp = FakePhoton()
    live_settings = replace(settings, photon_enabled=True, photon_listen=False)
    with TestClient(create_app(live_settings, photon_client=fp.client())) as c:
        [old] = c.get("/phones").json()
        assert old["opted_in"] and old["space_id"] == "space-old"
        assert old["assignment_id"] == "assignment-old" and old["thread"] == {"household_id": judge}
        assert register(c, PHONE_B, other).status_code == 200
        assert len(c.get("/phones").json()) == 2
        r = c.post("/ask", json={"role": "resident", "household_id": judge}).json()
        assert r["delivery"] == "sent" and fp.sends()[-1]["spaceId"] == "space-old"
    # Reopening applies no second migration and keeps both mappings.
    with TestClient(create_app(live_settings, photon_client=fp.client())) as c:
        phones = {p["handle"]: p for p in c.get("/phones").json()}
        assert phones[PHONE_A]["opted_in"] and phones[PHONE_B]["thread"] == {"household_id": other}
