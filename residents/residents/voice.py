"""Phone calls (D74): ElevenLabs runs the call (speech-to-text, text-to-speech, turn-taking, the Photon SIP
number); EMBER's backend is its "Custom LLM", so every sentence on the call is ours, never generated.

How one call works:
- ElevenLabs posts each caller turn to `/{token}/v1/chat/completions` (OpenAI-compatible, streamed) on the
  voice app: a separate server on its own port, the only thing exposed through the tunnel (never /dev/*).
  The agent's system prompt carries `EMBER-CALL caller={{system__caller_id}} called={{system__called_number}}
  conv={{system__conversation_id}}`, which tells us which phone this is.
- The words they said enter through `Messenger.phone_inbound`, exactly like a text (Locator / Intake / Guide /
  the one extraction call, unchanged). While the call is live, everything the backend would text that phone
  (`send_message` / `send_to_phone`) is captured here instead of texted, rendered for speech (speech.py) and
  returned as the reply. Steps or plan changes that happen between turns wait in the call's outbox and are
  said on the next turn. The call and the texts are one thread: what was said on the call is in the
  thread's history when the conversation moves back to text.
- Outbound calls (`call(handle)`): we first produce what the thread would say right now (the situation, or
  "where are you?"), then ask ElevenLabs to dial with that as the first message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .speech import render, render_all
from .threads import normalize_handle, phone_thread, unplaced

log = logging.getLogger("residents.voice")

ELEVENLABS = "https://api.elevenlabs.io"
OPENER = "Hi, this is EMBER, an automated flood drill. This is only a drill."
WHERE = "Where are you right now? Tell me your street address or the nearest intersection."
FILLER = "One moment... "        # ElevenLabs' advice for slow turns: an ellipsis + space, said while we work
FILLER_AFTER_S = 1.2
SESSION_IDLE_S = 300.0           # a call with no turn for this long is over (its leftovers go back to text)
# Phone call screening (iPhone "Screen Unknown Callers", Google Call Screen) answers first and asks who's calling
# and why; answering that (once) is what gets the call put through. A person asking "who is this?" gets the same.
SCREENING = re.compile(r"\b(stay on the line|record (your|it)\b|recorded\b|reason for (your )?call|screening service|"
                       r"see if (this person|they)( is| are|'re)? (is )?available|i'll see if|who('s| is) (calling|this)|state your name|"
                       r"leave (a|your) (message|name))", re.I)
WHO_WE_ARE = ("This is EMBER, the HackHarvard flood drill, calling with this phone's evacuation plan. It's a drill, "
              "not a real emergency.")
ECHO_SIMILAR = 0.7               # this close to what we just said, and no answer in it: our own voice coming back
ECHO_EXACT = 0.85                # this close: our own voice, whatever it contains (our help text lists "yes", "done")
CALL_LINE = re.compile(r"caller=(\S*)\s+called=(\S*)\s+conv=(\S*)")
SYSTEM_PROMPT = ("EMBER-CALL caller={{system__caller_id}} called={{system__called_number}} "
                 "conv={{system__conversation_id}}")


@dataclass
class Session:
    handle: str
    conversation_id: str | None = None
    outbox: list[str] = field(default_factory=list)
    last: float = field(default_factory=time.monotonic)
    turns: int = 0
    last_said: str = ""          # what this call said last (to tell our own echo from the caller)
    screened: int = 0            # times we answered a call-screening prompt on this call


class Voice:
    def __init__(self, store, messenger, outbound, settings, http: httpx.AsyncClient | None = None):
        self.store, self.messenger, self.outbound, self.settings = store, messenger, outbound, settings
        self.sessions: dict[str, Session] = {}
        self.http = http
        self.calls: list[dict] = []  # this process's outbound calls, newest last (GET /calls)
        messenger.voice = self

    # ---------- the capture (Messenger asks us before texting) ----------
    def live(self, handle: str | None) -> Session | None:
        if handle is None:
            return None
        s = self.sessions.get(handle)
        if s is not None and time.monotonic() - s.last > SESSION_IDLE_S:
            self.end(handle, reason="idle")
            return None
        return s

    def capture(self, handle: str | None, text: str) -> bool:
        """True: a call is live for this phone, so the text is said there instead of texted."""
        s = self.live(handle)
        if s is None:
            return False
        s.outbox.append(text)
        return True

    def open(self, handle: str, conversation_id: str | None = None) -> Session:
        s = self.sessions.get(handle)
        if s is None or (conversation_id and s.conversation_id and s.conversation_id != conversation_id):
            # a new call: what the last one didn't get to say is still owed to them
            s = self.sessions[handle] = Session(handle, conversation_id, outbox=s.outbox if s else [])
        s.conversation_id = s.conversation_id or conversation_id
        s.last = time.monotonic()
        return s

    def end(self, handle: str, reason: str) -> list[str]:
        s = self.sessions.pop(handle, None)
        left = s.outbox if s else []
        if left:
            log.warning("call with %s ended (%s) with %d unsaid message(s); they stay in the thread", handle, reason, len(left))
        return left

    # ---------- one turn of a call ----------
    def identify(self, system_text: str) -> tuple[str | None, str | None]:
        """(phone handle, conversation id) from the agent's system prompt. The other end of the call is the
        number that isn't ours (inbound: caller; outbound: called); a registered phone wins."""
        m = CALL_LINE.search(system_text or "")
        if not m:
            return None, None
        ours = normalize_handle(self.settings.photon_voice_number) if self.settings.photon_voice_number else None
        cands = [normalize_handle(x) for x in (m[1], m[2]) if x and "{{" not in x]
        cands = [c for c in cands if c != ours]
        known = [c for c in cands if self.store.phone(handle=c) is not None]
        conv = m[3] if m[3] and "{{" not in m[3] else None
        return (known or cands or [None])[0], conv

    async def turn(self, handle: str, conversation_id: str | None, text: str) -> list[str]:
        """What the caller said → the backend's replies (raw texts, not yet rendered for speech)."""
        s = self.open(handle, conversation_id)
        s.turns += 1
        if self.store.phone(handle=handle) is None:
            if not self.settings.voice_admit_callers:
                return ["This line is for registered drill participants. Goodbye."]
            self.store.upsert_phone(handle, "resident", scenario_id=self.store.meta().get("scenario_id"))
            log.info("admitted caller %s as a resident to be located", handle)
        text = (text or "").strip()
        sim = _similar(text, s.last_said) if text and s.last_said else 0.0
        if sim >= ECHO_EXACT or (sim >= ECHO_SIMILAR and not _answers(text)):
            log.info("call %s: ignored our own echo %r", handle, text[:60])
            return None  # say nothing
        if text and SCREENING.search(text) and s.screened < 2:
            s.screened += 1
            s.last_said = WHO_WE_ARE
            return [WHO_WE_ARE]  # not a message from the resident: the thread doesn't change
        if text:
            await self.messenger.phone_inbound(handle, text)
        elif not s.outbox:  # the call started with no first words from them: say where things stand
            await self.say_situation(handle)
        out, s.outbox = s.outbox, []
        s.last = time.monotonic()
        s.last_said = render_all(out) or s.last_said
        return out

    async def say_situation(self, handle: str) -> None:
        """Put what the thread would say right now into the call (captured like any text)."""
        phone = self.store.phone(handle=handle)
        thread = phone_thread(self.store, phone) if phone else None
        if thread is None:
            if phone is None or unplaced(self.store, phone):
                await self.messenger.send_to_phone(handle, WHERE)
            return
        text = await self.outbound.situation(thread) if self.outbound is not None else None
        if text:
            await self.messenger.send_message(thread, text, self.store.meta().get("plan_version"))

    # ---------- outbound calls ----------
    async def call(self, handle: str, reason: str = "console") -> dict:
        """Dial a registered phone through ElevenLabs (Photon number). The first thing said is what the thread
        would say now. Returns ElevenLabs' answer (conversation_id, sip_call_id) or raises."""
        st = self.settings
        if not (st.elevenlabs_api_key and st.elevenlabs_agent_id and st.elevenlabs_phone_number_id):
            raise RuntimeError("ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID / ELEVENLABS_PHONE_NUMBER_ID missing in residents/.env")
        handle = normalize_handle(handle)
        if self.store.phone(handle=handle) is None:
            raise ValueError(f"{handle} is not a registered phone")
        s = self.open(handle)
        if not s.outbox:
            await self.say_situation(handle)
        opening = render_all(s.outbox)
        first = f"{OPENER} {opening}".strip()
        body = {"agent_id": st.elevenlabs_agent_id, "agent_phone_number_id": st.elevenlabs_phone_number_id,
                "to_number": handle,
                "conversation_initiation_client_data": {
                    "dynamic_variables": {"opening": opening or WHERE},
                    "conversation_config_override": {"agent": {"first_message": first}}}}
        http = self.http or httpx.AsyncClient(timeout=30)
        try:
            r = await http.post(f"{ELEVENLABS}/v1/convai/sip-trunk/outbound-call", json=body,
                                headers={"xi-api-key": st.elevenlabs_api_key})
            if r.status_code >= 400 and "override" in r.text.lower():
                # the agent doesn't allow a first-message override: dial anyway, the opening is said on
                # the caller's first turn (it stays in the outbox)
                body["conversation_initiation_client_data"].pop("conversation_config_override")
                r = await http.post(f"{ELEVENLABS}/v1/convai/sip-trunk/outbound-call", json=body,
                                    headers={"xi-api-key": st.elevenlabs_api_key})
                said = False
            else:
                said = True
            res = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"detail": r.text}
            if r.status_code >= 400 or not res.get("success", True):
                self.end(handle, reason="dial failed")
                raise RuntimeError(f"ElevenLabs outbound call failed ({r.status_code}): {res}")
        finally:
            if self.http is None:
                await http.aclose()
        if said:
            s.outbox = []
        s.conversation_id = res.get("conversation_id") or s.conversation_id
        rec = {"handle": handle, "reason": reason, "conversation_id": res.get("conversation_id"),
               "sip_call_id": res.get("sip_call_id"), "opening": first, "t_s": float(self.store.meta().get("t_s", 0.0)),
               "wall": time.time()}
        self.calls.append(rec)
        log.info("calling %s (%s): %s", handle, reason, res.get("conversation_id"))
        return rec


