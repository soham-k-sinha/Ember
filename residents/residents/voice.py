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
- Outbound calls (`call(handle, reason)`): the first message says who is calling and why in one sentence, then the
  one thing the thread most needs from them now (the step, the offer, or our question); ElevenLabs dials with it.
- Proactive calls (D80, `check`, on every new plan and clock move): EMBER calls the most at-risk residents itself,
  earliest deadline first, at most VOICE_MAX_CONCURRENT at once, at most once per (phone, reason) per COOLDOWN_S:
  no reply to an open offer / step / question while the water is close, a mobility or medical need not yet
  confirmed, or a pickup that changed since they last wrote (one call per wait, one per change). When a call is
  over the thread texts them where things stand, so the conversation carries on by text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import secrets
import time
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .db import thread_key
from .messaging import Messenger
from .speech import render, render_all
from .threads import normalize_handle, phone_thread, unplaced

log = logging.getLogger("residents.voice")

ELEVENLABS = "https://api.elevenlabs.io"
OPENER = "Hi, this is EMBER, an automated assistant for the flood drill"
INBOUND = f"{OPENER}. How can I help?"   # the agent's first message when someone calls us
WHY = {"no_reply": "calling because the water reaches your street in about {mins} minutes and we haven't heard back",
       "mobility": "calling about your wheelchair-accessible pickup",
       "medical": "calling about your pickup, because of the medical needs you told us about",
       "pickup_changed": "calling because your pickup has changed",
       "new_offer": "calling with a new pickup for you, because {why}",
       "undelivered": "calling because our text to you didn't go through",
       "console": "calling about your evacuation plan"}
PROMISE = "I'll text you this too."
# What a caller says that is about the call, not a message for the thread; the call answers it itself:
# "hello?" / "sorry, what?" as they pick up our call: a short hello, then the one thing we need, never the opener again
GREETING = re.compile(r"^(\W*(hello|hi|hey)( there)?)+\W*$", re.I)
# "sorry, what?" later on: the last thing we said, again
AGAIN = re.compile(r"^\W*(sorry|pardon|huh|excuse me|what)\W*(what|was that|did you say)?\W*\?", re.I)
# "thank you, dear" / "okay, got it" / "bye": the call is winding down
CLOSING = re.compile(r"^(?=.*\b(thank|bye|got it|will do|take care))(\W*(ok(ay)?|great|alright|all right|perfect|"
                     r"thanks?|thank you|so much|very much|dear|bye|good ?bye|got it|will do|take care|you too))+\W*$", re.I)
BYE = "I'm texting you all of this now. Take care."
FOLLOW_UP = "As promised, here's your plan in writing."
MISSED = "We just tried to call you."
WHERE = "Where are you right now? Tell me your street address or the nearest intersection."
FILLER = "One moment... "        # ElevenLabs' advice for slow turns: an ellipsis + space, said while we work
FILLER_AFTER_S = 1.2
SESSION_IDLE_S = 300.0           # a call with no turn for this long is over (its leftovers go back to text)
# Phone call screening (iPhone "Screen Unknown Callers", Google Call Screen) answers first and asks who's calling
# and why; answering that (once) is what gets the call put through. A person asking "who is this?" gets the same.
SCREENING = re.compile(r"\b(stay on the line|record (your|it)\b|recorded\b|reason for (your )?call|screening service|"
                       r"see if (this person|they)( is| are|'re)? (is )?available|i'll see if|who('s| is) (calling|this)|state your name|"
                       r"leave (a|your) (message|name))", re.I)
