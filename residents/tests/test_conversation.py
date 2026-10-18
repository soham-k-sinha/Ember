"""Regression: the first real-phone run-through (2026-10-17), replayed with the model's actual outputs.

Live, the judge said "2 of us, my mom uses a wheelchair", then later "Yes, 2 people"; the second need
replaced the first, the wheelchair was dropped, and the non-accessible passenger truck
was assigned (then "Generator truck", now "Utility truck").
Also: no reply after the first fact (the plan couldn't serve them yet), and chatter got generic prompts."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.extract import Extraction, Fact, to_outcome
from tests.test_engine import JUDGE, SCENARIO, bridge, full_bridge  # noqa: F401
from tests.test_extract import FakeLLM, ex, fact

JT = {"household_id": JUDGE}
ACCESSIBLE = {"van-3"}  # the scenario's only wheelchair-accessible vehicle

LIVE = {  # what claude-opus-5-5 returned for each text
    "Hi": ex(fact("other"), q="Hi, do you need a pickup, and if so, how many people?"),
    "2 of us, my mom uses a wheelchair": ex(fact("need", people=2, mobility=True, accessible_vehicle=True)),
    "Hello?": ex(fact("other"), q="Hi, this is EMBER. Do you need a pickup, and if so, how many people?"),
    "Yes, 2 people": ex(fact("need", people=2)),
    "Yes": ex(fact("confirm")),
}


@pytest.fixture
def judge_phone(settings, bridge):  # noqa: F811
    s = replace(settings, scenario=SCENARIO, extract_enabled=True)
    with TestClient(create_app(s, bridge=bridge, llm=FakeLLM(LIVE))) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        c.post("/clock", json={"t_s": 3000})
        yield c


def say(c, text):
    n = len([m for m in c.get("/state").json()["messages"] if m["thread"] == JT])
    c.post("/dev/inbound", json={"role": "resident", "text": text})
    new = [m for m in c.get("/state").json()["messages"] if m["thread"] == JT][n:]
    return [m["text"] for m in new if m["direction"] == "out"]


def judge(c):
    return next(h for h in c.get("/state").json()["households"] if h["household_id"] == JUDGE)


def test_partial_need_keeps_what_we_knew():
    o = to_outcome(Extraction(facts=[Fact(kind="need", people=2, mobility=None, accessible_vehicle=None, medical=None,
                                          road_hint=None, cross_street=None, address=None, endurance_min=None, facility_state=None, question_topic=None)],
                              confidence=0.9, clarifying_question=None),
                   role="resident", thread=JT, text="Yes, 2 people", pending=None, resolve_road=lambda *a: [],
                   last_assignment_id=None, known_needs={"people": 2, "mobility": True, "accessible_vehicle": True})
    assert o.reports[0]["payload"] == {"people": 2, "mobility": True, "accessible_vehicle": True}
    # an explicit correction still wins
    o = to_outcome(Extraction(facts=[Fact(kind="need", people=3, mobility=False, accessible_vehicle=False, medical=None,
                                          road_hint=None, cross_street=None, address=None, endurance_min=None, facility_state=None, question_topic=None)],
                              confidence=0.9, clarifying_question=None),
                   role="resident", thread=JT, text="actually 3, nobody needs a wheelchair", pending=None,
                   resolve_road=lambda *a: [], last_assignment_id=None, known_needs={"people": 2, "accessible_vehicle": True})
    assert o.reports[0]["payload"] == {"people": 3, "mobility": False, "accessible_vehicle": False}


def test_live_conversation_replayed(judge_phone):
    c = judge_phone
    q = next(q for q in c.get("/state").json()["plan"]["info_requests"] if q["to"] == JT)

    # 1. "Hi" → the plan's own question (people + wheelchair), not the model's generic prompt
    assert say(c, "Hi") == [f"[EMBER drill] {q['question']}"]

    # 2. the fact → a replan AND a reply, whatever the plan could do for them
    replies = say(c, "2 of us, my mom uses a wheelchair")
    assert c.get("/state").json()["plan_version"] == 2 and len(replies) >= 1
    assert any(r.startswith("[EMBER drill] Got it. We have your details (2 people, wheelchair-accessible vehicle)")
               or "Accessible Van 3 will pick you up" in r for r in replies)

    # 3. "Hello?" → where they stand, not "do you need a pickup?" again
    [r] = say(c, "Hello?")
    assert "Do you need a pickup" not in r and ("2 people, wheelchair-accessible vehicle" in r or "Accessible Van 3" in r)

    # 4. "Yes, 2 people" must not erase the wheelchair, and no non-accessible vehicle may take them
    say(c, "Yes, 2 people")
    assert judge(c)["needs"] == {"people": 2, "mobility": True, "accessible_vehicle": True}
    st = c.get("/state").json()
    mine = [a for a in st["plan"]["assignments"] if a["target"] == JT and a["status"] not in ("cancelled", "rejected")]
    assert all(a["resource_id"] in ACCESSIBLE for a in mine), [a["resource_id"] for a in mine]


def test_every_fact_gets_a_reply_even_when_nothing_changed(judge_phone):
    c = judge_phone
    say(c, "2 of us, my mom uses a wheelchair")
    replies = say(c, "Yes, 2 people")            # same need again: plan may not change for them
    assert len(replies) == 1 and replies[0].startswith("[EMBER drill] ")


def test_question_goes_to_coordinators_with_status(settings, bridge):  # noqa: F811
    llm = FakeLLM({"2 of us, my mom uses a wheelchair": LIVE["2 of us, my mom uses a wheelchair"],
                   "is the western ave bridge open?": ex(fact("question"))})
    s = replace(settings, scenario=SCENARIO, extract_enabled=True)
    with TestClient(create_app(s, bridge=bridge, llm=llm)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        say(c, "2 of us, my mom uses a wheelchair")
        [r] = say(c, "is the western ave bridge open?")  # no topic → `other`: queued, and never only that (D60)
        assert r.startswith("[EMBER drill] Our plan doesn't cover that, so we've passed your question to a "
                            "coordinator, who will reply here. Meanwhile, here's where you stand: "), r
        assert c.get("/questions").json()[0]["text"] == "is the western ave bridge open?"


def test_tuned_demo_beat_through_the_text_pipeline(settings, full_bridge):  # noqa: F811
    """Engine's judge beat (engine/tests/test_demo_beats.py), but starting from the judge's TEXT: at minute 5
    "2 of us, my mom's in a wheelchair, River St is blocked" → one replan → the judge gets the accessible van
    before the deadline AND the generator plan changes; the judge is texted the instruction."""
    text = "2 of us, my mom's in a wheelchair, River St is blocked"
    llm = FakeLLM({text: ex(fact("need", people=2, mobility=True, accessible_vehicle=True),
                            fact("closure_report", road_hint="River St"))})
    s = replace(settings, scenario=SCENARIO, extract_enabled=True)
    with TestClient(create_app(s, bridge=full_bridge, llm=llm)) as c:
        c.post("/phones", json={"role": "resident", "handle": "6175550120"})
        c.post("/clock", json={"t_s": 300})
        v1 = c.get("/plan/1").json()
        replies = say(c, text)
        st = c.get("/state").json()
        assert st["plan_version"] == 2
        v2 = c.get("/plan/2").json()
        mine = [a for a in v2["assignments"] if a["target"] == JT and a.get("status") not in ("cancelled", "rejected")]
        assert mine and mine[0]["resource_id"] in ACCESSIBLE and mine[0]["eta_s"] <= mine[0]["deadline_s"]
        gb = {a["id"]: a["eta_s"] for a in v1["assignments"] if a["task"] == "protect"}
        ga = {a["id"]: a["eta_s"] for a in v2["assignments"] if a["task"] == "protect"}
        assert set(ga) != set(gb) or any(abs(ga.get(i, 1e9) - e) > 120 for i, e in gb.items())
        assert any("Accessible Van 3 will pick you up" in r for r in replies)
        closure = next(r for r in st["reports"] if r["kind"] == "closure_report")
        assert len(closure["payload"]["edge_ids"]) <= 4