def _similar(a: str, b: str) -> float:
    """Share of the caller's words that are words we just said (a transcript of our own voice scores ~1)."""
    wa = re.findall(r"[a-z']+", a.lower())
    wb = set(re.findall(r"[a-z']+", b.lower()))
    return sum(w in wb for w in wa) / len(wa) if len(wa) >= 6 else 0.0


def _answers(text: str) -> bool:
    """Does it carry an answer (yes / no / done / a need / a street)? Then it's the caller, never an echo."""
    from . import fallback
    ex = fallback.parse(text)
    return bool(ex and any(f.kind not in ("question", "other") for f in ex.facts)) or bool(fallback.STREET.search(text.lower()))


# ---------- the voice app: the only thing reachable through the tunnel ----------
def _content(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""


def _chunk(cid: str, delta: dict, finish: str | None = None) -> str:
    return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "ember", "choices": [{"index": 0, "delta": delta,
                                                                 "finish_reason": finish}]}) + "\n\n"


def create_voice_app(get_voice, token: str) -> FastAPI:
    """`get_voice()` → the running backend's Voice (shared state, same process). `token`: the secret path."""
    app = FastAPI(title="EMBER voice", docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/{secret}/v1/chat/completions")
    async def completions(secret: str, request: Request):
        if not secrets.compare_digest(secret, token):
            raise HTTPException(404)
        voice = get_voice()
        if voice is None:
            raise HTTPException(503, "EMBER backend not ready")
        body = await request.json()
        msgs = body.get("messages") or []
        system = " ".join(_content(m) for m in msgs if m.get("role") == "system")
        said = next((_content(m) for m in reversed(msgs) if m.get("role") == "user"), "")
        handle, conv = voice.identify(system)
        cid = f"chatcmpl-{secrets.token_hex(6)}"
        if handle is None:
            log.error("voice turn without a caller id; is the agent's system prompt set? (%r)", system[:120])
            reply_now = "Sorry, I can't tell which phone this is. Please call again later."
            task = None
        else:
            task = asyncio.create_task(voice.turn(handle, conv, said))
            reply_now = None

        async def answer() -> str:
            if task is None:
                return reply_now
            got = await task
            return "" if got is None else (render_all(got) or "Okay.")

        if not body.get("stream"):
            text = await answer()
            return JSONResponse({"id": cid, "object": "chat.completion", "created": int(time.time()), "model": "ember",
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                              "finish_reason": "stop"}]})

        async def stream():
            yield _chunk(cid, {"role": "assistant"})
            if task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(task), FILLER_AFTER_S)
                except asyncio.TimeoutError:
                    yield _chunk(cid, {"content": FILLER})
            texts = await task if task is not None else None
            text = ("" if texts is None else (render_all(texts) or "Okay.")) if task is not None else reply_now
            try:
                if text:
                    yield _chunk(cid, {"content": text})
                yield _chunk(cid, {}, "stop")
                yield "data: [DONE]\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                if texts and handle:  # they talked over us: say it on the next turn
                    s = voice.sessions.get(handle)
                    if s is not None:
                        s.outbox[:0] = texts
                raise

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


