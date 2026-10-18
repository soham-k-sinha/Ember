"""Phone calls (D74), the primary channel since D100: ElevenLabs runs the call, our backend is its Custom LLM. What a
caller says goes through the same path as a text; what the thread would text is said on the call instead. No network:
ElevenLabs is faked at the HTTP layer, the voice app is driven in the backend's own event loop (as in the drill, one
process)."""
import argparse
import asyncio
import json
import re
from dataclasses import replace

import httpx
import pytest

from residents import voice as voice_mod
from residents.drill import Drill
from residents.messaging import DISCLOSURE as TEXT_NOTICE
from residents.messaging import plain
from residents.outbound import ASK_NEEDS
from residents.speech import render, render_all
from residents.voice import (BYE, CALM, CLOSED, DISCLOSURE, FULL_CALL, HI, INBOUND, MISSED, SYSTEM_PROMPT, WHERE, WHO_WE_ARE,
                             configure_agent, create_voice_app, wait_for_voice)
from tests.helpers import CALLENDER, GREEN, PUTNAM, R1, R2, Tap, ex, fact, make, register, text, thread_of

OURS = "+16175550199"           # the Photon voice number (placeholder)
TOKEN = "t0k"
R3 = "+16175550103"


def sys_prompt(caller, called=OURS, conv="conv_1"):
    return SYSTEM_PROMPT.replace("{{system__caller_id}}", caller).replace("{{system__called_number}}", called) \
        .replace("{{system__conversation_id}}", conv)


def configure(c, **kw):
    v = c.app.state.voice
    v.settings = replace(v.settings, photon_voice_number=OURS, elevenlabs_api_key="k", elevenlabs_agent_id="agent_1",
                         elevenlabs_phone_number_id="phnum_1", **kw)


@pytest.fixture
def vd(drill):
    configure(drill)
    drill.seen = []  # configured, so EMBER calls on its own (D100): never the real ElevenLabs
    drill.app.state.voice.http = fake_eleven(drill.seen, [])
    for h in (drill.app.state.intake.llm, drill.app.state.locator.llm):
        h.script["what's the plan?"] = ex(fact("question", question_topic="plan"))
    return drill


def say(c, words, caller=R1, called=OURS, stream=False, token=TOKEN, conv="conv_1", tools=None):
    """One caller turn through the voice app, in the backend's event loop. Returns the HTTP response."""
    return c.portal.call(post, c, words, caller, called, stream, token, conv, tools)


async def post(c, words, caller=R1, called=OURS, stream=False, token=TOKEN, conv="conv_1", tools=None):
    vapp = create_voice_app(lambda: c.app.state.voice, TOKEN)
    body = {"model": "ember", "stream": stream,
            "messages": [{"role": "system", "content": sys_prompt(caller, called, conv)},
                         {"role": "assistant", "content": "Hi, this is EMBER"},
                         {"role": "user", "content": words}]}
    if tools is not None:
        body["tools"] = tools
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=vapp), base_url="http://v") as cl:
        return await cl.post(f"/{token}/v1/chat/completions", json=body)


