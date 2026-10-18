"""The LLM is unavailable (live 2026-10-17: the Anthropic key hit its usage limit mid-call and every turn got
"Sorry, we couldn't read that"): the keyword parser keeps a text or a call going, and nothing loops."""
import pytest

from residents import fallback
from tests.helpers import PUTNAM, R1, Tap, register, text, thread_of


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
    ("Oh. Yes, yes please.", [("confirm", None, None, None, None, None)]),           # heard on calls (D80)
    ("Oh, okay. What changed?", [("question", None, None, None, "plan", None)]),     # a nod, then a question
    ("no thanks", [("reject", None, None, None, None, None)]),
    ("We're on the second floor, we'll be okay.", [("question", None, None, None, "safety", None)]),  # not a decline
    ("done", [("done", None, None, None, None, None)]),
    ("We're outside.", [("done", None, None, None, None, None)]),                   # "Tell me when you're outside."
    ("I'm not ready", []),
    ("2 of us", [("need", 2, None, None, None, None)]),
    ("three people", [("need", 3, None, None, None, None)]),
    ("me and my mom, she uses a wheelchair", [("need", 2, True, True, None, None)]),
    ("just me", [("need", 1, None, None, None, None)]),
    ("we need a wheelchair", [("need", None, True, True, None, None)]),
    ("I'm stuck in my house and I can't get out", [("need", None, True, None, None, None)]),  # D83: was 2 people
    ("we need an accessible vehicle", [("need", None, True, True, None, None)]),  # D83: was dropped
    ("what's the plan?", [("question", None, None, None, "plan", None)]),
    ("how long?", [("question", None, None, None, "eta", None)]),
    ("is River St open?", [("question", None, None, None, "roads", "river st")]),
    ("River St is flooded", [("closure_report", None, None, None, None, "river st")]),
    ("is it safe to drive?", [("question", None, None, None, "safety", None)]),
    ("the water is at our door, please hurry", [("urgent", None, None, None, None, None)]),   # D92: was "didn't catch that"
    ("We're flooding inside!", [("urgent", None, None, None, None, None)]),
    ("we're trapped, 3 of us", [("need", 3, None, None, None, None), ("urgent", None, None, None, None, None)]),
    ("help", [("urgent", None, None, None, None, None)]),
    ("Yes. Yes, please hurry.", [("confirm", None, None, None, None, None)]),        # a yes, said urgently
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

