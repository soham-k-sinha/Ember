"""The LLM is unavailable (live 2026-10-17: the Anthropic key hit its usage limit mid-call and every turn got
"Sorry, we couldn't read that"): the keyword parser keeps a text or a call going, and nothing loops."""
import pytest

from residents import fallback
from tests.test_drill import PUTNAM, R1, Tap, drill, register, solo_bridge, text, thread_of  # noqa: F401
from tests.test_voice import OURS, say, spoken, vd  # noqa: F401
from residents.voice import WHO_WE_ARE


class Down:
    """The Anthropic API answering 400 'You have reached your specified API usage limits'."""
    script: dict = {}

    async def __call__(self, system, user):
        raise RuntimeError("Error code: 400 - You have reached your specified API usage limits.")


def kinds(t, role="resident"):
    ex = fallback.parse(t, role)
    return [(f.kind, f.people, f.mobility, f.accessible_vehicle, f.question_topic, f.road_hint) for f in (ex.facts if ex else [])]


@pytest.mark.parametrize("t,want", [
    ("yes", [("confirm", None, None, None, None, None)]),
    ("Yeah sure", [("confirm", None, None, None, None, None)]),
    ("no thanks", [("reject", None, None, None, None, None)]),
    ("done", [("done", None, None, None, None, None)]),
    ("I'm not ready", []),
    ("2 of us", [("need", 2, None, None, None, None)]),
    ("three people", [("need", 3, None, None, None, None)]),
    ("me and my mom, she uses a wheelchair", [("need", 2, True, True, None, None)]),
    ("just me", [("need", 1, None, None, None, None)]),
    ("we need a wheelchair", [("need", None, True, True, None, None)]),
    ("what's the plan?", [("question", None, None, None, "plan", None)]),
    ("how long?", [("question", None, None, None, "eta", None)]),
    ("is River St open?", [("question", None, None, None, "roads", "river st")]),
    ("River St is flooded", [("closure_report", None, None, None, None, "river st")]),
    ("is it safe to drive?", [("question", None, None, None, "safety", None)]),
    ("hello?", [("other", None, None, None, None, None)]),
    ("Please stay on the line.", []),
    ("asdf qwerty", []),
])
def test_parse(t, want):
    assert kinds(t) == want


def test_operator_status():
    [f] = fallback.parse("on backup, about 40 minutes left", "operator").facts
    assert (f.kind, f.facility_state, f.endurance_min) == ("facility_status", "backup", 40)
    [f] = fallback.parse("2 hours of fuel on the generator", "operator").facts
    assert f.endurance_min == 120


def test_a_whole_drill_by_text_without_the_llm(drill):
    c = drill
    c.app.state.intake.llm = c.app.state.locator.llm = Down()
    tap = Tap(c)
    register(c)
    text(c, R1, PUTNAM)
    assert thread_of(c, R1) is not None, tap.outs(R1)                       # placed from the text itself
    text(c, R1, "2 of us")
    assert " will pick you up at " in tap.outs(R1)[-1], tap.outs(R1)[-1]   # the offer
    text(c, R1, "yes")
    assert "Step 1 of 4" in tap.outs(R1)[-1]
    text(c, R1, "what's the plan?")
    assert "Right now: Step 1 of 4" in tap.outs(R1)[-1]
    text(c, R1, "asdf qwerty")
    text(c, R1, "zxcv")
    a, b = tap.outs(R1)[-2:]
    assert a.startswith("Sorry, I didn't catch that.") and b != a, (a, b)  # never the same apology twice
    assert not any("couldn't read that" in x for x in tap.outs(R1))


def test_unreadable_before_details_repeats_the_plans_question(drill):
    c = drill
    c.app.state.intake.llm = c.app.state.locator.llm = Down()
    tap = Tap(c)
    register(c)
    text(c, R1, PUTNAM)
    text(c, R1, "mmm")
    assert tap.outs(R1)[-1] == "Sorry, I didn't catch that. How many people are with you, and does anyone need a wheelchair-accessible vehicle?"


def test_call_screening_gets_who_and_why_and_changes_nothing(vd):
    register(vd, R1)
    assert spoken(say(vd, "Hi, if you record your name and reason for calling, I'll see if this person is available.")) == WHO_WE_ARE
    assert spoken(say(vd, "Please stay on the line.")) == WHO_WE_ARE
    assert vd.app.state.store.phone(handle=R1)["thread_key"] is None   # the screening didn't place or tell anyone anything
    assert vd.app.state.messenger.lobby_log(R1) == []                   # not stored as something the resident said


def test_our_own_echo_is_ignored_but_the_caller_never_is(vd):
    c = vd
    c.app.state.intake.llm = c.app.state.locator.llm = Down()
    register(c, R1)
    first = spoken(say(c, PUTNAM))
    assert first.startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
    assert spoken(say(c, first)) == ""                                   # our words coming back: silence
    offer = spoken(say(c, "Got it, you have me at Putnam Avenue and Western Avenue. 2 of us"))  # an answer in it
    assert " will pick you up at " in offer, offer