def spoken(r) -> str:
    if r.headers["content-type"].startswith("text/event-stream"):
        parts = [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: {")]
        assert r.text.rstrip().endswith("data: [DONE]")
        return "".join(p["choices"][0]["delta"].get("content", "") for p in parts)
    return r.json()["choices"][0]["message"]["content"]


# ---------- speech ----------
@pytest.mark.parametrize("text,want", [
    (f"{TEXT_NOTICE} Van 2 will pick you up in about 12 min. (plan v3)", "Van 2 will pick you up in about 12 minutes."),
    ("Van 2 picks you up in about 9 min. Pack medications, ID and your phone, then walk to the pickup point: the corner "
     "of Putnam Ave and N Harvard St, about 120 m north of you (about 2 min on foot).",
     "Van 2 picks you up in about 9 minutes. Pack medications, ID and your phone, then walk to the pickup point: the corner "
     "of Putnam Avenue and North Harvard Street, about 120 meters north of you."),
    ("Where are you right now? Reply with your street address (e.g. 125 Western Ave) or the nearest intersection.",
     "Where are you right now? Tell me your street address or the nearest intersection."),
    # the plan's reasons behind a pickup: the follow-up text has them
    ("Accessible Van 3 is coming to your door in about 3 min. Be ready at the door with medications, ID, your phone and "
     "the wheelchair. Accessible Van 3 is the only wheelchair-accessible vehicle that fits 4 people; it picks up 1 other "
     "household first. (plan v4)",
     "Accessible Van 3 is coming to your door in about 3 minutes. Be ready at the door with medications, ID, your phone "
     "and the wheelchair."),
    ("Van 2 will pick you up at the corner of Memorial Drive and River St in about 64 min and take you to the Treehouse. "
     "It picks up 8 other households first; you share the trip with 1 other household: it collects you both before the "
     "drop-off.", "Van 2 will pick you up at the corner of Memorial Drive and River Street in about 64 minutes."),
    ("Reply YES to keep it, or NO to decline anyway.", "Say yes to keep it, or no to decline anyway."),
    ("Utility truck is outside now. Understood, we won't send Utility truck.",
     "The utility truck is outside now. Understood, we won't send the utility truck."),
    ("Bring ID (and prescriptions), e.g. a charger.", "Bring ID (and prescriptions), for example, a charger."),
    ("In a real emergency, call 911.", "In a real emergency, call 9 1 1."),
    ("We've passed your question to a coordinator, who will reply here.",
     "We've passed your question to a coordinator, who will get back to you."),
    ("household #10296; overflow 9,600 m³. We'll text you if that changes. Text us if anything changes.",
     "household number 10296; overflow 9,600 cubic meters. We'll let you know if that changes. Tell us if anything changes."),
    ("Send your street address or the nearest intersection.", "Tell me your street address or the nearest intersection."),
    ("Send a street address or the two nearest cross streets there.", "Tell me a street address or the two nearest cross streets there."),
])
def test_render(text, want):
    assert render(text) == want


def test_nothing_screen_only_survives():
    for t in [f"{TEXT_NOTICE} x (plan v12)", "Reply NO if you'd rather stay put", "Stadium Rd and Western Ave"]:
        r = render(t)
        assert not re.search(r"simulation|\(plan v|Reply|\b(Rd|Ave|St)\b", r), r


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
    with make(replace(settings, db_path=tmp_path / "call.db"), solo_bridge) as c:
        tap = Tap(c)
        c.app.state.voice.settings = replace(c.app.state.voice.settings, photon_voice_number=OURS)
        register(c, R1)
        by_call = [spoken(say(c, w)) for w in FLOW]
        assert all(e["delivery"] == "voice" for e in tap.events if e["direction"] == "out"), tap.events
        rows = c.app.state.store.thread_messages(f"household:{thread_of(c, R1)['household_id']}")
        assert any(m["direction"] == "in" and m["text"] == "2 of us" for m in rows)  # the call is in the thread
    by_call = [c.removesuffix(" " + BYE) for c in by_call]  # an "okay" once they know their pickup also closes the call
    assert by_call == by_text, list(zip(FLOW, by_text, by_call))
    assert by_call[0].startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
    assert " picks you up in about " in by_call[1] and "yes" not in by_call[1].lower()  # the instruction, no ask
    assert by_call[3].startswith("Thanks. Van ") and " gets to you in about " in by_call[3]  # "yes": understood, not needed


def test_after_the_call_it_texts_again(vd):
    c = vd
    configure(c, voice_max_concurrent=0)  # the call is theirs: EMBER doesn't ring on its own here
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


async def test_voice_health_is_protected_and_checks_backend_readiness():
    for backend, status in ((None, 503), (object(), 200)):
        app = create_voice_app(lambda backend=backend: backend, TOKEN)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://voice") as client:
            assert (await client.get(f"/{TOKEN}/health")).status_code == status
            assert (await client.get("/wrong/health")).status_code == 404


async def test_the_voice_callback_must_be_ready_before_dialing():
    responses = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: responses.pop(0))) as client:
        assert await wait_for_voice("https://callback.test/token/health", client, poll_s=0)
        assert responses == []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        assert not await wait_for_voice("https://callback.test/token/health", client, timeout_s=0)


# ---------- anyone can call the number and join by voice (D100) ----------
def test_an_unknown_caller_joins_by_voice(vd, solo_bridge):
    c = vd
    words = spoken(say(c, "hello?", caller=R2))                    # the agent already said INBOUND (the notice)
    p = next(x for x in c.get("/phones").json() if x["handle"] == R2)
    assert p["player"] == 1 and p["household_id"] is not None      # Player 1, on a flood-zone house we chose
    d = solo_bridge.deadline(p["household_id"])
    assert d is not None
    assert re.fullmatch(rf"You're Player 1, living by [^;.]+; the river reaches your street in about \d+ minutes\. "
                        rf"{re.escape(ASK_NEEDS)}", words), words
    assert c.app.state.store.plan(2)["trigger"] == "Player 1 joined by phone"
    assert c.app.state.voice.live(R2).turns == 1 and dials(c) == []  # no call out: they're on the line
    offer = spoken(say(c, "me and my dad, he uses a wheelchair", caller=R2))
    assert offer.startswith("Accessible Van 3 is coming to your door in about "), offer
    assert c.get("/health").json()["players"] == 1


def test_a_full_simulation_and_a_closed_line_turn_callers_away(vd):
    c = vd
    c.app.state.messenger.max_players = 0
    assert spoken(say(c, "hello?", caller=R2)) == FULL_CALL
    assert c.app.state.store.phone(handle=R2) is None
    configure(c, voice_admit_callers=False)
    assert spoken(say(c, "hello?", caller=R3, conv="conv_2")) == CLOSED