WHO_WE_ARE = "It's EMBER, an automated assistant for the HackHarvard flood drill; this is a drill, not a real emergency."
# someone frightened gets a calm word before the plan (once a call)
PANIC = re.compile(r"\b(oh my god|omg|scared|terrified|panick?ing|hurry|help me|what do i do)\b", re.I)
CALM = "I'm here with you; we'll go one step at a time."
NO_REPLY_S = 180.0               # an open offer / step / question unanswered this long (sim-s), not called about yet …
NEAR_S = 45 * 60.0               # … while their deadline is this close: call
CHANGED_S = 30 * 60.0            # their pickup changed this recently (they haven't written or been called since): call
QUIET_S = 60.0                   # never call someone in the middle of texting us
COOLDOWN_S = 15 * 60.0           # one call per (phone, reason) per this many sim-s
REAP_EVERY_S = 5.0               # ask ElevenLabs which calls are over at most this often (wall-s)
ECHO_SIMILAR = 0.7               # this close to what we just said, and no answer in it: our own voice coming back
ECHO_EXACT = 0.85                # this close: our own voice, whatever it contains (our help text lists "yes", "done")
CALL_LINE = re.compile(r"caller=(\S*)\s+called=(\S*)\s+conv=(\S*)")
SYSTEM_PROMPT = ("EMBER-CALL caller={{system__caller_id}} called={{system__called_number}} "
                 "conv={{system__conversation_id}}")


@dataclass
class Session:
    handle: str
    conversation_id: str | None = None
    reason: str = "inbound"      # inbound | console | no_reply | mobility | pickup_changed | undelivered
    started_t_s: float = 0.0
    reports_at: int = 0          # reports before the call: the ones after it are what the call changed
    outbox: list[str] = field(default_factory=list)
    last: float = field(default_factory=time.monotonic)
    turns: int = 0
    last_said: str = ""          # what this call said last (to tell our own echo from the caller)
    screened: int = 0            # times we said again who we are (call screening, "who is this?", "hello?")
    promised: bool = False       # told them a text follows
    calmed: bool = False         # said CALM


