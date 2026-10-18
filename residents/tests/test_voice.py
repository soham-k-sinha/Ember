"""Phone calls (D74): ElevenLabs runs the call, our backend is its Custom LLM. What a caller says goes through the
same path as a text; what the thread would text is said on the call instead. No network: ElevenLabs is faked at
the HTTP layer, the voice app is driven in the backend's own event loop (as in the drill, one process)."""
import argparse
import json
import re

import httpx
import pytest

from residents import voice as voice_mod
from residents.drill import Drill
from residents.speech import render, render_all
from residents.voice import (CALM, INBOUND, OPENER, PROMISE, SYSTEM_PROMPT, WHERE, WHO_WE_ARE, configure_agent,
                             create_voice_app)
from tests.helpers import GREEN, PUTNAM, R1, R2, Tap, ex, fact, make, register, text, thread_of

OURS = "+16175550199"           # the Photon voice number (placeholder)
TOKEN = "t0k"


def sys_prompt(caller, called=OURS, conv="conv_1"):
    return SYSTEM_PROMPT.replace("{{system__caller_id}}", caller).replace("{{system__called_number}}", called) \
        .replace("{{system__conversation_id}}", conv)


@pytest.fixture
def vd(drill):
    from dataclasses import replace
    v = drill.app.state.voice
    v.settings = replace(v.settings, photon_voice_number=OURS, elevenlabs_api_key="k", elevenlabs_agent_id="agent_1",
                         elevenlabs_phone_number_id="phnum_1")
    drill.seen = []  # configured, so EMBER may call on its own (D80): never the real ElevenLabs
    v.http = fake_eleven(drill.seen, [])
    for h in (drill.app.state.intake.llm, drill.app.state.locator.llm):
        h.script["what's the plan?"] = ex(fact("question", question_topic="plan"))
    return drill


def say(c, words, caller=R1, called=OURS, stream=False, token=TOKEN, conv="conv_1"):
    """One caller turn through the voice app, in the backend's event loop. Returns the HTTP response."""
    vapp = create_voice_app(lambda: c.app.state.voice, TOKEN)
    body = {"model": "ember", "stream": stream,
            "messages": [{"role": "system", "content": sys_prompt(caller, called, conv)},
                         {"role": "assistant", "content": "Hi, this is EMBER"},
                         {"role": "user", "content": words}]}

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=vapp), base_url="http://v") as cl:
            return await cl.post(f"/{token}/v1/chat/completions", json=body)
    return c.portal.call(go)