# ---------- outbound calls through ElevenLabs ----------
def fake_eleven(seen, answers, status="in-progress"):
    def handler(req):
        seen.append((req.method, str(req.url), json.loads(req.content or b"null"), req.headers.get("xi-api-key")))
        if req.method == "GET":
            return httpx.Response(200, json={"status": status})
        return answers.pop(0) if answers else httpx.Response(200, json={"success": True, "conversation_id": "conv_9", "sip_call_id": "s"})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def dials(c) -> list[tuple[str, str]]:
    """(to, first words) of every call EMBER placed through the fake ElevenLabs."""
    return [(b["to_number"], b["conversation_initiation_client_data"]["conversation_config_override"]["agent"]["first_message"])
            for _, url, b, _ in c.seen if url.endswith("/outbound-call")]


def at(c, minutes):
    assert c.post("/clock", json={"t_s": minutes * 60.0}).status_code == 200


def deadline_min(c, handle):
    hid = thread_of(c, handle)["household_id"]
    return next(h for h in c.app.state.store.households() if h["household_id"] == hid)["deadline_s"] / 60


def over(c, monkeypatch):
    """ElevenLabs reports every call done (they hung up), and EMBER looks right away."""
    monkeypatch.setattr(voice_mod, "REAP_EVERY_S", 0.0)
    c.app.state.voice.http = fake_eleven(c.seen, [], status="done")


def water(c, handle):
    return round(deadline_min(c, handle) + 15)  # the street floods 15 min (the margin) after the pickup deadline


def join(c, handle):
    """POST /join, then the phone texts JOIN EMBER (D89): placed as Player N once the burst of joins is over."""
    assert c.post("/join", json={"handle": handle}).status_code == 200
    text(c, handle, "JOIN EMBER")
    if (task := c.app.state.locator.replan_task) is not None:
        c.portal.call(lambda: task)


def test_first_contact_is_a_call(vd):
    """A player who joins is called right away: the notice, where they live, when the water comes and the one question;
    the text says so. Their spoken answer drives the plan, said back on the call."""
    c = vd
    tap = Tap(c)
    join(c, R1)
    texted = [e["text"] for e in tap.events if e["direction"] == "out" and e["delivery"] != "voice"]
    assert texted[-1].endswith("We're calling you now.") and not any(ASK_NEEDS in t for t in texted)  # asked on the call
    [(to, first)] = dials(c)
    assert to == R1 and re.fullmatch(rf"{re.escape(DISCLOSURE)} The river reaches [^.]+ in about "
                                     rf"{water(c, R1)} minutes\. {re.escape(ASK_NEEDS)}", first), first
    [live] = c.get("/calls").json()["live"]
    assert live == {"handle": R1, "household_id": thread_of(c, R1)["household_id"], "reason": "first_contact",
                    "started_t_s": 0.0, "turns": 0}
    words = spoken(say(c, "2 of us", caller=OURS, called=R1, conv="conv_9"))
    assert re.fullmatch(r"[\w ]+ picks you up (now|in about \d+ minutes)\. Pack medications, ID and your phone, then "
                        r"(walk|go out) to the pickup point[^.]+\.", words), words  # two sentences, no "can you be ready?"
    a = next(x for x in c.app.state.store.current_plan()["assignments"] if x["target"] == thread_of(c, R1))
    assert a["status"] == "confirmed"                                   # silence means we proceed


def test_someone_texting_us_is_answered_by_text(vd):
    c = vd
    tap = Tap(c)
    register(c, R1)
    for w in (PUTNAM, "2 of us"):
        text(c, R1, w)
    assert dials(c) == [] and " picks you up in about " in tap.outs(R1)[-1]


def test_after_an_answered_call_one_short_text_follows(vd, monkeypatch):
    c = vd
    tap = Tap(c)
    join(c, R1)
    spoken(say(c, "me and my dad, he uses a wheelchair", caller=OURS, called=R1, conv="conv_9"))
    over(c, monkeypatch)
    c.portal.call(c.app.state.voice.check)
    follow_up = tap.events[-1]
    assert follow_up["delivery"] == "dev" and plain(follow_up["text"]).startswith("From our call: Accessible Van 3 is ")
    assert "door" in follow_up["text"], follow_up                       # the instruction in writing (now: 2 minutes away)
    assert c.get("/calls").json() == {"live": [], "recent": [{
        "handle": R1, "household_id": thread_of(c, R1)["household_id"], "reason": "first_contact", "outcome": "updated",
        "turns": 1, "ended_t_s": 0.0}]}


