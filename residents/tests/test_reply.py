"""The AI talks, the planner decides (D63). Each inbound turn's computed messages are still the record (offers,
YES/NO bookkeeping, steps); the person gets one natural reply written from them, which a deterministic guard checks
(no invented numbers, vehicles, streets, safety claims; every ask kept). Anything the guard rejects → the computed
messages go out as before. Replays Soham's 2026-10-17 call, where "No, I'm stuck in my house and can't get out"
declined three vans in a row."""
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.reply import check
from tests.test_drill import PUTNAM, R1, SCENARIO, SCRIPT, Tap, register, solo_bridge, text, thread_of  # noqa: F401
from tests.test_extract import FakeLLM, ex, fact

NAMES = ["Van 1", "Van 2", "Accessible Van 3", "Generator truck", "David Rubenstein Treehouse (drill shelter)"]
OFFER = ("[EMBER drill] Van 2 will pick you up at the corner of Putnam Avenue and Western Avenue in about 3 min and take "
         "you to David Rubenstein Treehouse (drill shelter). Reply YES to confirm, or tell us what changed. (plan v3)")


# ---------- the guard ----------
@pytest.mark.parametrize("reply,ok,why", [
    ("Thanks. Van 2 will pick you up at the corner of Putnam Avenue and Western Avenue in about 3 min and take you to "
     "David Rubenstein Treehouse (drill shelter). Reply YES to confirm.", True, ""),
    ("Van 2 is the only one coming; it'll be there in about 3 min. Reply YES to confirm.", True, ""),
    ("Van 2 will be there in about 5 min. Reply YES to confirm.", False, "numbers"),
    ("Van 1 will pick you up in about 3 min. Reply YES to confirm.", False, "Van 1"),
    ("Van 2 will meet you at Memorial Drive in about 3 min. Reply YES to confirm.", False, "Memorial Drive"),
    ("Van 2 will pick you up in about 3 min.", False, "YES"),
    ("Van 2 is coming in about 3 min, you're safe now. Reply YES to confirm.", False, "safe"),
    ("If it gets bad call 911. Van 2 comes in about 3 min. Reply YES to confirm.", False, "911"),
    ("", False, "empty"),
])
def test_guard(reply, ok, why):
    c = check(reply, [OFFER], "", NAMES)
    assert c.ok == ok and why in c.why, c


def test_guard_keeps_a_question():
    q = "[EMBER drill] How many people are with you, and does anyone need a wheelchair-accessible vehicle?"
    assert not check("I'm sorry you're stuck. We're getting a vehicle ready.", [q], "", NAMES).ok
    assert check("I'm sorry you're stuck. How many people are with you, and does anyone need a wheelchair?", [q], "", NAMES).ok


# ---------- one reply per turn ----------
class Writer:
    """A stand-in for Haiku: returns what the test says (or raises), and records what it was given."""

    def __init__(self, fn):
        self.fn, self.inputs = fn, []

    async def __call__(self, system, user):
        d = json.loads(user)
        self.inputs.append(d)
        r = self.fn(d)
        if isinstance(r, Exception):
            raise r
        return r


def make(settings, bridge, writer, script=None, tmp=None):
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, auto_clock=True, reply_enabled=True,
                **({"db_path": tmp} if tmp else {}))
    return TestClient(create_app(s, bridge=bridge, llm=FakeLLM({**SCRIPT, **(script or {})}), writer=writer))


def warm(d):
    """A natural rewrite that keeps every fact: 'Thanks, got it.' + the drafts, unchanged."""
    return "Thanks, got it. " + " ".join(x.replace(" (plan v", " (v") for x in d["drafts"])


def test_a_turn_gets_one_reply_and_the_record_is_unchanged(settings, solo_bridge):
    w = Writer(warm)
    with make(settings, solo_bridge, w) as c:
        tap = Tap(c)
        register(c)
        text(c, R1, PUTNAM)
        n = len(tap.outs(R1))
        text(c, R1, "2 of us")
        [reply] = tap.outs(R1)[n:]                                   # one message for the turn
        assert reply.startswith("Thanks, got it. ") and " will pick you up at " in reply
        assert w.inputs[-1]["they_said"] == "2 of us" and w.inputs[-1]["conversation_so_far"]
        key = f"household:{thread_of(c, R1)['household_id']}"
        conv = c.app.state.store.conversation(key)
        assert conv[-1]["text"] == reply                             # the conversation shows what they got
        text(c, R1, "yes")                                           # bookkeeping intact: the offer was offered
        assert any("Step 1 of 4" in x for x in tap.outs(R1)[-1:]), tap.outs(R1)[-1]


def test_a_rejected_reply_falls_back_to_the_computed_messages(settings, solo_bridge):
    w = Writer(lambda d: "Van 1 will be there in 2 minutes, you're safe.")   # invents a vehicle, a time, a claim
    with make(settings, solo_bridge, w) as c:
        tap = Tap(c)
        register(c)
        text(c, R1, PUTNAM)
        assert tap.outs(R1)[0].startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
        assert tap.outs(R1)[1].startswith("How many people are with you")
        assert not any("you're safe" in x for x in tap.outs(R1))