def spoken(r) -> str:
    if r.headers["content-type"].startswith("text/event-stream"):
        parts = [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: {")]
        assert r.text.rstrip().endswith("data: [DONE]")
        return "".join(p["choices"][0]["delta"].get("content", "") for p in parts)
    return r.json()["choices"][0]["message"]["content"]


# ---------- speech ----------
@pytest.mark.parametrize("text,want", [
    ("[EMBER drill] Van 2 will pick you up in about 12 min. Reply YES to confirm, or tell us what changed. (plan v3)",
     "Van 2 will pick you up in about 12 minutes. Can you be ready?"),
    ("Walk to the corner of Putnam Ave and N Harvard St, about 120 m north of you (about 1 min on foot). Reply DONE when you're there.",
     "Walk to the corner of Putnam Avenue and North Harvard Street, about 120 meters north of you (about 1 minute on foot). Tell me when you're outside."),
    ("Welcome to the EMBER flood drill. Where are you right now? Reply with your street address (e.g. 125 Western Ave) "
     "or the nearest intersection.", "Where are you right now? Tell me your street address or the nearest intersection."),
    ("Van 2 will pick you up at the corner of Memorial Drive and River St in about 64 min and take you to the Treehouse. "
     "Plan to be out within about 110 min, before the water reaches your street. It picks up 8 other households first; "
     "you share the trip with 1 other household: it collects you both before the drop-off. Reply YES to confirm. (plan v4)",
     "Van 2 will pick you up at the corner of Memorial Drive and River Street in about 64 minutes. Can you be ready?"),
    # lists, step labels and an ETA said twice: the follow-up text has them
    ("Confirmed: Van 2 is coming to you. Step 1 of 4: Pack medications, ID, your phone and charger, then go out to "
     "Flagg Street. Van 2 gets there in about 9 min. Reply DONE when you're there.",
     "Confirmed. Go out to Flagg Street. Van 2 gets there in about 9 minutes. Tell me when you're outside."),
    ("Your pickup is confirmed: Van 2 is arriving in about 9 min. Right now: Step 1 of 4: Walk to Flagg Street. "
     "Van 2 gets there in about 9 min. Reply DONE when you're there.",
     "Your pickup is confirmed: Van 2 is arriving in about 9 minutes. Right now: Walk to Flagg Street. Tell me when you're outside."),
    ("Understood, we won't send Van 1. Reply here if you change your mind. Van 2 will pick you up in about 5 min. "
     "Reply YES to confirm.", "Understood, we won't send Van 1. Van 2 will pick you up in about 5 minutes. Can you be ready?"),
    ("Reply YES to keep it, or NO to decline anyway.", "Say yes to keep it, or no to decline anyway."),
    ("Utility truck is outside now. Reply DONE once everyone is aboard. Understood, we won't send Utility truck.",
     "The utility truck is outside now. Tell me once everyone is aboard. Understood, we won't send the utility truck."),
    ("Generator 1 is on its way to you, arriving in about 8 min. Reply YES to confirm someone will meet it.",
     "Generator 1 is on its way to you, arriving in about 8 minutes. Can someone meet it?"),
    ("Accessible Van 3 is the only wheelchair-accessible vehicle that fits 1 person; it picks up 2 other households first.",
     "Accessible Van 3 is the only wheelchair-accessible vehicle that fits 1 person."),
    ("Bring ID (and prescriptions), e.g. a charger.", "Bring ID (and prescriptions), for example, a charger."),
    ("In a real emergency, call 911.", "In a real emergency, call 9 1 1."),
    ("household #10296; overflow 9,600 m³. We'll text you if that changes. Text us if anything changes.",
     "household number 10296; overflow 9,600 cubic meters. We'll let you know if that changes. Tell us if anything changes."),
    ("Send your street address or the nearest intersection.", "Tell me your street address or the nearest intersection."),
    ("we need a few details to send the right vehicle.", "we need a few details to send the right vehicle."),
    ("Send a street address or the two nearest cross streets there.", "Tell me a street address or the two nearest cross streets there."),
])
def test_render(text, want):
    assert render(text) == want


def test_nothing_screen_only_survives():
    for t in ["[EMBER drill] x (plan v12)", "Reply NO if you'd rather stay put", "Stadium Rd and Western Ave"]:
        r = render(t)
        assert not re.search(r"\[EMBER|\(plan v|Reply|\b(Rd|Ave|St)\b", r), r


# ---------- who is calling ----------
def test_identify_the_other_end(vd):
    v = vd.app.state.voice
    register(vd, R1)
    assert v.identify(sys_prompt(R1, OURS)) == (R1, "conv_1")              # inbound: they called us
    assert v.identify(sys_prompt(OURS, R1, "c2")) == (R1, "c2")            # outbound: we called them
    assert v.identify(sys_prompt("{{system__caller_id}}", OURS)) == (None, "conv_1")
    assert v.identify("no call line") == (None, None)


# ---------- a whole call is the text conversation ----------
FLOW = [PUTNAM, "2 of us", "what's the plan?", "yes", "done", "done"]


def test_a_call_says_what_the_thread_would_text(settings, solo_bridge, tmp_path):
    """Parity: the same words by text and by call → the same replies (rendered for speech), nothing texted."""
    with make(settings, solo_bridge) as c:
        tap = Tap(c)
        register(c, R1)
        by_text = []
        for w in FLOW:
            n = len(tap.outs(R1))
            text(c, R1, w)
            by_text.append(render_all(tap.outs(R1)[n:]))
    from dataclasses import replace
    with make(replace(settings, db_path=tmp_path / "call.db"), solo_bridge) as c:
        tap = Tap(c)
        c.app.state.voice.settings = replace(c.app.state.voice.settings, photon_voice_number=OURS)
        register(c, R1)
        by_call = [spoken(say(c, w)) for w in FLOW]
        assert all(e["delivery"] == "voice" for e in tap.events if e["direction"] == "out"), tap.events
        rows = c.app.state.store.thread_messages(f"household:{thread_of(c, R1)['household_id']}")
        assert any(m["direction"] == "in" and m["text"] == "2 of us" for m in rows)  # the call is in the thread
    assert [w.replace(f" {PROMISE}", "") for w in by_call] == by_text, list(zip(FLOW, by_text, by_call))
    assert by_call[0].startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
    assert "Can you be ready?" in by_call[1] and by_call[3].startswith("Confirmed. ") and by_call[3].endswith(PROMISE)


def test_after_the_call_it_texts_again(vd):
    c = vd
    tap = Tap(c)
    register(c, R1)
    spoken(say(c, PUTNAM))
    c.app.state.voice.end(R1, reason="hung up")
    text(c, R1, "2 of us")
    outs = [e for e in tap.events if e["direction"] == "out"]
    assert outs[0]["delivery"] == "voice" and outs[-1]["delivery"] == "dev"  # back to the text thread


def test_streams_sse_with_a_filler_when_slow(vd, monkeypatch):
    register(vd, R1)
    monkeypatch.setattr(voice_mod, "FILLER_AFTER_S", 0.0)
    r = say(vd, PUTNAM, stream=True)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    words = spoken(r)
    assert words.startswith("One moment... Got it: we have you at"), words


def test_wrong_token_and_unknown_call(vd):
    assert say(vd, "hi", token="nope").status_code == 404
    r = say(vd, "hi", caller="{{system__caller_id}}", called="{{system__called_number}}")
    assert spoken(r).startswith("Sorry, I can't tell which phone this is.")


def test_an_unregistered_caller_is_asked_where_they_are(vd):
    vd.app.state.locator.llm.script["hello?"] = ex(fact("other"))
    words = spoken(say(vd, "hello?", caller=R2))
    assert "Where are you right now?" in words, words
    assert vd.app.state.store.phone(handle=R2)["role"] == "resident"
    assert spoken(say(vd, GREEN, caller=R2)).startswith("Got it: we have you at Green Street and Sellers Street.")


def test_closed_line_refuses_strangers(vd):
    from dataclasses import replace
    v = vd.app.state.voice
    v.settings = replace(v.settings, voice_admit_callers=False)
    assert spoken(say(vd, "hello?", caller=R2)).startswith("This line is for registered drill participants.")
    assert vd.app.state.store.phone(handle=R2) is None


# ---------- outbound calls through ElevenLabs ----------
def fake_eleven(seen, answers):
    def handler(req):
        seen.append((req.method, str(req.url), json.loads(req.content or b"null"), req.headers.get("xi-api-key")))
        return answers.pop(0) if answers else httpx.Response(200, json={"success": True, "conversation_id": "conv_9", "sip_call_id": "s"})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_call_opens_with_the_situation(vd):
    c = vd
    register(c, R1)
    text(c, R1, PUTNAM)
    seen = []
    c.app.state.voice.http = fake_eleven(seen, [])
    rec = c.portal.call(c.app.state.voice.call, R1)
    [(method, url, body, key)] = seen
    assert method == "POST" and url.endswith("/v1/convai/sip-trunk/outbound-call") and key == "k"
    assert body["agent_id"] == "agent_1" and body["agent_phone_number_id"] == "phnum_1" and body["to_number"] == R1
    first = body["conversation_initiation_client_data"]["conversation_config_override"]["agent"]["first_message"]
    assert first == (f"{OPENER}, calling about your evacuation plan. How many people are with you, and does anyone need "
                     f"a wheelchair-accessible vehicle?"), first  # who and why, then one question
    assert rec["conversation_id"] == "conv_9"
    [live] = c.get("/calls").json()["live"]
    assert live == {"handle": R1, "household_id": thread_of(c, R1)["household_id"], "reason": "console",
                    "started_t_s": 0.0, "turns": 0}
    # their answer on the call → the offer, said on the call
    assert "Can you be ready?" in spoken(say(c, "2 of us", caller=OURS, called=R1))


def test_call_without_override_says_the_opening_on_the_first_turn(vd):
    c = vd
    register(c, R1)
    text(c, R1, PUTNAM)
    seen = []
    c.app.state.voice.http = fake_eleven(seen, [httpx.Response(400, json={"detail": "first_message override is not allowed"})])
    c.portal.call(c.app.state.voice.call, R1)
    assert len(seen) == 2 and "conversation_config_override" not in seen[1][2]["conversation_initiation_client_data"]
    c.app.state.intake.llm.script["hello"] = ex(fact("other"))
    words = spoken(say(c, "hello", caller=OURS, called=R1))
    assert words.startswith("How many people are with you"), words  # the opening, then the reply


def test_failed_dial_is_reported_and_texts_resume(vd):
    c = vd
    register(c, R1)
    c.app.state.voice.http = fake_eleven([], [httpx.Response(422, json={"detail": [{"msg": "bad number"}]})])
    with pytest.raises(RuntimeError, match="outbound call failed"):
        c.portal.call(c.app.state.voice.call, R1)
    assert c.app.state.voice.live(R1) is None
    assert c.post("/calls", json={"handle": "+16175550177"}).status_code == 404


def test_configure_agent_keeps_the_secret_and_verifies(vd):
    s = vd.app.state.voice.settings
    agent = {"conversation_config": {"agent": {"prompt": {"llm": "custom-llm", "custom_llm": {
        "url": "https://old/v1", "model_id": "m", "api_key": {"secret_id": "sec_1"}}}}}}
    seen = []

    def handler(req):
        body = json.loads(req.content or b"null")
        seen.append((req.method, body))
        if req.method == "PATCH" and body.get("conversation_config"):
            agent["conversation_config"]["agent"]["prompt"].update(body["conversation_config"]["agent"]["prompt"])
        return httpx.Response(200, json=agent)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ok, detail = vd.portal.call(configure_agent, s, "https://new.trycloudflare.com/x/v1", http)
    assert ok, detail
    patch = next(b for m, b in seen if m == "PATCH")["conversation_config"]["agent"]["prompt"]
    assert patch["custom_llm"] == {"url": "https://new.trycloudflare.com/x/v1", "model_id": "m", "api_key": {"secret_id": "sec_1"}}
    assert patch["prompt"] == SYSTEM_PROMPT and patch["llm"] == "custom-llm"
    assert next(b for m, b in seen if m == "PATCH")["conversation_config"]["agent"]["first_message"] == INBOUND
    bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"conversation_config": {}})))
    ok, detail = vd.portal.call(configure_agent, s, "https://x/v1", bad)
    assert not ok and "still points at" in detail