def test_an_unanswered_call_is_tried_once_more_then_texted(vd, monkeypatch):
    c = vd
    tap = Tap(c)
    join(c, R1)
    n = len(tap.outs(R1))
    assert len(dials(c)) == 1
    over(c, monkeypatch)
    c.portal.call(c.app.state.voice.check)                              # nobody picked up: no text yet, a retry is due
    assert tap.outs(R1)[n:] == [] and len(dials(c)) == 1
    c.app.state.voice.http = fake_eleven(c.seen, [])
    at(c, 1)
    assert len(dials(c)) == 1
    at(c, 2)                                                            # 2 sim-min later: once more
    assert len(dials(c)) == 2 and dials(c)[1][1].startswith(f"{HI} The river reaches ")  # the notice was said once
    over(c, monkeypatch)
    at(c, 3)
    assert tap.outs(R1)[-1].startswith(f"{MISSED} The river reaches your street in about "), tap.outs(R1)[-1]
    assert tap.outs(R1)[-1].endswith(ASK_NEEDS + f" (plan v{c.app.state.store.meta()['plan_version']})")
    assert [r["outcome"] for r in c.get("/calls").json()["recent"]] == ["no_answer", "no_answer"]
    at(c, 10)
    assert len(dials(c)) == 2                                           # one retry, never a third call
    assert c.post("/dev/reset").status_code == 200
    assert c.app.state.store.kv_prefix("retry:") == {} and c.app.state.store.kv_prefix("voiced:") == {}


def test_a_changed_pickup_is_a_call_that_says_why(vd):
    c = vd
    configure(c, voice_max_concurrent=0)                                # by text first
    register(c, R1)
    for w in (PUTNAM, "2 of us"):
        text(c, R1, w)
    assert dials(c) == []
    configure(c, voice_max_concurrent=3)
    r = c.post("/reports", json={"source": "operator", "kind": "need", "household_id": thread_of(c, R1)["household_id"],
                                 "payload": {"people": 2, "mobility": True, "accessible_vehicle": True}})
    assert r.status_code == 200 and r.json()["replanned"]
    [(to, first)] = dials(c)
    assert first.startswith(f"{DISCLOSURE} Your pickup changed because your household's needs changed. Accessible Van 3 is "
                            f"coming to your door in about "), first
    assert c.get("/calls").json()["live"][0]["reason"] == "pickup_changed"


def test_calls_queue_earliest_deadline_first_within_the_cap(vd, monkeypatch):
    c = vd
    configure(c, voice_max_concurrent=1)
    c.app.state.locator.llm.script[FLAGG] = ex(fact("location", address="Flagg St", cross_street="Memorial Dr"))
    for handle, where in ((R1, GREEN), (R3, CALLENDER), (R2, FLAGG)):
        register(c, handle)
        text(c, handle, where)
    assert dials(c) == []                                               # they were texting: answered by text
    assert deadline_min(c, R2) < deadline_min(c, R3)                    # (GREEN: outside the flood, no deadline)
    v = c.app.state.voice
    for h in (R1, R3, R2):                                              # three calls due at once, one line
        v.ring(h, "instruction")
    c.portal.call(v.check)
    assert [to for to, _ in dials(c)] == [R2]                           # R2's water comes first
    over(c, monkeypatch)
    c.portal.call(v.check)                                              # R2's call is over: the line is free
    assert [to for to, _ in dials(c)] == [R2, R3]


def test_two_minutes_away_is_a_call_for_a_busy_person(vd):
    """Never a yes, never a done: the instruction, then every step on the plan's clock; "2 minutes away" rings."""
    c = vd
    configure(c, voice_max_concurrent=0)
    tap = Tap(c)
    register(c, R1)
    for w in (PUTNAM, "2 of us"):
        text(c, R1, w)
    configure(c, voice_max_concurrent=3)
    at(c, c.portal.call(c.app.state.guide.next_event_t) / 60)          # the vehicle is 2 minutes away
    [(to, first)] = dials(c)
    assert re.fullmatch(rf"{re.escape(DISCLOSURE)} [\w ]+ is 2 minutes away\. Go to the corner of [A-Za-z ]+ now\.", first), first
    assert not any("yes" in o.lower() or "done" in o.lower() for o in tap.outs(R1)), tap.outs(R1)


def test_call_words_that_are_not_for_the_thread(vd):
    """"Hello?" as they pick up, "sorry, what?", "who is this?", "thank you": the call answers; the thread doesn't change."""
    c = vd
    configure(c, voice_max_concurrent=0)
    register(c, R1)
    text(c, R1, PUTNAM)
    first = c.portal.call(c.app.state.voice.call, R1)["opening"]
    assert first == f"{DISCLOSURE} {ASK_NEEDS}"
    key = f"household:{thread_of(c, R1)['household_id']}"
    before = len(c.app.state.store.thread_messages(key))
    turn = lambda w: spoken(say(c, w, caller=OURS, called=R1, conv="conv_9"))  # noqa: E731
    hello = turn("Hello?")
    assert hello == f"{HI} {ASK_NEEDS}"                                 # a short hello, never the whole notice again
    assert turn("Sorry, what?") == hello
    who = turn("Who is this?")
    assert who.startswith(WHO_WE_ARE) and who.endswith(ASK_NEEDS)
    assert turn("Thank you, dear.") == "You're welcome. I'll text you all of this now. Take care."
    assert not [m for m in c.app.state.store.thread_messages(key)[before:] if m["direction"] == "in"]


