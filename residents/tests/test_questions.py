"""Every question gets an answer from the plan (D60). Live 2026-10-17: a resident at 125 Western Ave (outside the
flood, details not given yet) asked "what's the plan?" and "what to do?" and got only "We've passed your question to
the coordinators." Now: a topic's own answer (briefing.py), else the person's whole situation (Outbound.situation);
a question the plan can't cover also lands on the coordinators' queue (GET /questions), never instead of an answer."""
import argparse

import pytest

from residents.briefing import BRING, SAFETY, TOPICS
from residents.drill import Drill
from residents.intake import ESCALATED
from tests.helpers import GREEN, PUTNAM, R1, R2, Tap, clock, ex, fact, outcome, place, register, text, thread_of

BARE = "We've passed your question to the coordinators."
ASKS = "Please tell us: How many people are with you"
Q = {
    "what's the plan?": ex(fact("question", question_topic="plan"), confidence=0.75),
    "what to do?": ex(fact("question", question_topic="plan"), confidence=0.75),
    "what now?": ex(fact("question", question_topic="other")),         # if the model calls it `other`
    "how long until pickup?": ex(fact("question", question_topic="eta")),
    "where do I go?": ex(fact("question", question_topic="pickup_place")),
    "where will you take us?": ex(fact("question", question_topic="destination")),
    "where is the flood happening": ex(fact("question", question_topic="flood")),
    "is River St open?": ex(fact("question", question_topic="roads", road_hint="River St")),
    "is Western Ave open at Putnam?": ex(fact("question", question_topic="roads", road_hint="Western Ave",
                                              cross_street="Putnam Ave")),
    "is River St open at Putnam?": ex(fact("question", question_topic="roads", road_hint="River St",
                                           cross_street="Putnam Ave")),
    "is Elm Alley open?": ex(fact("question", question_topic="roads", road_hint="Elm Alley")),
    "are the roads ok?": ex(fact("question", question_topic="roads")),
    "is it safe to drive?": ex(fact("question", question_topic="safety")),
    "can I bring my cat?": ex(fact("question", question_topic="other")),
    "when, and where do we go?": ex(fact("question", question_topic="eta"), fact("question", question_topic="pickup_place")),
    "what now and can I bring my cat?": ex(fact("question", question_topic="plan"), fact("question", question_topic="other")),
    "2 of us, what should we bring?": ex(fact("need", people=2), fact("question", question_topic="bring")),
    "we need a wheelchair, how long?": ex(fact("need", mobility=True, accessible_vehicle=True),
                                         fact("question", question_topic="eta")),
    "what's going on?": ex(fact("question", question_topic="plan")),
}
TOPIC_TEXT = {"plan": "what's the plan?", "eta": "how long until pickup?", "pickup_place": "where do I go?",
              "destination": "where will you take us?", "others": "is anyone near me?", "vehicles": "are there other vans?",
              "bring": "what should we bring?", "flood": "where is the flood happening", "roads": "is River St open?",
              "safety": "is it safe to drive?", "other": "can I bring my cat?"}


@pytest.fixture
def qd(drill):
    for k, t in TOPIC_TEXT.items():
        Q.setdefault(t, ex(fact("question", question_topic=k)))
    for h in (drill.app.state.intake.llm, drill.app.state.locator.llm):
        h.script.update(Q)
        h.script["2 of us"] = ex(fact("need", people=2))
        h.script["yes"] = ex(fact("confirm"))
    return drill, Tap(drill)


def ask(c, tap, msg, handle=R1):
    n = len(tap.outs(handle))
    text(c, handle, msg)
    new = tap.outs(handle)[n:]
    assert new, f"no reply to {msg!r}"
    return new


# ---------- the live transcript ----------
def test_whats_the_plan_outside_the_flood_before_details(qd):
    """The 2026-10-17 transcript: placed outside the flood, asked the plan's question, then 'what's the plan?'."""
    c, tap = qd
    register(c)
    place(c, tap, R1, GREEN)
    assert tap.outs(R1)[-1].startswith("How many people are with you")
    for msg in ("what's the plan?", "what to do?"):
        [r] = ask(c, tap, msg)
        assert BARE not in r and r.startswith("Your street is outside this drill's forecast flood area, so no pickup is "
                                              "planned: stay where you are, above the ground floor if you can."), r
        assert ASKS in r and r.endswith("(plan v2)"), r


def test_a_vague_question_labelled_other_still_gets_the_situation_and_reaches_a_coordinator(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, GREEN)
    [r] = ask(c, tap, "what now?")
    assert r.startswith(ESCALATED + " Meanwhile, here's where you stand: Your street is outside"), r
    assert ASKS in r
    [q] = c.get("/questions").json()
    assert q["text"] == "what now?" and q["handle"] == R1 and q["thread"] == thread_of(c, R1) and q["answer"] is None


