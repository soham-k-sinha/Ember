"""Phone calls (D74), the primary channel since D100: in a disaster people answer a ringing phone, not a text.
ElevenLabs runs the call (speech-to-text, text-to-speech, turn-taking, the Photon SIP number); EMBER's backend is its
"Custom LLM", so every sentence on the call is ours, never generated.

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
- ElevenLabs re-sends a turn while its speech-to-text revises it ("I'm done." ×3, "A walker." → "A walker. I need my
  needle."). Per call, at the turn boundary: the same words again within REPEAT_S get the same reply without being
  processed again; words that extend or mostly repeat the last turn within REVISE_S replace it (their facts count, a
  yes / no in them doesn't count twice). Nothing moves a step on but the plan's clock, so a re-sent "done" can't skip one.

When EMBER calls (D100, replacing D80's "no reply" calls; never a call just to get a yes):
- first contact: a player who joins is called with the simulation notice, where they live and when the water comes,
  then the one combined question (how many people; anyone needing a wheelchair or medical help);
- the pickup instruction, a pickup that changed, and "the vehicle is 2 minutes away, come to the door now".
Each of those `ring`s the phone: the call is queued and what the thread says meanwhile waits in its outbox. `check`
(every plan, clock move and VOICE_POLL_S) dials queued calls earliest deadline first, at most VOICE_MAX_CONCURRENT at
once. Not answered: one retry after RETRY_S, then the same news by text (time-critical news by text at once). Answered:
one short text follows with the instruction in writing. Anyone can call the voice number: an unknown caller becomes the
next player (D89's placement, same MAX_PLAYERS cap) with no texting needed. A phone's first call opens with the one
simulation notice; later calls just say who's calling (D100: no "drill" talk, nothing official).
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

from .briefing import ASK_NEEDS
from .db import PhoneConflict
from .fallback import NUM
from .messaging import DrillFull
from .photon import PhotonError
from .speech import render, render_all
from .threads import normalize_handle, phone_thread, unplaced

log = logging.getLogger("residents.voice")

ELEVENLABS = "https://api.elevenlabs.io"
DISCLOSURE = "This is EMBER, an automated assistant in a live flood simulation."  # a phone's first call only (D100)
HI = "Hi, it's EMBER."                                                             # every call after that
INBOUND = f"{DISCLOSURE} How can I help?"   # the agent's first message when someone calls us
UNDELIVERED = "Our text to you didn't go through, so I'm calling with it."
# What a caller says that is about the call, not a message for the thread; the call answers it itself:
# "hello?" / "sorry, what?" as they pick up our call: a short hello, then the one thing we need, never the opener again
GREETING = re.compile(r"^(\W*(hello|hi|hey)( there)?)+\W*$", re.I)
# "sorry, what?" later on: the last thing we said, again
AGAIN = re.compile(r"^\W*(sorry|pardon|huh|excuse me|what)\W*(what|was that|did you say)?\W*\?", re.I)
# "thank you, dear" / "okay, got it" / "bye": the call is winding down
CLOSING = re.compile(r"^(?=.*\b(thank|bye|got it|will do|take care))(\W*(oh|ok(ay)?|great|alright|all right|perfect|"
                     r"thanks?|thank you|so much|very much|dear|bye|good ?bye|got it|will do|take care|you too))+\W*$", re.I)
# "okay" / "um, sounds good to me" / "coming" once they know their pickup: the instruction landed, so we close after
# answering it (a short turn with one of these and no question)
ACK = re.compile(r"\b(ok(ay)?|sounds good|got it|alright|all right|perfect|great|cool|understood|will do|thanks?|"
                 r"thank you|yes|yeah|sure|done|coming|on (my|our) way)\b", re.I)
BYE = "I'll text you all of this now. Take care."
STILL_THERE = "Are you still there?"
# asking us to send help that a simulation can't send: say so first, every time
EMERGENCY = re.compile(r"\b(police|cops?|911|ambulance|paramedics?|fire ?(fighters?|department|truck)|"
                       r"send (someone|somebody|help)|real emergency)\b", re.I)
NOT_REAL = "This is a simulation, so I can't send anyone. If anyone is in real danger, hang up and call 911."
FOLLOW_UP = "From our call:"
MISSED = "We just tried to call you."
WHERE = "Where are you right now? Tell me your street address or the nearest intersection."
CLOSED = "This line is for people taking part in the EMBER flood simulation. Goodbye."
FULL_CALL = "Thanks for calling. The flood simulation is full right now; you can watch it on the big screen. Goodbye."
BUSY = "Sorry, I couldn't add you just now. Please call again in a minute."
FILLER = "One moment... "        # ElevenLabs' advice for slow turns: an ellipsis + space, said while we work
FILLER_AFTER_S = 1.2
SESSION_IDLE_S = 300.0           # a call with no turn for this long is over (its leftovers go back to text)
# Phone call screening (iPhone "Screen Unknown Callers", Google Call Screen) answers first and asks who's calling
# and why; answering that (once) is what gets the call put through. A person asking "who is this?" gets the same.
SCREENING = re.compile(r"\b(stay on the line|record (your|it)\b|recorded\b|reason for (your )?call|screening service|"
                       r"see if (this person|they)( is| are|'re)? (is )?available|i'll see if|who('s| is) (calling|this)|state your name|"
                       r"leave (a|your) (message|name))", re.I)
VOICEMAIL = re.compile(r"\b(?:voice ?mail(?:box)? (?:that )?(?:has not|hasn['’]t|is not|isn['’]t) (?:been )?set up|"
                       r"(?:voice ?mail(?:box)?|mailbox) (?:is |is currently )?full|"
                       r"leave (?:a |your )?message.{0,60}after (?:the |a )?(?:beep|tone)|"
                       r"(?:at|after) (?:the |a )?(?:beep|tone).{0,45}(?:leave|record) (?:a |your )?message|"
                       r"when you have finished recording.{0,35}hang up|"
                       r"your call has been forwarded to.{0,30}voice ?mail)\b", re.I)
WHO_WE_ARE = f"{DISCLOSURE} It's not a real emergency."
# someone frightened gets a calm word before the plan (once a call)
PANIC = re.compile(r"\b(oh my god|omg|scared|terrified|panick?ing|hurry|help me|what do i do)\b", re.I)
CALM = "I'm here with you."
RETRY_S = 120.0                  # an unanswered call is tried once more after this many sim-s (D100) …
RETRY_WALL_S = 60.0              # … or this many wall-s, whichever comes first (the sim clock may be paused)
NO_RETRY = ("soon", "undelivered", "console", "inbound")  # unanswered: by text at once ("2 minutes away" can't wait)
REPEAT_S = 20.0                  # the same words again this soon: ElevenLabs re-sent the turn (D100)
REVISE_S = 10.0                  # words that extend / mostly repeat the last turn this soon: speech-to-text revised it
COUNT_SETTLE_S = 0.35            # bare counts are easy STT partials: let a replacement cancel them before dispatch
BARE_COUNT = re.compile(r"^\W*(?:(?:um+|uh+|erm|er)\W+)?(?:\d+|" + "|".join(NUM) + r")\W*$", re.I)
COOLDOWN_S = 15 * 60.0           # D90: one call-back for an undelivered text per phone per this many sim-s
REAP_EVERY_S = 5.0               # ask ElevenLabs which calls are over at most this often (wall-s)
ECHO_SIMILAR = 0.7               # this close to what we just said, and no answer in it: our own voice coming back
ECHO_EXACT = 0.85                # this close: our own voice, whatever it contains (our help text lists "yes", "done")
CALL_LINE = re.compile(r"caller=(\S*)\s+called=(\S*)\s+conv=(\S*)")
SYSTEM_PROMPT = ("EMBER-CALL caller={{system__caller_id}} called={{system__called_number}} "
                 "conv={{system__conversation_id}}")


@dataclass
class Heard:
    words: list[str]             # what they said, normalized
    at: float                    # when the turn arrived (monotonic)
    reply: list[str] | None      # what we answered


@dataclass
class Session:
    handle: str
    conversation_id: str | None = None
    reason: str = "inbound"      # inbound | console | first_contact | instruction | pickup_changed | soon | undelivered
    started_t_s: float = 0.0
    reports_at: int = 0          # reports before the call: the ones after it are what the call changed
    outbox: list[str] = field(default_factory=list)
    last: float = field(default_factory=time.monotonic)
    turns: int = 0
    last_said: str = ""          # what this call said last (to tell our own echo from the caller)
    last_heard: str = ""         # what the caller said last (shown live on the roster)
    screened: int = 0            # times we said again who we are (call screening, "who is this?", "hello?")
    voicemail: bool = False      # a mailbox greeting is not an answered resident conversation
    calmed: bool = False         # said CALM
    silent: int = 0              # ElevenLabs' "..." turns in a row (no answer before its turn timeout)
    closing: bool = False        # we said goodbye: end the call on this reply
    dialed: bool = False         # ElevenLabs dialed it, or they called us; until then it's queued for a free line
    deadline: float = math.inf   # queue order: their household's flood deadline
    plan_version: int = 0        # the plan when the call was queued; refresh the opening if it changed while waiting
    attempt: int = 1             # 2: the retry of an unanswered call
    arrived: float = 0.0         # when the newest turn arrived (monotonic)
    heard: list[Heard] = field(default_factory=list)  # this call's recent turns (repeats and revisions, D100)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one turn at a time: ElevenLabs may post the next early


class Voice:
    def __init__(self, store, messenger, outbound, settings, http: httpx.AsyncClient | None = None):
        self.store, self.messenger, self.outbound, self.settings = store, messenger, outbound, settings
        self.locator = None  # locate.Locator, set by the app: an unknown caller joins as a player (D100)
        self.sessions: dict[str, Session] = {}
        self.http = http
        self.recent: list[dict] = []  # this process's finished calls, newest last (GET /calls)
        self._reaped = 0.0
        self._check_lock = asyncio.Lock()
        self._dial_lock = asyncio.Lock()
        messenger.voice = self

    def _t_s(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    def configured(self) -> bool:
        st = self.settings
        return bool(st.elevenlabs_api_key and st.elevenlabs_agent_id and st.elevenlabs_phone_number_id)

    def calls_first(self, handle: str) -> bool:
        """D100: this phone hears the moments that matter on a call (a resident's real number, calls configured)."""
        phone = self.store.phone(handle=handle)
        return (self.configured() and self.settings.voice_max_concurrent > 0 and handle.startswith("+")
                and phone is not None and phone["role"] == "resident")

    async def _eleven(self, method: str, path: str, **kw) -> httpx.Response:
        http = self.http or httpx.AsyncClient(timeout=30)
        try:
            return await http.request(method, ELEVENLABS + path, headers={"xi-api-key": self.settings.elevenlabs_api_key}, **kw)
        finally:
            if self.http is None:
                await http.aclose()

    # ---------- the capture (Messenger asks us before texting) ----------
    def live(self, handle: str | None) -> Session | None:
        """The call on, or queued, for this phone (what the thread says goes to it)."""
        if handle is None:
            return None
        s = self.sessions.get(handle)
        if s is not None and s.dialed and time.monotonic() - s.last > SESSION_IDLE_S:
            return None  # reap() closes it asynchronously, including the follow-up or missed-call retry
        return s

    def capture(self, handle: str | None, text: str) -> bool:
        """True: a call is on or queued for this phone, so the text is said there instead of texted."""
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
                                                outbox=owed, plan_version=int(self.store.meta().get("plan_version", 0)))
        s.conversation_id = s.conversation_id or conversation_id
        s.dialed = s.dialed or conversation_id is not None
        s.last = time.monotonic()
        return s

    def end(self, handle: str, reason: str) -> Session | None:
        """The call is over (or never started): it joins `recent` with what it changed."""
        s = self.sessions.pop(handle, None)
        if s is None:
            return None
        if s.outbox and s.turns and not s.voicemail:
            log.warning("call with %s ended (%s) with %d unsaid message(s); they stay in the thread", handle, reason,
                        len(s.outbox))
        if s.turns or s.reason != "inbound":  # not the drill console's capture while it decides whether to call
            hid = self._household_id(handle)
            kinds = {r["kind"] for r in self.store.reports()[s.reports_at:] if hid is not None and r.get("household_id") == hid}
            outcome = ("failed" if reason == "dial failed" else "no_answer" if not s.turns or s.voicemail else
                       "confirmed" if "confirm" in kinds else "declined" if "reject" in kinds else
                       "updated" if "need" in kinds else "talked")
            self.recent.append({"handle": handle, "household_id": hid, "reason": s.reason, "outcome": outcome,
                                "turns": s.turns, "ended_t_s": self._t_s()})
        return s

    async def hang_up(self, handle: str) -> None:
        """The call is over. Answered: the instruction follows in one short text. Not answered: one retry after RETRY_S,
        then the same news by text; time-critical news (and a call that was itself the retry) by text at once."""
        s = self.end(handle, reason="hung up")
        if s is None:
            return
        if s.turns and not s.voicemail:
            await self.say_situation(handle, lead=FOLLOW_UP)
        elif s.attempt == 1 and s.reason not in NO_RETRY:
            self.store.kv_set(f"retry:{handle}", json.dumps({"reason": s.reason, "t_s": self._t_s(), "wall": time.time()}))
        else:
            await self.say_situation(handle, lead=MISSED)

    def _household_id(self, handle: str) -> int | None:
        phone = self.store.phone(handle=handle)
        return (phone_thread(self.store, phone) or {}).get("household_id") if phone else None

    def _settled(self, handle: str) -> bool:
        """We know their needs, so they've heard their pickup: an "okay" now closes the call."""
        hid = self._household_id(handle)
        return any(h["household_id"] == hid and isinstance(h.get("needs"), dict) for h in self.store.households())

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

    async def turn(self, handle: str, conversation_id: str | None, text: str, arrived: float | None = None) -> list[str] | None:
        """What the caller said → the backend's replies (raw texts, not yet rendered for speech). None: say nothing."""
        arrived = time.monotonic() if arrived is None else arrived
        s = self.open(handle, conversation_id)
        s.arrived = max(s.arrived, arrived)
        async with s.lock:  # ElevenLabs may post a revised turn before we've answered the last one
            text = re.sub(r"\b\w+- +(?=\w)", "", (text or "").strip())  # a stutter: "I don't need any med- medical help"
            if _words(text):
                s.last_heard = text
            if text and not _words(text):  # "...": no answer before ElevenLabs' turn timeout
                return await self._silence(s, handle)
            if re.fullmatch(r"(?:um+|uh+|erm|er|hm+|mm+)[\W_]*", text, re.I):
                return None  # hesitation is not a request to repeat the onboarding question
            s.silent = 0
            if BARE_COUNT.fullmatch(text):
                await asyncio.sleep(COUNT_SETTLE_S)
                if s.arrived > arrived:
                    return None  # a newer transcript replaced this short fragment before it became a fact
            kind, prev = self._boundary(s, _words(text), arrived)
            if kind == "repeat":
                log.info("call %s: %r again; same reply, not processed again", handle, text[:60])
                return prev.reply
            out = await self._turn(s, handle, text, revision=kind == "revision")
            s.heard = (s.heard + [Heard(_words(text), arrived, out)])[-8:]
            return out

    async def _silence(self, s: Session, handle: str) -> list[str] | None:
        """ElevenLabs' "..." after its turn timeout: ask once whether they're still there, then close."""
        s.silent += 1
        if s.voicemail:
            return None
        if s.silent > 1:
            s.closing = True
            return [BYE]
        await self.say_situation(handle, brief=True)
        out, s.outbox = [STILL_THERE, *s.outbox], []
        s.last_said = render_all(out)
        return out

    @staticmethod
    def _boundary(s: Session, words: list[str], arrived: float) -> tuple[str | None, Heard | None]:
        """("repeat", that turn): the same words again within REPEAT_S; ("revision", the last turn): they extend it or
        share most of its opening words, within REVISE_S (speech-to-text revising what it heard); else (None, None)."""
        if not words:
            return None, None
        for h in reversed(s.heard):
            if h.words == words and arrived - h.at <= REPEAT_S:
                return "repeat", h
        last = s.heard[-1] if s.heard else None
        if last is not None and arrived - last.at <= REVISE_S and last.words:
            n = next((i for i, (a, b) in enumerate(zip(words, last.words)) if a != b), min(len(words), len(last.words)))
            if n == len(last.words) or n >= max(2, 0.6 * min(len(words), len(last.words))):
                return "revision", last
        return None, None

    async def _turn(self, s: Session, handle: str, text: str, revision: bool) -> list[str] | None:
        s.turns += 1
        if s.voicemail or (s.reason != "inbound" and s.turns <= 2 and VOICEMAIL.search(text)):
            s.voicemail = True
            return None  # a mailbox cannot provide needs; use the normal missed-call retry/text path
        joined = False
        if self.store.phone(handle=handle) is None:  # someone called the number: they join by voice (D100)
            if not self.settings.voice_admit_callers or self.locator is None:
                return [CLOSED]
            try:
                await self.messenger.register_player(handle)
            except DrillFull:
                return [FULL_CALL]
            except (PhoneConflict, ValueError, PhotonError) as e:
                log.warning("couldn't add caller %s: %s", handle, e)
                return [BUSY]
            self.store.kv_set(f"joined:{handle}", "1")  # placed again after a reset, like a player who texted
            self.store.kv_set(f"voiced:{handle}", "1")  # the agent's first words were the notice (INBOUND)
            await self.locator.join_now(self.store.phone(handle=handle))  # where, when, then the plan's question
            log.info("caller %s joined by voice", handle)
            joined = True
            if GREETING.match(text) or ("join" in text.lower() and not _answers(text)):
                text = ""  # a greeting/join request is answered by the introduction; keep any supplied needs
        sim = _similar(text, s.last_said) if text and s.last_said else 0.0
        if sim >= ECHO_EXACT or (sim >= ECHO_SIMILAR and not _answers(text)):
            log.info("call %s: ignored our own echo %r", handle, text[:60])
            return None  # say nothing
        greeted = bool(s.outbox) and s.outbox[0].startswith((DISCLOSURE, HI))  # an opening ElevenLabs didn't say
        intro = (WHO_WE_ARE if SCREENING.search(text) and s.screened < 2 else HI if s.turns == 1 and not greeted
                 and s.reason != "inbound" and (GREETING.match(text) or AGAIN.match(text)) else None)
        if intro:  # who we are, then the one thing we need from them
            s.screened += 1
            if not s.outbox:
                await self.say_next(handle, s.reason)
            s.outbox.insert(0, intro)
        elif text and AGAIN.match(text) and s.last_said:
            s.outbox.insert(0, s.last_said)
        elif text and CLOSING.match(text):
            s.closing = True
            goodbye = BYE
            phone = self.store.phone(handle=handle)
            if self.messenger.photon is not None and (phone is None or not self.messenger.opted_in(phone)):
                goodbye = "Take care."
                if phone and phone.get("assigned_number"):
                    goodbye += f" For a written copy, send JOIN EMBER by iMessage to {phone['assigned_number']}."
            s.outbox.append(("You're welcome. " if "thank" in text.lower() else "Great. ") + goodbye)
        elif text and EMERGENCY.search(text) and not _answers(text):
            await self.say_situation(handle, brief=True)
            s.outbox.insert(0, NOT_REAL)
        elif text:
            if revision:
                self.messenger.revising.add(handle)
            try:
                await self.messenger.phone_inbound(handle, text)
            finally:
                self.messenger.revising.discard(handle)
            if EMERGENCY.search(text) and not any("911" in t for t in s.outbox):
                s.outbox.insert(0, NOT_REAL)
            if ACK.search(text) and len(_words(text)) <= 6 and "?" not in text and self._settled(handle):
                s.outbox.append(BYE)
                s.closing = True
            if joined:
                hid = self._household_id(handle)
                household = next((h for h in self.store.households() if h["household_id"] == hid), {})
                if isinstance(household.get("needs"), dict):
                    # The first answer already supplied the details: don't ask the onboarding question again.
                    s.outbox = [t.replace(ASK_NEEDS, "").strip() for t in s.outbox if t.strip() != ASK_NEEDS]
            if PANIC.search(text) and not s.calmed:
                s.outbox.insert(0, CALM)
                s.calmed = True
        elif not s.outbox:  # the call started with no first words from them: say where things stand
            await self.say_situation(handle)
        if text and not s.outbox and not self._settled(handle):  # "no" / "yep" over our opening: ask again, not "Okay."
            await self.say_next(handle, s.reason)
        out, s.outbox = s.outbox, []
        s.last = time.monotonic()
        s.last_said = render_all(out) or s.last_said
        return out

    def requeue(self, handle: str, texts: list[str], arrived: float) -> None:
        """They talked over a reply (ElevenLabs cancelled it): say it on the next turn, unless a newer turn already
        arrived (a repeat or a revision gets its own reply, so this one would be said twice)."""
        s = self.sessions.get(handle)
        if s is not None and s.arrived <= arrived:
            s.outbox[:0] = texts

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
        """Who is calling: the simulation notice on a phone's first call (D100), "Hi, it's EMBER." after that. First
        contact adds where they live and when the water comes."""
        parts = [HI if self.store.kv_get(f"voiced:{handle}") else DISCLOSURE]
        hid = self._household_id(handle)
        if reason == "first_contact" and hid is not None and self.outbound is not None:
            parts.append(self.outbound.where_when({"household_id": hid}))
        elif reason == "undelivered":
            parts.append(UNDELIVERED)
        return " ".join(p for p in parts if p)

    async def say_next(self, handle: str, reason: str) -> None:
        """The one thing they most need to hear now (a call says one thing at a time): the step they're on, else
        where they stand, else our question."""
        await self.say_situation(handle, brief=True)

    async def opening(self, handle: str, reason: str) -> str:
        """A call's first words: who is calling, then the one thing they most need to hear."""
        s = self.open(handle, reason=reason)
        if not s.dialed:
            s.reason = reason
            if reason in ("first_contact", "instruction", "pickup_changed", "soon") and (
                    s.started_t_s != self._t_s() or s.plan_version != self.store.meta().get("plan_version")):
                # A busy line can outlast a pickup estimate or a whole plan. Say the current step, once.
                s.outbox = []
        if not s.outbox:
            await self.say_next(handle, reason)
        return render_all([self.hello(handle, reason), *s.outbox])

    async def call(self, handle: str, reason: str = "console") -> dict:
        """Dial a registered phone through ElevenLabs (Photon number). Returns ElevenLabs' answer
        (conversation_id, sip_call_id) and the opening, or raises."""
        handle = normalize_handle(handle)
        if handle in self.sessions and self.sessions[handle].dialed and self.live(handle) is None:
            # A failed follow-up may itself request a callback: finish it before taking the dial lock.
            await self.hang_up(handle)
        async with self._dial_lock:
            s = self.live(handle)
            if s is not None and s.dialed:
                return {"handle": handle, "reason": s.reason, "conversation_id": s.conversation_id,
                        "sip_call_id": None, "opening": s.last_said}
            return await self._dial(handle, reason)

    async def _dial(self, handle: str, reason: str) -> dict:
        if not self.configured():
            raise RuntimeError("ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID / ELEVENLABS_PHONE_NUMBER_ID missing in residents/.env")
        st = self.settings
        handle = normalize_handle(handle)
        if self.store.phone(handle=handle) is None:
            raise ValueError(f"{handle} is not a registered phone")
        first = await self.opening(handle, reason)
        s = self.sessions[handle]
        opening_messages = len(s.outbox)
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
            del s.outbox[:opening_messages]  # news captured while the provider was dialing still needs to be said
            s.last_said = first
        else:
            s.outbox.insert(0, self.hello(handle, reason))
        s.conversation_id = res.get("conversation_id") or s.conversation_id
        s.dialed, s.last = True, time.monotonic()
        self.store.kv_set(f"voiced:{handle}", "1")
        log.info("calling %s (%s): %s", handle, reason, res.get("conversation_id"))
        return {"handle": handle, "reason": reason, "conversation_id": res.get("conversation_id"),
                "sip_call_id": res.get("sip_call_id"), "opening": first}

    # ---------- when EMBER calls (D100) ----------
    def ring(self, handle: str, reason: str) -> Session | None:
        """Queue a call for one of the moments that matter: first contact, the pickup, a changed pickup, "2 minutes
        away". Until it's dialed (`check`: a free line, earliest deadline first), what the thread would text this
        phone waits in the call's outbox and is said when they pick up. A call already on or queued takes it; someone
        texting us right now gets the answer by text."""
        if not self.calls_first(handle):
            return None
        s = self.live(handle)
        if s is None and handle in self.messenger.texting:
            return None  # they're texting us right now: the answer goes back by text
        if s is None:
            s = self.open(handle, reason=reason)
            hid = self._household_id(handle)
            h = next((x for x in self.store.households() if x["household_id"] == hid), {})
            s.deadline = math.inf if h.get("deadline_s") is None else float(h["deadline_s"])
        return s

    async def check(self, *_) -> list[dict]:
        """Plan / clock hook and the poll: notice calls that are over, re-ring unanswered ones whose retry is due, and
        dial queued calls earliest deadline first within VOICE_MAX_CONCURRENT."""
        async with self._check_lock:
            return await self._check()

    async def _check(self) -> list[dict]:
        if not self.configured():
            return []
        await self.reap()
        now, wall = self._t_s(), time.time()
        for key, raw in self.store.kv_prefix("retry:").items():
            handle, r = key.removeprefix("retry:"), json.loads(raw)
            if self.live(handle) is not None:
                self.store.kv_delete(key)  # they're on a call (or one is queued) already
            elif now - r["t_s"] >= RETRY_S or wall - r["wall"] >= RETRY_WALL_S:
                self.store.kv_delete(key)
                if (s := self.ring(handle, r["reason"])) is not None:
                    s.attempt = 2
        placed = []
        queued = sorted((s for s in self.sessions.values() if not s.dialed and s.reason != "inbound"),  # (the console's
                        key=lambda s: s.deadline)                                                      # capture: not a call)
        for s in queued[:max(self.settings.voice_max_concurrent - self._live_count(), 0)]:
            try:
                placed.append(await self.call(s.handle, s.reason))
            except (RuntimeError, ValueError, httpx.HTTPError) as e:
                log.warning("call to %s (%s) failed: %s; texting instead", s.handle, s.reason, e)
                self.end(s.handle, reason="dial failed")
                await self.say_situation(s.handle)
        return placed

    async def undelivered(self, handle: str, text: str) -> dict | None:
        """D90: a text Photon refused after its retries is said on a call instead (Messenger tells us): a resident's real
        number, no call already on, VOICE_MAX_CONCURRENT, one call per phone per COOLDOWN_S."""
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
        return sum(1 for h in list(self.sessions) if (s := self.live(h)) is not None and s.dialed)

    async def reap(self) -> None:
        """Calls ElevenLabs says are over end here, each with its follow-up (a text, or a retry)."""
        for handle, s in list(self.sessions.items()):
            if s.dialed and time.monotonic() - s.last > SESSION_IDLE_S:
                await self.hang_up(handle)
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
                 "turns": s.turns, "heard": s.last_heard, "said": s.last_said}
                for h, s in list(self.sessions.items()) if self.live(h) and s.dialed]
        return {"live": live, "recent": self.recent[::-1][:20]}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


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

    @app.get("/{secret}/health")
    async def health(secret: str):
        if not secrets.compare_digest(secret, token):
            raise HTTPException(404)
        if get_voice() is None:
            raise HTTPException(503, "EMBER backend not ready")
        return {"ok": True}

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
        arrived = time.monotonic()
        cid = f"chatcmpl-{secrets.token_hex(6)}"
        if handle is None:
            log.error("voice turn without a caller id; is the agent's system prompt set? (%r)", system[:120])
            reply_now = "Sorry, I can't tell which phone this is. Please call again later."
            task = None
        else:
            task = asyncio.create_task(voice.turn(handle, conv, said, arrived))
            reply_now = None

        async def answer() -> str:
            if task is None:
                return reply_now
            got = await task
            return "" if got is None else (render_all(got) or "Okay.")

        def end_call(text: str) -> dict | None:
            session = voice.live(handle)
            goodbye = CLOSING.match(said) and re.search(r"\b(?:bye|goodbye|take care)\b", said, re.I)
            offered = any(isinstance(tool, dict) and (tool.get("function") or {}).get("name") == "end_call"
                          for tool in body.get("tools") or [])
            if session is None or not (session.voicemail or session.closing or goodbye) or not offered:
                return None
            args = {"reason": "Voicemail answered" if session.voicemail else "Call finished"}
            return {"id": f"call_{secrets.token_hex(6)}", "type": "function",
                    "function": {"name": "end_call", "arguments": json.dumps(args)}}

        if not body.get("stream"):
            text = await answer()
            tool = end_call(text)
            return JSONResponse({"id": cid, "object": "chat.completion", "created": int(time.time()), "model": "ember",
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": text,
                                              **({"tool_calls": [tool]} if tool else {})},
                                              "finish_reason": "tool_calls" if tool else "stop"}]})

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
                tool = end_call(text)
                if text:  # said first, then the call ends (a tool call's message isn't spoken)
                    yield _chunk(cid, {"content": text})
                if tool:
                    yield _chunk(cid, {"tool_calls": [{"index": 0, **tool}]})
                yield _chunk(cid, {}, "tool_calls" if tool else "stop")
                yield "data: [DONE]\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                if texts and handle:  # they talked over us: say it on the next turn (unless a newer turn answers it)
                    voice.requeue(handle, texts, arrived)
                raise

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


__all__ = ["Voice", "create_voice_app", "render", "SYSTEM_PROMPT", "DISCLOSURE", "HI"]


# ---------- ElevenLabs agent settings (the tunnel URL changes every run) ----------
async def wait_for_voice(url: str, http: httpx.AsyncClient | None = None, timeout_s: float = 90.0, poll_s: float = 1.0) -> bool:
    """Wait for the protected callback's health check: quick-tunnel DNS is not immediately ready."""
    client = http or httpx.AsyncClient(timeout=3.0)
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200 and r.json().get("ok") is True:
                    return True
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(poll_s)
        return False
    finally:
        if http is None:
            await client.aclose()


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
        tools = dict(prompt.get("built_in_tools") or {})
        if not tools.get("end_call"):
            tools["end_call"] = {"type": "system", "name": "end_call", "description": "",
                                 "params": {"system_tool_type": "end_call"}}
        body = {"conversation_config": {"agent": {"first_message": INBOUND, "prompt": {
            "llm": "custom-llm", "custom_llm": custom, "prompt": SYSTEM_PROMPT, "built_in_tools": tools}}}}
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