class Voice:
    def __init__(self, store, messenger, outbound, settings, http: httpx.AsyncClient | None = None):
        self.store, self.messenger, self.outbound, self.settings = store, messenger, outbound, settings
        self.sessions: dict[str, Session] = {}
        self.http = http
        self.recent: list[dict] = []  # this process's finished calls, newest last (GET /calls)
        self._reaped = 0.0
        messenger.voice = self

    def _t_s(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    def configured(self) -> bool:
        st = self.settings
        return bool(st.elevenlabs_api_key and st.elevenlabs_agent_id and st.elevenlabs_phone_number_id)

    async def _eleven(self, method: str, path: str, **kw) -> httpx.Response:
        http = self.http or httpx.AsyncClient(timeout=30)
        try:
            return await http.request(method, ELEVENLABS + path, headers={"xi-api-key": self.settings.elevenlabs_api_key}, **kw)
        finally:
            if self.http is None:
                await http.aclose()

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

    def open(self, handle: str, conversation_id: str | None = None, reason: str = "inbound") -> Session:
        s = self.sessions.get(handle)
        owed = []
        if s is not None and conversation_id and s.conversation_id and s.conversation_id != conversation_id:
            owed = self.end(handle, reason="next call").outbox  # what the last call didn't get to say is still owed
            s = None
        if s is None:
            s = self.sessions[handle] = Session(handle, conversation_id, reason, self._t_s(), len(self.store.reports()),
                                                outbox=owed)
        s.conversation_id = s.conversation_id or conversation_id
        s.last = time.monotonic()
        return s

    def end(self, handle: str, reason: str) -> Session | None:
        """The call is over (or never started): it joins `recent` with what it changed."""
        s = self.sessions.pop(handle, None)
        if s is None:
            return None
        if s.outbox:
            log.warning("call with %s ended (%s) with %d unsaid message(s); they stay in the thread", handle, reason,
                        len(s.outbox))
        if s.turns or s.reason != "inbound":  # not the drill's capture while it decides whether to call
            hid = self._household_id(handle)
            kinds = {r["kind"] for r in self.store.reports()[s.reports_at:] if hid is not None and r.get("household_id") == hid}
            outcome = ("failed" if reason == "dial failed" else "no_answer" if not s.turns else
                       "confirmed" if "confirm" in kinds else "declined" if "reject" in kinds else
                       "updated" if "need" in kinds else "talked")
            self.recent.append({"handle": handle, "household_id": hid, "reason": s.reason, "outcome": outcome,
                                "turns": s.turns, "ended_t_s": self._t_s()})
        return s

    async def hang_up(self, handle: str) -> None:
        """The call is over: the thread texts them where things stand, so the conversation goes on by text."""
        s = self.end(handle, reason="hung up")
        if s is not None:
            await self.say_situation(handle, lead=FOLLOW_UP if s.turns else MISSED)

    def _household_id(self, handle: str) -> int | None:
        phone = self.store.phone(handle=handle)
        return (phone_thread(self.store, phone) or {}).get("household_id") if phone else None

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
        intro = (WHO_WE_ARE if SCREENING.search(text) and s.screened < 2 else f"{OPENER}." if s.turns == 1
                 and s.reason != "inbound" and (GREETING.match(text) or AGAIN.match(text)) else None)
        if intro:  # who we are, then the one thing we need from them
            s.screened += 1
            if not s.outbox:
                await self.say_next(handle, s.reason)
            s.outbox.insert(0, intro)
        elif text and AGAIN.match(text) and s.last_said:
            s.outbox.insert(0, s.last_said)
        elif text and CLOSING.match(text):
            s.outbox.append(("You're welcome. " if "thank" in text.lower() else "Great. ") + BYE)
            s.promised = True
        elif text:
            await self.messenger.phone_inbound(handle, text)
            if PANIC.search(text) and not s.calmed:
                s.outbox.insert(0, CALM)
                s.calmed = True
        elif not s.outbox:  # the call started with no first words from them: say where things stand
            await self.say_situation(handle)
        out, s.outbox = s.outbox, []
        if not s.promised and any("Step " in t for t in out):  # they have something to do: it's coming in writing
            out.append(PROMISE)
            s.promised = True
        s.last = time.monotonic()
        s.last_said = render_all(out) or s.last_said
        return out

    async def say_situation(self, handle: str, lead: str = "", brief: bool = False) -> None:
        """What the thread would say right now: said on the call while one is live (captured), else texted."""
        phone = self.store.phone(handle=handle)
        thread = phone_thread(self.store, phone) if phone else None
        if thread is None:
            if phone is None or unplaced(self.store, phone):
                await self.messenger.send_to_phone(handle, f"{lead} {WHERE}".strip())
            return
        text = await self.outbound.situation(thread, brief) if self.outbound is not None else None
        if text:
            await self.messenger.send_message(thread, f"{lead} {text}".strip(), self.store.meta().get("plan_version"))

    # ---------- outbound calls ----------
    def hello(self, handle: str, reason: str) -> str:
        """Who is calling and why, in one sentence."""
        hid = self._household_id(handle)
        h = next((x for x in self.store.households() if x["household_id"] == hid), {})
        needs = h["needs"] if isinstance(h.get("needs"), dict) else {}
        if reason == "mobility" and not (needs.get("mobility") or needs.get("accessible_vehicle")):
            reason = "medical"
        thread = {"household_id": hid}
        why = WHY.get(reason, WHY["console"])
        if reason == "no_reply":  # only called with a deadline
            why = why.format(mins=max(1, round((self.outbound.water_s(thread) - self._t_s()) / 60)))
        elif reason == "pickup_changed":  # a confirmed pickup's update says why itself; a new offer says it here
            view = self.store.plan_view() or {}
            a = self.outbound.instruction_for(view, thread, exclude=self.outbound.rejected(thread_key(thread)))
            if a is not None and not self.outbound.confirmed(a):
                why = WHY["new_offer"].format(why=self.outbound.news(view["version"], thread))
        return f"{OPENER}, {why}."

    async def say_next(self, handle: str, reason: str) -> None:
        """The one thing the thread most needs them to hear now (a call says one thing at a time): their pickup as it
        is now, if it changed, else the step they're on, the offer or where they stand, else our question."""
        phone = self.store.phone(handle=handle)
        thread = phone_thread(self.store, phone) if phone else None
        view = self.store.plan_view()  # the simulated ETAs, the same ones the texts and "what changed?" say
        a = None
        if reason == "pickup_changed" and thread is not None and view:
            a = self.outbound.instruction_for(view, thread, exclude=self.outbound.rejected(thread_key(thread)))
        if a is not None:  # "Update: Callender Street was reported blocked, so Van 2 is now arriving in about 40 min." / the new offer
            await self.messenger.send_message(thread, self.outbound.compose(a, thread, self._t_s(), view["version"]),
                                              view["version"], a["id"])
        else:
            await self.say_situation(handle, brief=True)

    async def opening(self, handle: str, reason: str) -> str:
        """A call's first words: who and why in one sentence, then the one thing they most need to hear."""
        s = self.open(handle, reason=reason)
        if not s.outbox:
            await self.say_next(handle, reason)
        return f"{self.hello(handle, reason)} {render_all(s.outbox)}".strip()

    async def call(self, handle: str, reason: str = "console") -> dict:
        """Dial a registered phone through ElevenLabs (Photon number). Returns ElevenLabs' answer
        (conversation_id, sip_call_id) and the opening, or raises."""
        if not self.configured():
            raise RuntimeError("ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID / ELEVENLABS_PHONE_NUMBER_ID missing in residents/.env")
        st = self.settings
        handle = normalize_handle(handle)
        if self.store.phone(handle=handle) is None:
            raise ValueError(f"{handle} is not a registered phone")
        first = await self.opening(handle, reason)
        s = self.sessions[handle]
        body = {"agent_id": st.elevenlabs_agent_id, "agent_phone_number_id": st.elevenlabs_phone_number_id,
                "to_number": handle,
                "conversation_initiation_client_data": {
                    "dynamic_variables": {"opening": first},
                    "conversation_config_override": {"agent": {"first_message": first}}}}
        r = await self._eleven("POST", "/v1/convai/sip-trunk/outbound-call", json=body)
        said = not (r.status_code >= 400 and "override" in r.text.lower())
        if not said:
            # the agent doesn't allow a first-message override: dial anyway, the opening is said on the caller's
            # first turn (it stays in the outbox)
            body["conversation_initiation_client_data"].pop("conversation_config_override")
            r = await self._eleven("POST", "/v1/convai/sip-trunk/outbound-call", json=body)
        res = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"detail": r.text}
        if r.status_code >= 400 or not res.get("success", True):
            self.end(handle, reason="dial failed")
            raise RuntimeError(f"ElevenLabs outbound call failed ({r.status_code}): {res}")
        if said:
            s.outbox = []
            s.last_said = first
        s.conversation_id = res.get("conversation_id") or s.conversation_id
        log.info("calling %s (%s): %s", handle, reason, res.get("conversation_id"))
        return {"handle": handle, "reason": reason, "conversation_id": res.get("conversation_id"),
                "sip_call_id": res.get("sip_call_id"), "opening": first}

    # ---------- proactive calls (D80) ----------
    async def check(self, *_) -> list[dict]:
        """Plan and clock hook: call whoever needs it most, earliest deadline first, within the concurrency cap."""
        if not self.configured():
            return []
        await self.reap()
        free = self.settings.voice_max_concurrent - self._live_count()
        now = self._t_s()
        due = sorted(d for p in self.store.phones() if (d := self._due(p, now)))
        placed = []
        for _, handle, reason in due[:max(free, 0)]:
            self.store.kv_set(f"call:{handle}:{reason}", str(now))  # a failed dial isn't retried every tick either
            try:
                placed.append(await self.call(handle, reason))
            except (RuntimeError, ValueError, httpx.HTTPError) as e:
                log.warning("proactive call to %s (%s) failed: %s", handle, reason, e)
        return placed

    async def undelivered(self, handle: str, text: str) -> dict | None:
        """D90: a text Photon refused after its retries is said on a call instead (Messenger tells us). Same rules
        as D80: a resident's real number, no call already on, VOICE_MAX_CONCURRENT, COOLDOWN_S per (phone, reason)."""
        if not self.configured() or not handle.startswith("+") or self.live(handle) is not None:
            return None
        phone = self.store.phone(handle=handle)
        if phone is None or phone["role"] != "resident":
            return None
        now = self._t_s()
        last = self.store.kv_get(f"call:{handle}:undelivered")
        if last is not None and now - float(last) < COOLDOWN_S:
            return None
        if self._live_count() >= self.settings.voice_max_concurrent:
            return None
        self.store.kv_set(f"call:{handle}:undelivered", str(now))
        self.open(handle, reason="undelivered").outbox.append(text)  # the opening says this text, nothing else
        try:
            return await self.call(handle, "undelivered")
        except (RuntimeError, ValueError, httpx.HTTPError) as e:
            self.end(handle, reason="dial failed")
            log.warning("call-back to %s for an undelivered text failed: %s", handle, e)
            return None

    def _live_count(self) -> int:
        return sum(1 for h in list(self.sessions) if self.live(h))

    def _due(self, phone: dict, now: float) -> tuple[float, str, str] | None:
        """(deadline, handle, reason) when this resident should get a call now, else None."""
        handle = phone["handle"]
        thread = phone_thread(self.store, phone)
        if phone["role"] != "resident" or not handle.startswith("+") or thread is None or self.live(handle):
            return None
        h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), None)
        if h is None or h["status"] in ("picked_up", "safe"):
            return None
        key = thread_key(thread)
        msgs = self.store.thread_messages(key)
        ins = [i for i, m in enumerate(msgs) if m["direction"] == "in"]
        last_in = msgs[ins[-1]]["t_s"] if ins else None
        # since when we've been waiting: our first message after their last one
        waiting = next((m["t_s"] for m in msgs[ins[-1] + 1 if ins else 0:] if m["direction"] == "out"), None)
        if (last_in is None and not Messenger.opted_in(phone)) or (last_in is not None and now - last_in < QUIET_S):
            return None  # they never wrote to us (no call out of the blue), or they're writing right now
        view = self.store.plan_view() or {}
        a = self.outbound.instruction_for(view, thread, exclude=self.outbound.rejected(key))
        offered = a is not None and not self.outbound.confirmed(a)
        asked = any(q["to"] == thread and self.store.kv_get(f"asked:{q['id']}") for q in view.get("info_requests", []))
        stepping = self.outbound.guide is not None and self.outbound.guide.awaiting_done(thread)
        changed = json.loads(self.store.kv_get(f"instr:{key}") or "{}").get("changed_t_s")
        called = max((float(v) for v in self.store.kv_prefix(f"call:{handle}:").values()), default=None)
        needs = h["needs"] if isinstance(h.get("needs"), dict) else {}
        deadline = h.get("deadline_s")
        for reason, hit in (  # a change and a wait get one call each; a need not yet confirmed, one per cooldown
                ("pickup_changed", changed is not None and now - changed <= CHANGED_S
                 and (last_in is None or last_in < changed) and (called is None or called < changed)),
                ("mobility", offered and any(needs.get(k) for k in ("mobility", "accessible_vehicle", "medical"))),
                ("no_reply", (offered or asked or stepping) and deadline is not None and deadline - now <= NEAR_S
                 and waiting is not None and now - waiting >= NO_REPLY_S and (called is None or called < waiting))):
            last_call = self.store.kv_get(f"call:{handle}:{reason}")
            if hit and (last_call is None or now - float(last_call) >= COOLDOWN_S):
                return (math.inf if deadline is None else deadline), handle, reason
        return None

    async def reap(self) -> None:
        """Calls ElevenLabs says are over end here, each with its follow-up text."""
        if time.monotonic() - self._reaped < REAP_EVERY_S:
            return
        self._reaped = time.monotonic()
        for handle, s in list(self.sessions.items()):
            if s.conversation_id is None:
                continue
            try:
                r = await self._eleven("GET", f"/v1/convai/conversations/{s.conversation_id}")
                status = r.json().get("status") if r.status_code < 400 else None
            except (httpx.HTTPError, ValueError) as e:
                log.info("couldn't read call %s: %s", s.conversation_id, e)
                continue
            if status in ("done", "failed"):
                await self.hang_up(handle)

    def calls_view(self) -> dict:
        """GET /calls: the calls in progress, and the finished ones newest first."""
        live = [{"handle": h, "household_id": self._household_id(h), "reason": s.reason, "started_t_s": s.started_t_s,
                 "turns": s.turns} for h, s in list(self.sessions.items()) if self.live(h)]
        return {"live": live, "recent": self.recent[::-1][:20]}


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
    """Point the ElevenLabs agent's Custom LLM at `server_url`, set the system prompt that carries the caller id
    and the first message of a call in (who we are). Read-modify-write: keeps whatever else the custom_llm block holds (model id, secret); verified by a
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
        body = {"conversation_config": {"agent": {"first_message": INBOUND, "prompt": {
            "llm": "custom-llm", "custom_llm": custom, "prompt": SYSTEM_PROMPT}}}}
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