# ---------- the situation in each state ----------
def test_in_the_flood_before_details_says_when_the_water_comes(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    [r] = ask(c, tap, "what's the plan?")
    assert r.startswith("In this drill's flood forecast, water reaches your street in about "), r
    assert "so we're planning to pick you up; we need a few details" in r and ASKS in r


def test_offered_then_confirmed_then_on_a_step(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    text(c, R1, "2 of us")
    [r] = ask(c, tap, "what's the plan?")
    assert " is assigned to pick you up, arriving " in r and "Reply YES to confirm." in r and "Please tell us" not in r, r
    text(c, R1, "yes")
    [r] = ask(c, tap, "what to do?")
    assert r.startswith("Your pickup is confirmed: ") and " Right now: Step 1 of 4: Pack medications" in r, r
    assert "Confirmed:" not in r.split("Right now:")[1]  # step 1 without its "Confirmed: …" lead
    assert r.count("(plan v") == 1 and r.endswith(")")
    text(c, R1, "done")          # auto clock: the vehicle arrives, step 2 is texted
    [r] = ask(c, tap, "what's the plan?")
    assert " Right now: Step 2 of 4: " in r and "Reply DONE once everyone is aboard" in r, r


def test_eta_before_any_vehicle_is_the_situation_not_the_coordinators(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    for msg in ("how long until pickup?", "where do I go?"):
        [r] = ask(c, tap, msg)
        assert r.startswith("In this drill's flood forecast") and ASKS in r, (msg, r)
    assert ask(c, tap, "where will you take us?") == [  # the shelter, then what we still need to know
        "Everyone we pick up goes to David Rubenstein Treehouse (drill shelter). How many people are with you, and does "
        "anyone need a wheelchair-accessible vehicle?"]
    assert c.get("/questions").json() == []  # answered: nothing for a coordinator


# ---------- flood, roads, safety ----------
def test_flood_question(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, GREEN)
    [r] = ask(c, tap, "where is the flood happening")
    assert r.startswith("Your street is outside this drill's forecast flood area. The river flood reaches these "
                        "corners first: Flagg Street and Memorial Drive (in about "), r
    register(c, R2)
    place(c, tap, R2, PUTNAM)
    [r] = ask(c, tap, "where is the flood happening", R2)
    assert r.startswith("In this drill's flood forecast, water reaches your street in about "), r


def test_roads_questions(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, GREEN)
    [r] = ask(c, tap, "is River St open?")
    assert r.startswith("River Street is open right now."), r
    [r] = ask(c, tap, "are the roads ok?")
    assert r == "No roads are closed in the current picture. Vehicles are routed around closed roads.", r
    edges = c.app.state.planner.bridge.resolve_road("River St", "Memorial Dr", None)
    assert edges and c.post("/disruption", json={"close_edges": edges}).status_code == 200
    [r] = ask(c, tap, "is River St open?")
    assert r.startswith("River Street is closed near the corner of ") and "Memorial Drive" in r, r
    assert r.endswith("flooded or reported blocked. Vehicles are routed around it.")
    [r] = ask(c, tap, "is River St open at Putnam?")  # the closed stretch is at Memorial Dr, not here
    assert r.startswith("River Street at Putnam Ave is open right now."), r
    [r] = ask(c, tap, "are the roads ok?")
    assert r.startswith("Closed right now: ") and "River Street" in r, r
    [r] = ask(c, tap, "is Western Ave open at Putnam?")
    assert r.startswith("Western Avenue at Putnam Ave is open right now."), r
    [r] = ask(c, tap, "is Elm Alley open?")
    assert r.startswith('We couldn\'t find "Elm Alley" on our map. Closed right now: '), r


def test_safety_and_bring_are_the_fixed_wording(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    assert ask(c, tap, "is it safe to drive?") == [SAFETY]
    assert SAFETY.startswith("In a real emergency, call 911.")
    assert ask(c, tap, "what should we bring?") == [BRING]


# ---------- several topics, questions with facts ----------
def test_two_topics_falling_back_send_the_situation_once(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    [r] = ask(c, tap, "when, and where do we go?")  # no vehicle yet: both fall back to the same answer
    assert r.startswith("In this drill's flood forecast")
    new = ask(c, tap, "what now and can I bring my cat?")
    assert len(new) == 1 and new[0].startswith("In this drill's flood forecast"), new  # plan first, cat → queue only
    assert [q["text"] for q in c.get("/questions").json()] == ["what now and can I bring my cat?"]


def test_a_need_with_a_question_gets_the_offer_and_the_answer(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    new = ask(c, tap, "2 of us, what should we bring?")
    assert " will pick you up at " in new[0] and new[-1] == BRING, new


def test_missing_details_with_a_question_asks_once(qd):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    new = ask(c, tap, "we need a wheelchair, how long?")
    assert new == ["How many people need to be picked up, including you?"], new  # not the situation's question too


# ---------- shared trips (engine D59) ----------
def test_neighbours_who_fit_one_van_hear_they_share_the_trip(qd):
    """Two 2-person wheelchair households at one corner both need the only accessible van; 4 people fit its 6 seats,
    so the engine chains the second pickup before the drop-off. The texts must say so (it used to say "one
    household per trip")."""
    from tests.test_drill import NEIGHBORS, STADIUM
    c, tap = qd
    for h in (c.app.state.intake.llm, c.app.state.locator.llm):
        h.script.update(NEIGHBORS)
        h.script["me and my dad, he uses a wheelchair"] = ex(fact("need", people=2, mobility=True, accessible_vehicle=True))
        h.script["is anyone near me?"] = ex(fact("question", question_topic="others"))
    for h in (R1, R2):
        register(c, h)
    place(c, tap, R2, STADIUM)
    place(c, tap, R1, STADIUM)
    text(c, R2, "me and my dad, he uses a wheelchair")
    text(c, R1, "me and my dad, he uses a wheelchair")
    q = [a for a in c.get("/plan/current").json()["assignments"] if a["resource_id"] == "van-3" and a["task"] == "rescue"]
    assert len(q) == 2 and any("shares the trip with household #" in a["rationale"] for a in q), [a["rationale"] for a in q]
    offers = [next(x for x in reversed(tap.outs(h)) if "will pick you up" in x) for h in (R1, R2)]
    assert any("you share the trip with 1 other household: it collects you both before the drop-off." in o for o in offers), offers
    for h in (R1, R2):
        [r] = ask(c, tap, "is anyone near me?", h)
        assert "and you share the trip with it: Accessible Van 3 collects you both before the drop-off." in r, r
        assert "separate" not in r and "one household per trip" not in r


# ---------- the coordinators' queue ----------
def test_coordinator_answers_from_the_api_and_the_console(qd, capsys):
    c, tap = qd
    register(c)
    place(c, tap, R1, PUTNAM)
    d = Drill(argparse.Namespace(dry=True, crowded=False, keep=False, manual_clock=False, port=0, db="x.db",
                                 resident=[R1], operator=[]))
    d.app, d.names = c.app, {R1: "r1"}
    c.app.state.intake.escalation_hooks.append(d.on_question)
    ask(c, tap, "can I bring my cat?")
    assert "tell r1 <text>" in capsys.readouterr().out
    [q] = c.get("/questions?open_only=true").json()
    r = c.post(f"/questions/{q['report_id']}/answer", json={"text": "Yes, in a carrier."})
    assert r.status_code == 200 and r.json()["delivery"] == "dev"
    assert tap.outs(R1)[-1] == "Yes, in a carrier."
    assert c.get("/questions?open_only=true").json() == [] and c.get("/questions").json()[0]["answer"]["text"] == "Yes, in a carrier."
    assert c.post("/questions/r-nope/answer", json={"text": "x"}).status_code == 404
    ask(c, tap, "can I bring my cat?")
    c.portal.call(d.command, "questions")
    assert "(open)" in capsys.readouterr().out
    c.portal.call(d.command, "tell r1 Cats are fine.")
    assert tap.outs(R1)[-1] == "Cats are fine." and all(x["answer"] for x in c.get("/questions").json())
    c.post("/dev/reset")
    assert c.get("/questions").json() == []  # per run


# ---------- the lobby ----------
def test_a_question_before_a_location_says_why_we_need_it(qd):
    c, tap = qd
    register(c)
    [r] = ask(c, tap, "what's going on?")
    assert r.startswith("We can tell you exactly what to do once we know where you are. ") and "Where are you" in r, r
    assert thread_of(c, R1) is None


# ---------- the invariant ----------
@pytest.mark.parametrize("where", [GREEN, PUTNAM])
def test_every_topic_in_every_state_gets_a_real_answer(qd, where):
    """No question, in any state, gets silence or only "passed to the coordinators"."""
    c, tap = qd
    register(c)
    place(c, tap, R1, where)
    for stage in ("no details", "offered", "confirmed"):
        if stage == "offered":
            text(c, R1, "2 of us")
        if stage == "confirmed":
            text(c, R1, "yes")
        for topic in TOPICS:
            new = ask(c, tap, TOPIC_TEXT[topic])
            assert all(r.strip() and r.strip() != BARE for r in new), (where, stage, topic, new)
            # handing it to a coordinator is never the whole answer
            assert all("here's where you stand: " in r for r in new if r.startswith(ESCALATED)), (where, stage, topic, new)
    assert clock(c) == 0.0  # questions never move the clock


def test_roads_question_carries_the_street():
    o = outcome(ex(fact("question", question_topic="roads", road_hint="River St", cross_street="Memorial Dr")))
    assert o.topics == ["roads"] and o.road == {"road_hint": "River St", "cross_street": "Memorial Dr"}
    assert outcome(ex(fact("question", question_topic="roads"))).road is None
    assert outcome(ex(fact("question", question_topic="eta", road_hint="River St"))).road is None