# ---------- the drill calls the people in the flood zone ----------
def test_drill_calls_only_callers_in_the_flood(vd, capsys):
    c = vd
    d = Drill(argparse.Namespace(dry=True, crowded=False, keep=False, manual_clock=False, port=0, db="x.db",
                                 resident=[], operator=[], voice=True,
                                 caller=[f"{R1}=Putnam Ave and Western Ave", f"{R2}=Green St and Sellers St"]))
    d.app = c.app
    c.portal.call(d.register)
    c.portal.call(d.dial_callers)
    out = capsys.readouterr().out
    assert (f"[pretend call to r1] EMBER: {OPENER}, calling about your evacuation plan. We have you at Putnam Avenue and "
            f"Western Avenue. In this drill's flood forecast") in out, out
    assert "r2 at Green Street and Sellers Street: outside the forecast flood, so not called" in out
    assert c.app.state.voice.live(R2) is None and c.app.state.voice.live(R1) is not None
    c.portal.call(d.command, "@r1 2 of us")
    assert "[call] EMBER → r1: " in capsys.readouterr().out


# ---------- EMBER calls the most at-risk first (D80) ----------
FLAGG = "Flagg St and Memorial Dr"  # the flood reaches it first (out by 75 min); PUTNAM: out by 135 min


def dials(c) -> list[tuple[str, str]]:
    """(to, first words) of every call EMBER placed through the fake ElevenLabs."""
    return [(b["to_number"], b["conversation_initiation_client_data"]["conversation_config_override"]["agent"]["first_message"])
            for _, url, b, _ in c.seen if url.endswith("/outbound-call")]