def test_call_without_override_says_the_opening_on_the_first_turn(vd):
    c = vd
    configure(c, voice_max_concurrent=0)
    register(c, R1)
    text(c, R1, PUTNAM)
    seen = []
    c.app.state.voice.http = fake_eleven(seen, [httpx.Response(400, json={"detail": "first_message override is not allowed"})])
    c.portal.call(c.app.state.voice.call, R1)
    assert len(seen) == 2 and "conversation_config_override" not in seen[1][2]["conversation_initiation_client_data"]
    c.app.state.intake.llm.script["hello"] = ex(fact("other"))
    assert spoken(say(c, "hello", caller=OURS, called=R1)) == f"{DISCLOSURE} {ASK_NEEDS}"


def test_failed_dial_is_reported_and_texts_resume(vd):
    c = vd
    configure(c, voice_max_concurrent=0)
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
    assert patch["built_in_tools"]["end_call"]["params"]["system_tool_type"] == "end_call"
    assert next(b for m, b in seen if m == "PATCH")["conversation_config"]["agent"]["first_message"] == INBOUND
    bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"conversation_config": {}})))
    ok, detail = vd.portal.call(configure_agent, s, "https://x/v1", bad)
    assert not ok and "still points at" in detail


# ---------- the console calls the people in the flood zone ----------
def test_drill_calls_only_callers_in_the_flood(vd, capsys):
    c = vd
    d = Drill(argparse.Namespace(dry=True, crowded=False, keep=False, port=0, db="x.db", resident=[], operator=[],
                                 voice=True, caller=[f"{R1}=Putnam Ave and Western Ave", f"{R2}=Green St and Sellers St"]))
    d.app = c.app
    c.portal.call(d.register)
    c.portal.call(d.dial_callers)
    out = capsys.readouterr().out
    assert re.search(rf"\[pretend call to r1\] EMBER: {re.escape(DISCLOSURE)} The river reaches Putnam Avenue and "
                     rf"Western Avenue in about \d+ minutes\. {re.escape(ASK_NEEDS)}\n", out), out
    assert "r2 at Green Street and Sellers Street: outside the forecast flood, so not called" in out
    assert c.app.state.voice.live(R2) is None and c.app.state.voice.live(R1) is not None
    c.portal.call(d.command, "@r1 2 of us")
    assert "[call] EMBER → r1: " in capsys.readouterr().out


def test_call_screening_gets_who_and_why_and_changes_nothing(vd):
    register(vd, R1)
    who = f"{WHO_WE_ARE} {WHERE}"  # who and why, then the one thing we need from them
    assert spoken(say(vd, "Hi, if you record your name and reason for calling, I'll see if this person is available.")) == who
    assert spoken(say(vd, "Please stay on the line.")) == who
    assert vd.app.state.store.phone(handle=R1)["thread_key"] is None   # the screening didn't place anyone
    assert {m["direction"] for m in vd.app.state.messenger.lobby_log(R1)} == {"out"}  # not stored as the resident's words


@pytest.mark.parametrize("greeting", [
    "The person you called has a voice mailbox that hasn't been set up yet. Goodbye.",
    "The mailbox is full.",
    "Please leave a message after the tone.",
    "The person you're trying to reach is not available. At the tone, please record your message.",
])
def test_a_mailbox_greeting_uses_the_unanswered_call_path(vd, greeting):
    c = vd
    join(c, R1)
    before = len(c.app.state.store.reports())
    assert spoken(say(c, greeting, conv="conv_9")) == ""
    c.portal.call(c.app.state.voice.hang_up, R1)
    assert c.app.state.voice.calls_view()["recent"][0]["outcome"] == "no_answer"
    assert c.app.state.store.kv_get(f"retry:{R1}") is not None
    assert len(c.app.state.store.reports()) == before


