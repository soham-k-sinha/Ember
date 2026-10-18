"""One natural reply per turn (D76): the AI talks, the planner decides.

When someone texts or speaks, the backend still computes every message exactly as before (offers, steps, status,
answers from briefing.py; stored as the record, with all their bookkeeping). This module only changes what the
person receives for that turn: Claude Haiku rewrites the turn's computed messages ("drafts") into one short reply
to what they actually said, acknowledging it, and a deterministic guard checks the result before it is sent:

- every number, vehicle, facility and street it mentions appears in the drafts or the fact sheet;
- every ask in the drafts survives ("reply YES" → it still asks for yes; "reply DONE" → done; a question stays);
- no safety claim the drafts don't make ("you're safe", "no need to leave", "stay put", "911");
- not much longer than the drafts.

Anything the guard rejects, a timeout, an API error or a refusal → the drafts go out as they are. So the worst
case is today's behaviour, never an invented time, vehicle or promise.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from .config import Settings
from .extract import anthropic_client

log = logging.getLogger("residents.reply")

TIMEOUT_S = 8.0

SYSTEM = """You are EMBER, the voice of a flood-evacuation drill coordinator in Allston/Cambridge, talking with one resident (or a facility operator) by text message or on a phone call.

Each turn you get what they just said, the recent conversation, and DRAFTS: the messages our planner computed for this turn. Write the ONE reply we send instead of the drafts.

How to write it:
- Answer what they actually said first, briefly and humanly. If they're hurt, scared or stuck, acknowledge it in a few words ("I'm sorry about your leg.") and say what we're doing about it, using the drafts.
- Then carry every fact and every instruction in the drafts: vehicle names, times, places, steps, what they should do. Keep the drafts' order of importance.
- Keep every time and number attached to exactly what the drafts attach it to: "you should be at the shelter in about 16 min" is when they arrive, not how long the ride takes; "within about 135 min" is a deadline, not an arrival time. Don't convert, add up or re-explain times.
- Never add a fact: no time, number, vehicle, street, place, shelter, promise or reassurance that is not written in the drafts or the facts. Don't guess, don't estimate, don't invent a reason. If the drafts don't answer something they asked, say a coordinator has their question only if the drafts say so.
- If a draft asks them to reply YES / NO / DONE, end with that ask (e.g. "Reply YES to confirm."). If a draft asks a question, end with that question.
- Plain sentences, no lists, no markdown, no emoji. Short: usually 2-4 sentences. On a call, it will be read aloud.
- Don't start with "[EMBER drill]" and don't mention plan versions; we add what's needed."""

Writer = Callable[[str, str], Awaitable[str | None]]  # (system, user) → reply text or None


def make_writer(settings: Settings, timeout_s: float = TIMEOUT_S) -> Writer:
    client, prefix = anthropic_client(settings, timeout=timeout_s, max_retries=1)

    async def write(system: str, user: str) -> str | None:
        resp = await client.messages.create(
            model=prefix + settings.reply_model, max_tokens=600, output_config={"effort": "low"},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if resp.stop_reason == "refusal":
            return None
        return "".join(b.text for b in resp.content if b.type == "text").strip() or None

    return write


def build_input(said: str, history: list[dict], drafts: list[str], facts: str, channel: str) -> str:
    return json.dumps({"channel": channel, "they_said": said, "conversation_so_far": history,
                       "drafts": [d.removeprefix("[EMBER drill] ") for d in drafts], "facts": facts}, indent=1)


# ---------- the guard ----------
_NUMWORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
_SUFFIX = r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Place|Pl|Square|Sq|Boulevard|Blvd|Way|Parkway|Bridge|Lane|Court)"
STREET = re.compile(r"\b((?:[A-Z][a-z]+ ){1,3}" + _SUFFIX + r")\b")
UNSAFE = ("you're safe", "you are safe", "no need to leave", "no need to evacuate", "stay put", "stay where you are",
          "911", "nine one one", "guarantee", "definitely", "for sure", "promise")
_SFX = {"st": "street", "ave": "avenue", "rd": "road", "dr": "drive", "pl": "place", "sq": "square", "blvd": "boulevard"}


def _norm_street(s: str) -> str:
    w = s.lower().split()
    return " ".join(w[:-1] + [_SFX.get(w[-1], w[-1])])


def _numbers(text: str) -> set[int]:
    out = {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text)}
    out |= {v for k, v in _NUMWORDS.items() if re.search(rf"\b{k}\b", text, re.I)}
    return out


@dataclass
class Check:
    ok: bool
    why: str = ""


def check(reply: str, drafts: list[str], facts: str, names: list[str]) -> Check:
    """Is `reply` safe to send instead of `drafts`? `names`: vehicle and facility names in the scenario."""
    if not reply or not reply.strip():
        return Check(False, "empty")
    src = " ".join(drafts) + " " + facts
    low, srclow = reply.lower(), src.lower()
    for n in names:
        if n.lower() in low and n.lower() not in srclow:
            return Check(False, f"names {n!r}, which the drafts don't")
    extra = _numbers(reply) - _numbers(src)
    if extra:
        return Check(False, f"numbers not in the drafts: {sorted(extra)}")
    known = {_norm_street(m) for m in STREET.findall(src)}
    for m in STREET.findall(reply):
        st = _norm_street(m)
        if st not in known and not any(st in k or k in st for k in known):
            return Check(False, f"mentions {m!r}, which the drafts don't")
    for phrase in UNSAFE:
        if phrase in low and phrase not in srclow:
            return Check(False, f"says {phrase!r}, which the drafts don't")
    for word in ("yes", "done", "no"):
        if re.search(rf"\breply {word}\b|\bsay {word}\b", srclow) and not re.search(rf"\b{word}\b", low):
            return Check(False, f"drops the ask for {word.upper()}")
    if any(d.rstrip().endswith("?") for d in drafts) and "?" not in reply:
        return Check(False, "drops the question we need answered")
    if len(reply) > max(2 * len(" ".join(drafts)), 400):
        return Check(False, "much longer than the drafts")
    return Check(True)


async def compose(writer: Writer | None, *, said: str, history: list[dict], drafts: list[str], facts: str,
                  names: list[str], channel: str) -> tuple[str | None, str]:
    """(the reply to send, why) — None: send the drafts as they are."""
    if writer is None or not drafts:
        return None, "no writer"
    import asyncio
    import time
    t0 = time.monotonic()
    try:
        reply = await asyncio.wait_for(writer(SYSTEM, build_input(said, history, drafts, facts, channel)), TIMEOUT_S + 1)
    except Exception as e:  # noqa: BLE001 - down / slow / usage limit: the drafts are always a correct answer
        log.warning("reply writer unavailable (%s); sending the computed messages", str(e)[:160])
        return None, "writer failed"
    if reply is None:
        return None, "refused"
    reply = reply.strip().removeprefix("[EMBER drill]").strip()
    c = check(reply, drafts, facts, names)
    if not c.ok:
        log.warning("reply rejected by the guard (%s): %r", c.why, reply[:200])
        return None, c.why
    log.info("reply written in %.1f s", time.monotonic() - t0)
    return reply, "ok"