def at(c, minutes):
    assert c.post("/clock", json={"t_s": minutes * 60.0}).status_code == 200


def deadline_min(c, handle):
    hid = thread_of(c, handle)["household_id"]
    return next(h for h in c.app.state.store.households() if h["household_id"] == hid)["deadline_s"] / 60


def test_calls_a_wheelchair_user_who_hasnt_said_yes(vd, monkeypatch):
    c = vd
    tap = Tap(c)
    register(c, R1)
    text(c, R1, PUTNAM)
    text(c, R1, "me and my dad, he uses a wheelchair")
    assert dials(c) == []  # never while they're texting us
    at(c, 2)
    [(to, first)] = dials(c)
    assert to == R1 and first.startswith(f"{OPENER}, calling about your wheelchair-accessible pickup. Accessible Van"), first
    assert first.endswith("Can you be ready?")
    assert spoken(say(c, "yes", caller=OURS, called=R1, conv="conv_9")).endswith(PROMISE)
    at(c, 4)
    assert len(dials(c)) == 1  # the call is still on
    monkeypatch.setattr(voice_mod, "REAP_EVERY_S", 0.0)
    c.app.state.voice.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "done"})))
    at(c, 5)  # ElevenLabs says it's over: the plan follows by text
    assert tap.outs(R1)[-1].startswith("As promised, here's your plan in writing. Your pickup is confirmed:")
    assert c.get("/calls").json() == {"live": [], "recent": [{
        "handle": R1, "household_id": thread_of(c, R1)["household_id"], "reason": "mobility", "outcome": "confirmed",
        "turns": 1, "ended_t_s": 300.0}]}