@pytest.mark.parametrize("silence", ["...", "…"])
def test_silence_asks_once_then_closes_and_hesitation_says_nothing(vd, silence):
    join(vd, R1)
    before = len(vd.app.state.store.reports())
    assert spoken(say(vd, "Um-", conv="conv_9")) == ""
    assert spoken(say(vd, silence, conv="conv_9")).startswith("Are you still there? ")
    assert spoken(say(vd, silence, conv="conv_9")) == BYE
    assert len(vd.app.state.store.reports()) == before


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("words", ["Thanks, bye.", "Please leave a message after the tone."])
def test_a_goodbye_or_mailbox_ends_the_call_when_the_provider_offers_the_tool(vd, stream, words):
    join(vd, R1)
    response = say(vd, words, conv="conv_9", stream=stream,
                   tools=[{"type": "function", "function": {"name": "end_call"}}])
    if stream:
        chunks = [json.loads(line[6:])["choices"][0] for line in response.text.split("\n\n") if line.startswith("data: {")]
        call = next(c["delta"]["tool_calls"][0] for c in chunks if c["delta"].get("tool_calls"))
        said = "".join(c["delta"].get("content") or "" for c in chunks)
        assert chunks[-1]["finish_reason"] == "tool_calls" and response.text.rstrip().endswith("data: [DONE]")
    else:
        choice = response.json()["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        call, said = choice["message"]["tool_calls"][0], choice["message"]["content"] or ""
    assert call["function"]["name"] == "end_call"
    assert said.endswith("Take care.") if "bye" in words else said == ""  # the goodbye is spoken, then the call ends


def test_a_needs_answer_does_not_end_a_call_even_when_the_tool_is_available(vd):
    join(vd, R1)
    reply = say(vd, "4 of us, one wheelchair", conv="conv_9",
                tools=[{"type": "function", "function": {"name": "end_call"}}]).json()["choices"][0]
    assert reply["finish_reason"] == "stop" and "tool_calls" not in reply["message"]


def test_spoken_headcount_and_wheelchair_are_understood_on_the_first_turn_without_a_model(vd):
    c = vd
    join(c, R1)
    c.app.state.intake.llm = c.app.state.locator.llm = None
    reply = spoken(say(c, "We are four, and we need one w- wheelchair.", conv="conv_9"))
    assert "Accessible Van" in reply and "coming to your door" in reply and "How many" not in reply
    household = next(h for h in c.get("/state").json()["households"] if h["household_id"] == thread_of(c, R1)["household_id"])
    assert household["needs"] == {"people": 4, "mobility": True, "accessible_vehicle": True}
    assert spoken(say(c, "Uh, four.", conv="conv_9")).startswith("Got it.")
    assert spoken(say(c, "Um-", conv="conv_9")) == ""


def test_a_replaced_numeric_fragment_does_not_change_the_household_size(vd, monkeypatch):
    c = vd
    join(c, R1)
    c.app.state.intake.llm = c.app.state.locator.llm = None
    say(c, "We are four, and we need a wheelchair.", conv="conv_9")
    monkeypatch.setattr(voice_mod, "COUNT_SETTLE_S", 0.05)
    before = len(c.app.state.store.reports())

    async def revised():
        first = asyncio.create_task(c.app.state.voice.turn(R1, "conv_9", "Five."))
        await asyncio.sleep(0.01)
        replacement = await c.app.state.voice.turn(R1, "conv_9", "Um-")
        return await first, replacement

    assert c.portal.call(revised) == (None, None)
    assert len(c.app.state.store.reports()) == before
    household = next(h for h in c.get("/state").json()["households"] if h["household_id"] == thread_of(c, R1)["household_id"])
    assert household["needs"]["people"] == 4


def test_our_own_echo_is_ignored_but_the_caller_never_is(vd):
    c = vd
    c.app.state.intake.llm = c.app.state.locator.llm = None  # no model: the keyword parser
    register(c, R1)
    first = spoken(say(c, PUTNAM))
    assert first.startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
    assert spoken(say(c, first)) == ""                                   # our words coming back: silence
    offer = spoken(say(c, "Got it, you have me at Putnam Avenue and Western Avenue. 2 of us"))  # an answer in it
    assert " picks you up in about " in offer, offer


def test_a_frightened_caller_hears_a_calm_word_first(vd):
    configure(vd, voice_max_concurrent=0)
    register(vd, R1)
    text(vd, R1, PUTNAM)
    vd.app.state.intake.llm = None  # the keyword parser
    assert spoken(say(vd, "Oh my god, is the water coming? What do I do?")).startswith(f"{CALM} The river reaches your street")
    assert CALM not in spoken(say(vd, "Two of us, please hurry"))       # once a call


# ---------- ElevenLabs re-sends a turn while it revises what it heard (live, 2026-10-18; D100) ----------
WALKER = ["A walker.", "A walker. I need my ankle.", "A walker. I need my needle."]
DONE = ["I'm done.", "I'm done. Okay, done.", "A walker. I need my needle.", "I'm done.", "I'm done.", "I'm done. Okay, done."]


@pytest.fixture
def on_call(vd):
    """R1 at Putnam, 2 of them with a wheelchair, Accessible Van 3 coming; on a call with EMBER (keyword parser)."""
    c = vd
    configure(c, voice_max_concurrent=0)
    c.app.state.intake.llm = c.app.state.locator.llm = None
    register(c, R1)
    for w in (PUTNAM, "me and my dad, he uses a wheelchair"):
        text(c, R1, w)
    c.key = f"household:{thread_of(c, R1)['household_id']}"
    c.portal.call(c.app.state.voice.call, R1)
    return c


def heard(c):
    return [m["text"] for m in c.app.state.store.thread_messages(c.key) if m["direction"] == "in"]


def test_the_live_duplicate_turns_are_answered_once(on_call):
    c = on_call
    turn = lambda w: spoken(say(c, w, caller=OURS, called=R1, conv="conv_9"))  # noqa: E731
    guide = c.app.state.guide
    step, t0, n = guide.state(c.key)["sent"], c.app.state.store.meta()["t_s"], len(heard(c))
    replies = [turn(w) for w in WALKER + DONE]
    # the revisions replace the turn before (each processed once, the needle counts); the re-sent turns aren't processed
    assert heard(c)[n:] == WALKER + ["I'm done.", "I'm done. Okay, done."]
    h = next(x for x in c.app.state.store.households() if f"household:{x['household_id']}" == c.key)
    assert h["needs"] == {"people": 2, "mobility": True, "accessible_vehicle": True, "medical": True}
    assert replies[5] == replies[2]                                      # the needle again: the same reply
    assert replies[6] == replies[7] == replies[3]                        # "I'm done." again: the same reply
    assert replies[8] == replies[4]
    assert replies[3].startswith("Thanks. Accessible Van 3 gets to you in about ")  # understood, never needed
    assert guide.state(c.key)["sent"] == step and c.app.state.store.meta()["t_s"] == t0  # no step skipped, no clock jump


def test_turns_that_arrive_together_are_handled_one_at_a_time(on_call):
    c = on_call
    n = len(heard(c))

    async def burst():
        return await asyncio.gather(*(post(c, "I'm done.", OURS, R1, False, TOKEN, "conv_9") for _ in range(3)))
    replies = [spoken(r) for r in c.portal.call(burst)]
    assert heard(c)[n:] == ["I'm done."] and len(set(replies)) == 1


def test_a_revised_no_declines_once(on_call, monkeypatch):
    """The only vehicle that fits: a "no" is checked; its revision isn't a second "no"; a real second "no" later is."""
    c = on_call
    turn = lambda w: spoken(say(c, w, caller=OURS, called=R1, conv="conv_9"))  # noqa: E731
    assert "It's still coming unless you say no again." in turn("No.")
    assert "It's still coming unless you say no again." not in turn("No. No, thanks.")
    rejected = f"rejected:{c.key}"
    assert c.app.state.store.kv_get(rejected) is None                   # the revision didn't decline it
    monkeypatch.setattr(voice_mod, "REVISE_S", -1.0)
    monkeypatch.setattr(voice_mod, "REPEAT_S", -1.0)                    # later on
    assert turn("No.").startswith("Understood, we won't send Accessible Van 3.")
    assert c.app.state.store.kv_get(rejected) == '["van-3"]'


FLAGG = "Flagg St and Memorial Dr"  # the flood reaches it first (out by 75 min); PUTNAM: out by 135 min


def test_concurrent_plan_and_poll_hooks_dial_a_queued_call_once(vd):
    c = vd
    register(c, R1)
    text(c, R1, PUTNAM)
    v = c.app.state.voice
    v.ring(R1, "first_contact")
    seen = []

    async def handler(req):
        if req.method == "POST":
            seen.append(json.loads(req.content))
            await asyncio.sleep(0.01)  # another plan/poll hook runs while the dial is in flight
            return httpx.Response(200, json={"success": True, "conversation_id": "conv_9"})
        return httpx.Response(200, json={"status": "in-progress"})

    v.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def together():
        await asyncio.gather(v.check(), v.check())

    c.portal.call(together)
    assert len(seen) == 1
    assert v.calls_view()["live"][0]["handle"] == R1


def test_news_arriving_while_a_call_is_dialing_stays_in_its_outbox(vd):
    c = vd
    register(c, R1)
    text(c, R1, PUTNAM)
    v = c.app.state.voice
    v.ring(R1, "instruction")
    v.capture(R1, "The original pickup instruction.")
    update = "Your pickup changed because River Street was reported blocked."

    async def handler(req):
        v.capture(R1, update)  # a replan finishes after the opening was composed
        return httpx.Response(200, json={"success": True, "conversation_id": "conv_9"})

    v.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c.portal.call(v.check)
    assert v.live(R1).outbox == [update]


def test_an_unknown_callers_first_answer_keeps_their_needs(vd):
    c = vd
    c.app.state.intake.llm = c.app.state.locator.llm = None
    words = spoken(say(c, "me and my dad, he uses a wheelchair", caller=R2))
    hid = thread_of(c, R2)["household_id"]
    household = next(h for h in c.app.state.store.households() if h["household_id"] == hid)
    assert household["needs"] == {"people": 2, "mobility": True, "accessible_vehicle": True}
    assert "Accessible Van 3 is coming to your door" in words
    assert ASK_NEEDS not in words


def test_idle_call_sends_its_written_follow_up_when_provider_status_is_unavailable(vd):
    c = vd
    configure(c, voice_max_concurrent=0)
    tap = Tap(c)
    register(c, R1)
    for words in (PUTNAM, "2 of us"):
        text(c, R1, words)
    v = c.app.state.voice
    c.portal.call(v.call, R1)
    v.sessions[R1].turns = 1
    v.sessions[R1].last -= voice_mod.SESSION_IDLE_S + 1
    v.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    c.portal.call(v.check)
    assert R1 not in v.sessions
    assert tap.outs(R1)[-1].startswith("From our call:")


def test_a_call_waiting_for_a_free_line_uses_the_current_pickup_step(vd):
    c = vd
    configure(c, voice_max_concurrent=0)
    for handle, where in ((R1, PUTNAM), (R2, GREEN)):
        register(c, handle)
        text(c, handle, where)
    text(c, R1, "2 of us")
    v = c.app.state.voice
    c.portal.call(v.call, R2)  # the only line is busy
    configure(c, voice_max_concurrent=1)
    v.ring(R1, "soon")
    v.capture(R1, "Van 2 is 2 minutes away. Go to the corner now.")
    arrival = c.portal.call(c.app.state.guide.next_event_t) + 120
    at(c, arrival / 60)  # by the time a line is free, the van is outside
    assert not any(to == R1 for to, _ in dials(c))
    c.portal.call(v.hang_up, R2)
    c.portal.call(v.check)
    opening = next(first for to, first in dials(c) if to == R1)
    assert "2 minutes away" not in opening
    assert "now" in opening and "get in" in opening


def test_a_missed_call_retries_while_the_simulation_clock_is_paused(vd, monkeypatch):
    c = vd
    join(c, R1)
    over(c, monkeypatch)
    c.portal.call(c.app.state.voice.check)
    t0 = c.app.state.planner.now()
    retry = json.loads(c.app.state.store.kv_get(f"retry:{R1}"))
    retry["wall"] -= voice_mod.RETRY_WALL_S + 1
    c.app.state.store.kv_set(f"retry:{R1}", json.dumps(retry))
    c.app.state.voice.http = fake_eleven(c.seen, [])
    c.portal.call(c.app.state.voice.check)
    assert len(dials(c)) == 2 and c.app.state.planner.now() == t0


@pytest.mark.parametrize("assigned", [True, False])
def test_a_voice_only_caller_is_told_how_to_enable_the_written_follow_up(vd, assigned):
    from tests.fake_photon import LINE, FakePhoton

    c = vd
    register(c, R1)
    text(c, R1, PUTNAM)
    photon = FakePhoton().client()
    c.app.state.messenger.photon = photon
    c.app.state.store.upsert_phone(R1, "resident", assigned_number=LINE if assigned else None)
    try:
        words = spoken(say(c, "Thanks, bye."))
        assert "I'll text you" not in words
        if assigned:
            assert "iMessage" in words and LINE in words
        else:
            assert words == "You're welcome. Take care."
    finally:
        c.portal.call(photon.aclose)


def test_tonights_live_calls(vd):
    """Turns from the real calls of 2026-10-18 03:26–03:45: needs in one breath, an off-topic question, a request for
    the police (a simulation can't send anyone: say so, then 911), and an "okay" that closes the call."""
    join(vd, R1)
    assert "Accessible Van" in spoken(say(vd, "We are four, and we need one w- wheelchair.", conv="conv_9"))
    assert spoken(say(vd, "Um, do you know about Arnoux?", conv="conv_9")).startswith("I can only help with your evacuation. ")
    police = spoken(say(vd, "Um, for some reason, I'm unable to. Can you send the police to me?", conv="conv_9"))
    assert police.startswith("This is a simulation, so I can't send anyone. If anyone is in real danger, hang up and call 9 1 1.")
    assert spoken(say(vd, "Sounds good.", conv="conv_9")).endswith(BYE)


def test_a_casual_okay_closes_once_they_know_their_pickup(vd):
    """Live 2026-10-18 04:35: "Um, sounds good to me." and "Okay. Coming." kept the call going."""
    join(vd, R1)
    say(vd, "We are four, and one needs a wheelchair.", conv="conv_9")
    assert spoken(say(vd, "Um, sounds good to me.", conv="conv_9")).endswith(BYE)
    assert not spoken(say(vd, "Okay, but where do we go?", conv="conv_9")).endswith(BYE)