def test_writer_down_falls_back(settings, solo_bridge):
    with make(settings, solo_bridge, Writer(lambda d: RuntimeError("usage limit"))) as c:
        tap = Tap(c)
        register(c)
        text(c, R1, PUTNAM)
        text(c, R1, "2 of us")
        assert " will pick you up at " in tap.outs(R1)[-1]


def test_understanding_sees_the_conversation(settings, solo_bridge):
    with make(settings, solo_bridge, Writer(warm)) as c:
        register(c)
        text(c, R1, PUTNAM)
        text(c, R1, "2 of us")
        prompt = c.app.state.intake.llm.prompts[-1]
        ctx = json.loads(prompt.split("Context:\n", 1)[1].split("\n\nMessage:", 1)[0])
        assert any(h["from"] == "EMBER" and "How many people" in h["text"] for h in ctx["conversation_so_far"]), ctx
        assert ctx["conversation_so_far"][-1]["from"] == "EMBER"   # the message itself isn't repeated as history


# ---------- the 2026-10-17 call ----------
STUCK = "No, uh, that's not okay because I'm currently stuck in my house and I can't get out."
LEG = "No, um, actually, I'm injured right now. I've got, like, I've got a broken leg. I can't walk, so I can't make it out of the house."
CALL = {  # what the understanding step should return for these (live: tests/samples.json, scripts/eval_extract.py)
    "Um, we are three people.": ex(fact("need", people=3)),
    STUCK: ex(fact("need", mobility=True)),
    LEG: ex(fact("need", mobility=True, medical=True)),
}


def test_stuck_at_home_is_a_door_pickup_not_a_decline(settings, solo_bridge, tmp_path):
    with make(settings, solo_bridge, Writer(warm), CALL, tmp_path / "x.db") as c:
        tap = Tap(c)
        register(c)
        text(c, R1, PUTNAM)
        text(c, R1, "Um, we are three people.")
        assert "Van 2" in tap.outs(R1)[-1] or "Van 1" in tap.outs(R1)[-1]
        text(c, R1, STUCK)
        last = tap.outs(R1)[-1]
        assert "Accessible Van 3" in last and "at your door" in last, last
        text(c, R1, LEG)
        t = thread_of(c, R1)
        assert c.app.state.store.kv_get(f"rejected:household:{t['household_id']}") in (None, "[]")  # nothing declined
        reports = [r for r in c.get("/state").json()["reports"] if r.get("household_id") == t["household_id"]]
        assert not any(r["kind"] == "reject" for r in reports)
        h = next(x for x in c.get("/state").json()["households"] if x["household_id"] == t["household_id"])
        assert h["needs"]["people"] == 3 and h["needs"]["mobility"] is True and h["needs"]["medical"] is True


def test_a_bare_yes_to_an_offer_needs_no_model(settings, solo_bridge):
    with make(settings, solo_bridge, Writer(warm)) as c:
        tap = Tap(c)
        register(c)
        text(c, R1, "yes")                       # nothing offered yet: an ordinary turn (the model reads it)
        n_prompts = len(c.app.state.intake.llm.prompts) + len(c.app.state.locator.llm.prompts)
        assert n_prompts >= 1
        text(c, R1, PUTNAM)
        text(c, R1, "2 of us")
        before = len(c.app.state.intake.llm.prompts)
        text(c, R1, "Yes.")
        assert len(c.app.state.intake.llm.prompts) == before    # no model call
        assert "Step 1 of 4" in tap.outs(R1)[-1]


def test_over_photon_a_turn_is_one_imessage(settings, solo_bridge, monkeypatch):
    from tests.fake_photon import FakePhoton, received
    from tests.test_messaging import deliver

    async def no_wait(*a):
        pass
    monkeypatch.setattr("residents.photon._backoff", no_wait)
    fp = FakePhoton()
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, auto_clock=True, reply_enabled=True,
                photon_enabled=True, photon_listen=False)
    with TestClient(create_app(s, photon_client=fp.client(), bridge=solo_bridge, llm=FakeLLM(SCRIPT), writer=Writer(warm))) as c:
        register(c)
        deliver(c, received("m-1", R1, "hi"))
        n = len(fp.sends())
        deliver(c, received("m-2", R1, PUTNAM))
        sends = fp.sends()[n:]
        assert len(sends) == 1, [x["content"]["text"] for x in sends]          # placed + the plan's question: one text
        t = sends[0]["content"]["text"]
        assert t.startswith("[EMBER drill] Thanks, got it. ") and "How many people" in t
        n = len(fp.sends())
        deliver(c, received("m-3", R1, "2 of us"))
        [offer] = fp.sends()[n:]
        assert " will pick you up at " in offer["content"]["text"]
        deliver(c, received("m-4", R1, "yes"))
        assert "Step 1 of 4" in fp.sends()[-1]["content"]["text"]               # the YES confirmed the real offer
