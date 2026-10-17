"""Extraction: the deterministic code around the one LLM call (fake model), and the intake pipeline
end to end through the app with the real allocator on allston_flood_v1."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.contracts import validate_report
from residents.engine_bridge import normalize_street, street_matches
from residents.extract import Extraction, Fact, to_outcome
from residents.intake import SORRY
from tests.test_engine import JUDGE, SCENARIO, bridge  # noqa: F401  (session fixture)

NONE = dict(people=None, mobility=None, accessible_vehicle=None, medical=None, road_hint=None, cross_street=None, address=None,
            endurance_min=None, facility_state=None, question_topic=None)


def fact(kind, **kw):
    return Fact(kind=kind, **{**NONE, **kw})


def ex(*facts, confidence=0.9, q=None):
    return Extraction(facts=list(facts), confidence=confidence, clarifying_question=q)


def outcome(e, role="resident", thread=None, pending=None, roads=None, last_assignment=None):
    return to_outcome(e, role=role, thread=thread or {"household_id": JUDGE}, text="msg", pending=pending,
                      resolve_road=lambda h, c, hid: (roads or {}).get(h, []), last_assignment_id=last_assignment)


def complete(r):  # what planner.submit_report adds before validating
    return {"id": "r-x", "observed_at_t_s": 0, **r}


# ---------- street names ----------
def test_street_matching():
    assert normalize_street("River St.") == "river street"
    assert street_matches("River Street", "River St")
    assert street_matches("Western Avenue", "the Western Ave bridge")
    assert street_matches("Memorial Drive", "memorial dr")
    assert not street_matches("Riverdale Street", "River St")
    assert not street_matches("River Street", "Street")       # generic words alone never match
    assert not street_matches(None, "River St")


def test_resolve_road_near_household_and_at_cross_street(bridge):  # noqa: F811
    near = bridge.resolve_road("River St", None, JUDGE)
    assert near and all(bridge.edge_name(e) == "River Street" for e in near)
    assert sorted(near) == sorted(bridge.both_directions(near))     # both directions included
    at = bridge.resolve_road("River St", "Memorial Dr", JUDGE)
    assert at and set(at) <= set(e["id"] for e in bridge.town["edges"] if e["name"] == "River Street")
    assert bridge.resolve_road("Nonexistent Lane", None, JUDGE) == []
    assert bridge.resolve_road("River St", None, None) == []          # no anchor, no cross street → ask
    # near the household = engine's 150 m (its tested demo beat), both directions
    assert sorted(near) == sorted(bridge.both_directions(bridge.session.edges_by_name("River Street", near_household=JUDGE, radius_m=150)))
    assert len(near) <= 4                                              # a block, not the whole street


# ---------- deterministic outcome ----------
def test_full_need_becomes_one_valid_report():
    o = outcome(ex(fact("need", people=2, mobility=True, accessible_vehicle=True)))
    [r] = o.reports
    assert r["kind"] == "need" and r["household_id"] == JUDGE and r["source"] == "resident"
    assert r["payload"] == {"people": 2, "mobility": True, "accessible_vehicle": True}
    assert validate_report(complete(r)) == [] and o.question is None


def test_need_without_head_count_asks_and_holds_it():
    o = outcome(ex(fact("need", accessible_vehicle=True, mobility=True)))
    assert o.reports == [] and "How many people" in o.question
    assert o.pending == {"kind": "need", "accessible_vehicle": True, "mobility": True}


def test_reply_completes_the_pending_need():
    o = outcome(ex(fact("need", people=2)), pending={"kind": "need", "accessible_vehicle": True, "mobility": True})
    [r] = o.reports
    assert r["payload"] == {"people": 2, "mobility": True, "accessible_vehicle": True} and o.clear_pending and o.pending is None


def test_low_confidence_never_guesses():
    o = outcome(ex(fact("need", people=3), confidence=0.4, q="Did you mean 3 people?"))
    assert o.reports == [] and o.question == "Did you mean 3 people?"


def test_need_and_closure_in_one_message():
    o = outcome(ex(fact("need", people=2, accessible_vehicle=True), fact("closure_report", road_hint="River St")),
                roads={"River St": [5, 6]})
    assert [r["kind"] for r in o.reports] == ["need", "closure_report"]
    assert o.reports[1]["payload"] == {"edge_ids": [5, 6], "road_hint": "River St"}
    assert all(validate_report(complete(r)) == [] for r in o.reports)


def test_closure_without_street_or_unknown_street_asks():
    assert "Which street" in outcome(ex(fact("closure_report"))).question
    o = outcome(ex(fact("closure_report", road_hint="Elm Alley")))
    assert o.reports == [] and "Elm Alley" in o.question


def test_operator_endurance_and_state():
    o = outcome(ex(fact("facility_status", endurance_min=90, facility_state="backup")), role="operator",
                thread={"facility_id": "mt-auburn"})
    [r] = o.reports
    assert r["payload"] == {"set": {"backup_endurance_s": 5400, "state": "backup"}} and r["source"] == "operator"
    assert validate_report(complete(r)) == []
    [r] = outcome(ex(fact("facility_status", endurance_min=10, facility_state="backup")), role="operator",
                  thread={"facility_id": "mt-auburn"}).reports
    assert r["payload"]["set"]["backup_endurance_s"] == 600   # DEMO beat 4: exactly 10 min, not 612 s
    assert "hours of backup" in outcome(ex(fact("facility_status")), role="operator", thread={"facility_id": "mt-auburn"}).question


def test_confirm_only_when_something_was_offered():
    assert outcome(ex(fact("confirm"))).reports == []
    [r] = outcome(ex(fact("confirm")), last_assignment="a-van-3-10296").reports
    assert r["kind"] == "confirm" and r["assignment_id"] == "a-van-3-10296" and validate_report(complete(r)) == []


def test_facts_for_the_wrong_thread_are_ignored():
    # a resident can't set facility status; an operator can't file a household need
    assert outcome(ex(fact("facility_status", endurance_min=120))).reports == []
    assert outcome(ex(fact("need", people=2)), role="operator", thread={"facility_id": "mt-auburn"}).reports == []


# ---------- intake end to end ----------
class FakeLLM:
    def __init__(self, script):
        self.script, self.prompts = script, []

    async def __call__(self, system, user):
        self.prompts.append(user)
        text = user.split("Message:\n", 1)[1]
        r = self.script[text]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def make_client(settings, bridge):  # noqa: F811
    def make(script):
        llm = FakeLLM(script)
        s = replace(settings, scenario=SCENARIO, extract_enabled=True)
        return TestClient(create_app(s, bridge=bridge, llm=llm)), llm
    return make


def judge(st):
    return next(h for h in st["households"] if h["household_id"] == JUDGE)


def test_judge_text_replans_and_links_the_report(make_client):
    c, _ = make_client({"we are 2, my mom uses a wheelchair": ex(fact("need", people=2, mobility=True, accessible_vehicle=True))})
    with c:
        assert c.get("/health").json()["extraction"] == "on"
        msg = c.post("/dev/inbound", json={"role": "resident", "text": "we are 2, my mom uses a wheelchair"}).json()["message"]
        st = c.get("/state").json()
        assert st["plan_version"] == 2 and judge(st)["needs"]["accessible_vehicle"] is True
        stored = next(m for m in st["messages"] if m["id"] == msg["id"])
        rep = next(r for r in st["reports"] if r["id"] == stored["report_id"])
        assert rep["text"] == "we are 2, my mom uses a wheelchair" and rep["source"] == "resident" and rep["resolved"]


def test_two_facts_one_replan(make_client, bridge):  # noqa: F811
    text = "2 of us need a wheelchair van and River St is flooded"
    c, _ = make_client({text: ex(fact("need", people=2, accessible_vehicle=True, mobility=True),
                                 fact("closure_report", road_hint="River St"))})
    with c:
        c.post("/dev/inbound", json={"role": "resident", "text": text})
        st = c.get("/state").json()
        assert st["plan_version"] == 2  # one replan for both facts
        kinds = sorted(r["kind"] for r in st["reports"] if r["source"] == "resident")
        assert kinds == ["closure_report", "need"]
        assert "needs" in st["plan"]["trigger"] and "road closed" in st["plan"]["trigger"]  # one version, both facts


def test_missing_count_asks_then_reply_completes(make_client):
    c, llm = make_client({"we need a wheelchair van": ex(fact("need", accessible_vehicle=True, mobility=True)),
                          "2": ex(fact("need", people=2))})
    with c:
        c.post("/dev/inbound", json={"role": "resident", "text": "we need a wheelchair van"})
        st = c.get("/state").json()
        assert st["plan_version"] == 1 and st["messages"][-1]["direction"] == "out"
        assert st["messages"][-1]["text"].startswith("[EMBER drill] How many people")
        c.post("/dev/inbound", json={"role": "resident", "text": "2"})
        st = c.get("/state").json()
        assert st["plan_version"] == 2 and judge(st)["needs"] == {"people": 2, "mobility": True, "accessible_vehicle": True}
        assert "How many people" in llm.prompts[1] and "waiting_on_answer_for" in llm.prompts[1]  # the model saw the context
        assert c.app.state.store.kv_get(f"pending:household:{JUDGE}") is None


def test_llm_failure_asks_politely_and_keeps_running(make_client):
    c, _ = make_client({"asdf": RuntimeError("API down")})
    with c:
        r = c.post("/dev/inbound", json={"role": "resident", "text": "asdf"})
        assert r.status_code == 200
        st = c.get("/state").json()
        assert st["plan_version"] == 1 and st["messages"][-1]["text"] == f"[EMBER drill] {SORRY}"


def test_operator_endurance_moves_the_plan(make_client):
    c, _ = make_client({"about 90 minutes of diesel left": ex(fact("facility_status", endurance_min=90))})
    with c:
        c.post("/dev/inbound", json={"role": "operator", "text": "about 90 minutes of diesel left"})
        st = c.get("/state").json()
        rep = [r for r in st["reports"] if r["source"] == "operator"][0]
        assert rep["facility_id"] == "mt-auburn" and rep["payload"]["set"] == {"backup_endurance_s": 5400}
        assert st["plan_version"] == 2


def test_reset_forgets_half_answered_questions(make_client):
    c, _ = make_client({"we need a wheelchair van": ex(fact("need", accessible_vehicle=True))})
    with c:
        c.post("/dev/inbound", json={"role": "resident", "text": "we need a wheelchair van"})
        assert c.app.state.store.kv_get(f"pending:household:{JUDGE}") is not None
        c.post("/dev/reset")
        assert c.app.state.store.kv_get(f"pending:household:{JUDGE}") is None


def test_chatter_does_nothing(make_client):
    c, _ = make_client({"hi": ex(fact("other"))})
    with c:
        c.post("/dev/inbound", json={"role": "resident", "text": "hi"})
        st = c.get("/state").json()
        assert st["plan_version"] == 1 and st["reports"] == [] and st["messages"][-1]["direction"] == "in"