__all__ = ["Voice", "create_voice_app", "render", "SYSTEM_PROMPT", "OPENER"]


# ---------- ElevenLabs agent settings (the tunnel URL changes every run) ----------
async def configure_agent(settings, server_url: str, http: httpx.AsyncClient | None = None) -> tuple[bool, str]:
    """Point the ElevenLabs agent's Custom LLM at `server_url` and set the system prompt that carries the caller
    id. Read-modify-write: keeps whatever else the custom_llm block holds (model id, secret); verified by a
    second read. Returns (ok, detail)."""
    url = f"{ELEVENLABS}/v1/convai/agents/{settings.elevenlabs_agent_id}"
    h = {"xi-api-key": settings.elevenlabs_api_key}
    client = http or httpx.AsyncClient(timeout=30)
    try:
        r = await client.get(url, headers=h)
        if r.status_code >= 400:
            return False, f"reading the agent failed ({r.status_code}): {r.text[:300]}"
        prompt = ((r.json().get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}
        custom = dict(prompt.get("custom_llm") or {})
        custom["url"] = server_url
        custom.setdefault("model_id", "ember")
        body = {"conversation_config": {"agent": {"prompt": {"llm": "custom-llm", "custom_llm": custom,
                                                             "prompt": SYSTEM_PROMPT}}}}
        r = await client.patch(url, headers=h, json=body)
        if r.status_code >= 400:
            return False, f"updating the agent failed ({r.status_code}): {r.text[:400]}"
        # let outbound calls open with their own first message (best effort; the call works without it)
        await client.patch(url, headers=h, json={"platform_settings": {"overrides": {"conversation_config_override": {
            "agent": {"first_message": True}}}}})
        r = await client.get(url, headers=h)
        got = ((((r.json().get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}).get("custom_llm") or {})
        if got.get("url") != server_url:
            return False, f"the agent still points at {got.get('url')!r}"
        return True, "agent updated"
    finally:
        if http is None:
            await client.aclose()


async def start_tunnel(port: int, timeout_s: float = 40.0):
    """`cloudflared tunnel --url` (a free quick tunnel, new URL each run) → (process, https URL)."""
    proc = await asyncio.create_subprocess_exec(
        "cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    found = re.compile(rb"https://[a-z0-9-]+\.trycloudflare\.com")
    deadline = time.monotonic() + timeout_s
    url = None
    while url is None and time.monotonic() < deadline:
        try:
            line = await asyncio.wait_for(proc.stderr.readline(), max(0.1, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            break
        if not line:
            break
        if (m := found.search(line)):
            url = m[0].decode()

    async def drain():  # keep reading so cloudflared never blocks on a full pipe
        tl = logging.getLogger("residents.tunnel")
        while (line := await proc.stderr.readline()):
            tl.info(line.decode(errors="replace").rstrip())
    asyncio.create_task(drain())
    if url is None:
        proc.terminate()
        raise RuntimeError("cloudflared didn't print a tunnel URL (is it installed? `brew install cloudflared`)")
    return proc, url