def test_calls_once_when_an_open_question_goes_unanswered_near_the_water(vd):
    c = vd
    tap = Tap(c)
    register(c, R1)
    text(c, R1, PUTNAM)  # asked how many people; no answer
    out_by = deadline_min(c, R1)
    at(c, out_by - 50)
    assert dials(c) == []  # the water is still far
    at(c, out_by - 44)
    [(to, first)] = dials(c)
    assert first == (f"{OPENER}, calling because the water reaches your street in about 59 minutes and we haven't heard "
                     f"back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?"), first
    [live] = c.get("/calls").json()["live"]
    assert live["reason"] == "no_reply" and live["turns"] == 0 and live["started_t_s"] == (out_by - 44) * 60
    c.portal.call(c.app.state.voice.hang_up, R1)  # nobody answered
    assert tap.outs(R1)[-1].startswith("We just tried to call you. In this drill's flood forecast, water reaches")
    assert c.get("/calls").json()["recent"][0]["outcome"] == "no_answer"
    at(c, out_by - 20)
    assert len(dials(c)) == 1  # once per unanswered question, however long the cooldown
    assert c.post("/dev/reset").status_code == 200
    assert c.app.state.store.kv_prefix("call:") == {}


def test_calls_when_the_pickup_changed_and_they_havent_written_since(vd):
    c = vd
    register(c, R1)
    for w in (PUTNAM, "2 of us", "yes"):
        text(c, R1, w)
    at(c, 2)
    assert dials(c) == []
    r = c.post("/reports", json={"source": "operator", "kind": "need", "household_id": thread_of(c, R1)["household_id"],
                                 "payload": {"people": 2, "mobility": True, "accessible_vehicle": True}})
    assert r.status_code == 200 and r.json()["replanned"]
    [(to, first)] = dials(c)
    assert first.startswith(f"{OPENER}, calling with a new pickup for you, because your household's needs changed. Accessible Van"), first
    assert c.get("/calls").json()["live"][0]["reason"] == "pickup_changed"


