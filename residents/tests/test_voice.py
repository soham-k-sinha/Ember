"""Phone calls (D61): ElevenLabs runs the call, our backend is its Custom LLM. What a caller says goes through the
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
from residents.voice import OPENER, SYSTEM_PROMPT, configure_agent, create_voice_app
from tests.test_drill import (GREEN, PUTNAM, R1, R2, Tap, drill, make, register, solo_bridge,  # noqa: F401
                              text, thread_of)
from tests.test_extract import ex, fact

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
    for h in (drill.app.state.intake.llm, drill.app.state.locator.llm):
        h.script["what's the plan?"] = ex(fact("question", question_topic="plan"))
    return drill


def say(c, words, caller=R1, called=OURS, stream=False, token=TOKEN):
    """One caller turn through the voice app, in the backend's event loop. Returns the HTTP response."""
    vapp = create_voice_app(lambda: c.app.state.voice, TOKEN)
    body = {"model": "ember", "stream": stream,
            "messages": [{"role": "system", "content": sys_prompt(caller, called)},
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
     "Van 2 will pick you up in about 12 minutes. Say yes to confirm, or tell us what changed."),
    ("Walk to the corner of Putnam Ave and N Harvard St, about 120 m north of you (about 1 min on foot). Reply DONE when you're there.",
     "Walk to the corner of Putnam Avenue and North Harvard Street, about 120 meters north of you (about 1 minute on foot). Say done when you're there."),
    ("Where are you right now? Reply with your street address (e.g. 125 Western Ave) or the nearest intersection.",
     "Where are you right now? Tell me your street address (for example, 125 Western Avenue) or the nearest intersection."),
    ("In a real emergency, call 911.", "In a real emergency, call 9 1 1."),
    ("household #10296; overflow 9,600 m³. We'll text you if that changes. Text us if anything changes.",
     "household number 10296; overflow 9,600 cubic meters. We'll let you know if that changes. Tell us if anything changes."),
    ("Send your street address or the nearest intersection.", "Tell me your street address or the nearest intersection."),
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
    assert by_call == by_text, list(zip(FLOW, by_text, by_call))
    assert by_call[0].startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
    assert "Say yes to confirm" in by_call[1] and "Step 1 of 4" in by_call[3]


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
    assert first.startswith(OPENER + " In this drill's flood forecast, water reaches your street in about "), first
    assert "Please tell us: How many people are with you" in first and "(plan v" not in first
    assert rec["conversation_id"] == "conv_9" and c.get("/calls").json()["calls"][0]["handle"] == R1
    # their answer on the call → the offer, said on the call
    assert "Say yes to confirm" in spoken(say(c, "2 of us", caller=OURS, called=R1))


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
    assert words.startswith("In this drill's flood forecast"), words  # the opening, then the reply


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
    assert f"[pretend call to r1] EMBER: {OPENER} We have you at Putnam Avenue and Western Avenue. In this drill's flood forecast" in out, out
    assert "r2 at Green Street and Sellers Street: outside the forecast flood, so not called" in out
    assert c.app.state.voice.live(R2) is None and c.app.state.voice.live(R1) is not None
    c.portal.call(d.command, "@r1 2 of us")
    assert "[call] EMBER → r1: " in capsys.readouterr().out