def test_most_at_risk_first_within_the_cap(vd):
    from dataclasses import replace
    c = vd
    c.app.state.voice.settings = replace(c.app.state.voice.settings, voice_max_concurrent=1)
    c.app.state.locator.llm.script[FLAGG] = ex(fact("location", address="Flagg St", cross_street="Memorial Dr"))
    for handle, where in ((R1, PUTNAM), (R2, FLAGG)):
        register(c, handle)
        text(c, handle, where)
    assert deadline_min(c, R2) < deadline_min(c, R1)
    at(c, deadline_min(c, R1) - 40)  # both unanswered and close to the water: R2's water comes first
    assert [to for to, _ in dials(c)] == [R2]
    c.portal.call(c.app.state.voice.hang_up, R2)
    at(c, deadline_min(c, R1) - 39)
    assert [to for to, _ in dials(c)] == [R2, R1]


def test_call_words_that_are_not_for_the_thread(vd):
    """"Hello?" as they pick up, "sorry, what?", "who is this?", "thank you": the call answers; the thread doesn't change."""
    c = vd
    register(c, R1)
    text(c, R1, PUTNAM)
    first = c.portal.call(c.app.state.voice.call, R1)["opening"]
    key = f"household:{thread_of(c, R1)['household_id']}"
    before = len(c.app.state.store.thread_messages(key))
    turn = lambda w: spoken(say(c, w, caller=OURS, called=R1, conv="conv_9"))  # noqa: E731
    hello = turn("Hello?")
    assert hello == f"{OPENER}. {first.split('. ', 1)[1]}" != first     # a short hello, never the whole opener again
    assert turn("Sorry, what?") == hello
    who = turn("Who is this?")
    assert who.startswith(WHO_WE_ARE) and who.endswith("wheelchair-accessible vehicle?")
    assert turn("Thank you, dear.") == "You're welcome. I'm texting you all of this now. Take care."
    assert not [m for m in c.app.state.store.thread_messages(key)[before:] if m["direction"] == "in"]


def test_call_screening_gets_who_and_why_and_changes_nothing(vd):
    register(vd, R1)
    who = f"{WHO_WE_ARE} {WHERE}"  # who and why, then the one thing we need from them
    assert spoken(say(vd, "Hi, if you record your name and reason for calling, I'll see if this person is available.")) == who
    assert spoken(say(vd, "Please stay on the line.")) == who
    assert vd.app.state.store.phone(handle=R1)["thread_key"] is None   # the screening didn't place anyone
    assert {m["direction"] for m in vd.app.state.messenger.lobby_log(R1)} == {"out"}  # not stored as the resident's words


def test_our_own_echo_is_ignored_but_the_caller_never_is(vd):
    c = vd
    c.app.state.intake.llm = c.app.state.locator.llm = None  # no model: the keyword parser
    register(c, R1)
    first = spoken(say(c, PUTNAM))
    assert first.startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
    assert spoken(say(c, first)) == ""                                   # our words coming back: silence
    offer = spoken(say(c, "Got it, you have me at Putnam Avenue and Western Avenue. 2 of us"))  # an answer in it
    assert " will pick you up at " in offer, offer


def test_a_frightened_caller_hears_a_calm_word_first(vd):
    register(vd, R1)
    text(vd, R1, PUTNAM)
    vd.app.state.intake.llm = None  # the keyword parser
    assert spoken(say(vd, "Oh my god, is the water coming? What do I do?")).startswith(f"{CALM} In this drill's flood forecast")
    assert CALM not in spoken(say(vd, "Two of us, please hurry"))       # once a call
