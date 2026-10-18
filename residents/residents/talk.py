"""What a call says when the caller isn't giving us a new fact (D111): their question, worry or request, answered
in the flood from what EMBER knows, in two short spoken sentences. Never "I can't", never a dead end.

After Intake handles a call turn (the reading, the reports, the replan, the computed messages), `Talk.turn` may say
those messages as one reply instead:
- someone hurt / can't move / bleeding / fell / trapped (a need fact, already replanned): we've got you, what is coming
  from the plan (the vehicle's crew, or an ambulance's paramedics, at the door, when) and one thing to do meanwhile.
  Deterministic, so the reply stays as fast as any fact (D108);
- a question, a worry or a request (where are the police, is the hospital open, can I bring my dog, I'm scared): the
  reply model (D76: the AI talks, the planner decides) answers from a sheet of what we know about them (household, needs,
  vehicle, ETA, step, the water, closed roads, the shelter, the facilities), and a guard rejects any number, vehicle,
  place, street or service the sheet and the computed messages don't contain, any refusal or out-of-world word and
  anything long. Slow (TIMEOUT_S), down or rejected: the computed answer for a specific topic, else a fixed in-world
  template (what is happening for them, then what to do now).
Facts, decisions and finished steps keep their computed messages. The one line that ever steps outside the flood is
REAL_911, when a caller says it is a real emergency (voice.py and intake.py say it, and nothing else).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from .briefing import BRING, mins
from .db import thread_key
from .fallback import NONE_OF, answers
from .outbound import VERSION_TAG
from .reply import check
from .speech import render
from .threads import phone_for_thread

log = logging.getLogger("residents.talk")

TIMEOUT_S = 3.5
REAL = re.compile(r"\b(?:(?:this|it)(?: i|')s (?:a )?real(?! [a-z])|is (?:this|it) (?:a |the )?(?:simulation|drill|demo|"
                  r"game|exercise|real(?! [a-z]))|real emergency|for real|in real life|(?:i'?m|i am|we'?re|we are|"
                  r"(?:s?he|they)(?:'s| is| are|'re)) (?:actually|really) (?:hurt|injured|bleeding|in danger|dying)|"
                  r"not (?:part of )?(?:the |a |this )?(?:game|simulation|demo|drill|exercise))", re.I)
REAL_911 = "If this is a real emergency, please hang up and call 911."
HURT = re.compile(r"\b(hurt|injur\w*|bleed\w*|fell|fallen|broke|broken|sprain\w*|twisted|pain|trapped|"
                  r"can'?t (?:move|walk|stand|get up)|cannot (?:move|walk|stand))\b")
LEG = re.compile(r"\b(leg|ankle|knee|foot|feet|hip)\b")
BLEEDING = re.compile(r"\bbleed")
RESPONDERS = re.compile(r"\b(police|cops?|ambulance|paramedics?|fire ?(?:fighters?|department|truck|crew)|911|rescue|"
                        r"responders?|send (?:someone|somebody|help))\b", re.I)
PET = re.compile(r"\b(dog|cat|pet|puppy|kitten|bird|parrot|hamster|rabbit)s?\b", re.I)
COORDINATOR = re.compile(r"\bcoordinator", re.I)  # texts may name one (the escalation queue); a call never does
DEAD_END = re.compile(r"\b(can'?t|cannot|unable|not able|don'?t have|isn'?t something|aren'?t on)\b", re.I)
# help nobody planned: named only when the sheet or the computed messages name it (an ambulance from the plan does)
UNPLANNED = ("police", "cops", "ambulance", "paramedic", "firefighter", "fire truck", "fire department", "fire crew",
             "helicopter", "boat", "coast guard", "national guard", "rescue team")
STATE = {"ok": "operating on grid power", "backup": "operating on backup power", "down": "without power"}
SYSTEM = """You are EMBER, the flood-response line for Allston, Massachusetts, on a phone call with one resident while the Charles River floods. Every word you write is spoken aloud.

Reply to what they just said in exactly 2 sentences and under 30 words: first answer them (warmly if they're hurt or scared) with what is happening for them, then the one thing to do right now. Say "your corner" or "your door" rather than repeating street names, unless they ask where.

Use only SITUATION (what we know about them) and COMPUTED (what our planner worked out for this turn; it may answer a slightly different question than they asked). Never add a vehicle, time, number, street, place, service or promise that isn't written there, and keep each time exactly as written. Something SITUATION doesn't cover (police, fire crews, another person or address) is never a dead end and never named back: responders are working the flood zone, the request is noted, and here is what happens for them.

Never use the words "can't", "cannot", "unable" or "don't have", never refuse, and never mention a simulation, drill, demo, coordinator, emergency number or that anything isn't real. Never promise police, firefighters, an ambulance or any help SITUATION doesn't name. No lists, no markdown, no emoji; ask nothing back unless COMPUTED asks a question, then end with it.

The shape of a good answer (their facts will differ):
- "Where are the police?" → "Responders are working the whole flood zone; for you the fastest help is Van 7, about 20 min away. Stay inside until it pulls up."
- "Can you come sooner?" → "Van 7 is the fastest help that fits you, about 20 min away. Be at your corner with your medications so you can leave right away."
- "Can you get my sister on Elm Street too?" → "Your sister is noted; for you, Van 7 gets there in about 20 min. Be at your corner with your medications and phone."
"""


class Talk:
    def __init__(self, store, messenger, outbound, writer=None):
        self.store, self.messenger, self.outbound, self.writer = store, messenger, outbound, writer
        self.briefing = outbound.briefing

    async def turn(self, thread: dict, said: str, out, drafts: list[dict]) -> None:
        """A call turn Intake just handled (`out`; `drafts`: what it sent this thread meanwhile): a hurt caller or
        anything that isn't a fact gets one reply here, said in place of the computed messages."""
        t = said.lower().replace("’", "'")
        kinds = {r["kind"] for r in out.reports}
        if "household_id" not in thread or kinds & {"confirm", "reject"} or out.step_done:
            return
        if HURT.search(NONE_OF.sub(" ", t)):
            reply = f"We've got you. {out.question}" if out.question_is_missing_info else self.hurt(thread, t)
        elif kinds & {"need", "closure_report", "facility_status"} or out.question or out.pending:
            return
        elif out.topics or not (out.reports or out.urgent or answers(said)):
            reply = await self.answer(thread, said, [d["text"] for d in drafts], bool(set(out.topics) - {"other"}))
        else:
            return
        if reply is None:
            return
        self.messenger.voice.restate(phone_for_thread(self.store, thread)["handle"], [d["text"] for d in drafts], reply)
        if drafts:
            self.store.set_said([d["id"] for d in drafts], reply)

    def _coming(self, thread: dict) -> tuple[dict | None, dict, str]:
        """(their live assignment, its vehicle, when it reaches them)."""
        a = self.briefing.mine(thread)
        if a is None:
            return None, {}, ""
        r = self.briefing._resources().get(a["resource_id"], {"name": a["resource_id"]})
        return a, r, mins(a["eta_s"] - self.briefing._now())

    def hurt(self, thread: dict, t: str) -> str | None:
        """Someone is hurt or can't move (the need is already in the plan): what is coming, then one thing to do."""
        n = self.briefing.needs(thread)
        if not (n.get("medical") or n.get("mobility")):
            return None
        act = ("Press a clean cloth firmly on the bleeding." if BLEEDING.search(t) else
               "Keep the injured leg still." if LEG.search(t) else "Stay still and keep your phone on.")
        a, r, when = self._coming(thread)
        if a is None:
            return f"We've got you, and we know someone is hurt; we'll tell you the moment a vehicle is on its way. {act}"
        many = r.get("kind") == "ambulance"  # its paramedics
        crew = f"{r['name']}'s {'paramedics' if many else 'crew'}"
        if not (n.get("mobility") or n.get("accessible_vehicle")):
            first = f"{r['name']} picks you up {when}, and the {'paramedics know' if many else 'crew knows'} someone is hurt"
        elif n.get("medical"):
            first = f"{crew} {'know' if many else 'knows'} someone is hurt and {'come' if many else 'comes'} to your door {when}"
        else:
            first = f"{crew} {'come' if many else 'comes'} to your door {when} and will help you out"
        return f"We've got you: {first}. {act}"

    async def answer(self, thread: dict, said: str, drafts: list[str], specific: bool) -> str | None:
        """Their question or worry, answered by the reply model from what we know; None: the computed answer stands
        (a specific topic), else the in-world template."""
        computed = [render(d) for d in drafts]
        if self.writer is not None:
            sheet = await self.sheet(thread)
            t0 = time.monotonic()
            try:
                # the conversation as said on a call, up to this turn's computed messages
                history = [{**m, "text": render(m["text"]) if m["from"] == "EMBER" else m["text"]}
                           for m in self.store.conversation(thread_key(thread), 12) if m["text"] not in drafts][-6:]
                reply = await asyncio.wait_for(self.writer(SYSTEM, json.dumps({
                    "they_said": said, "conversation_so_far": history, "SITUATION": sheet, "COMPUTED": computed},
                    indent=1)), TIMEOUT_S)
            except Exception as e:  # noqa: BLE001 - slow, down, usage limit: the computed answer or the template
                log.warning("call answer unavailable (%s)", str(e)[:160] or type(e).__name__)
                reply = None
            if reply:
                names = [r["name"] for r in self.store.snapshot()["resources"]] + [f["name"] for f in self.store.facilities()]
                why = vet(reply, computed, sheet, names)
                if why is None:
                    log.info("call answer written in %.1f s", time.monotonic() - t0)
                    return reply
                log.warning("call answer rejected (%s): %r", why, reply[:200])
        if specific and not (RESPONDERS.search(said) or PET.search(said) or self._facility(said)):
            return None
        return self.template(thread, said, computed)

    def _facility(self, said: str) -> dict | None:
        """The facility they ask about, by its kind ("the hospital") or the last word of its name ("the Treehouse"); an
        outfall is never one ("the Lower Charles" is the river)."""
        low = said.lower()
        return next((f for f in self.store.facilities() if f["type"] != "outfall" and (
            f["type"].replace("_", " ") in low or re.search(rf"\b{re.escape(f['name'].split()[-1].lower())}\b", low))), None)

    def action(self, thread: dict, a: dict | None) -> str:
        """The one thing to do right now."""
        h, n = self.briefing.household(thread), self.briefing.needs(thread)
        if h.get("status") == "picked_up":
            return "Stay with the crew; they'll take you inside."
        if h.get("status") == "safe":
            return "Stay at the shelter until the all-clear."
        if a is not None and (n.get("mobility") or n.get("accessible_vehicle")):
            return "Stay inside with your medications and phone, ready at the door when it pulls up."
        if a is not None:
            corner = self.briefing.bridge.places.corner_label(self.briefing.node(thread["household_id"]))
            return f"Be at {corner} with your medications and phone before it gets there."
        if h.get("deadline_s") is None:
            return "Stay where you are, above the ground floor if you can."
        return "Stay inside, above the ground floor if you can, and keep your phone on."

    async def sheet(self, thread: dict) -> list[str]:
        """What we know about them and around them, for the reply model: computed fields only."""
        b, ob = self.briefing, self.outbound
        view = self.store.plan_view()
        home = b.home(thread)
        lines = [f"They are at {home[2] if home else 'their address'}; household: "
                 f"{ob.describe_need(b.needs(thread)) or 'details not known yet'}."]
        step = await ob.guide.current_text(thread) if ob.guide is not None else None
        lines += [VERSION_TAG.sub("", x) for x in (ob.status_text(view, thread) if view else None, step) if x]
        a, r, when = self._coming(thread)
        if a is not None:
            kind = r.get("kind", "vehicle").replace("_", " ")
            lines.append(f"{r['name']} ({kind}{', with paramedics' if r.get('kind') == 'ambulance' else ''}) is assigned "
                         f"to them and reaches them {when}.")
        lines += [b.flood_text(thread), b.roads_text(None)]
        for f in self.store.facilities():
            left = f.get("endurance_left_s")
            lines.append(f"Everyone we pick up goes to the shelter at {f['name']}." if f["type"] == "shelter" else
                         f"{f['name']} ({f['type'].replace('_', ' ')}): {STATE.get(f.get('state'), 'state unknown')}"
                         + (f", about {round(left / 60)} min of backup left" if f.get("state") == "backup" and left else "")
                         + ".")
        return lines + [BRING, "Other responders are working the flood zone; we have no positions or times for them.",
                        f"What to do now: {self.action(thread, a)}"]

    def template(self, thread: dict, said: str, computed: list[str]) -> str | None:
        """No model answer: what is happening for them, then what to do now (fixed wording, computed fields). None:
        nothing to add to the computed messages (no vehicle yet, nothing we recognize in what they asked)."""
        a, r, when = self._coming(thread)
        fac = self._facility(said)
        if RESPONDERS.search(said):
            first = "Responders are working the flood zone" + (
                f"; for you the fastest help is {r['name']}, which gets to you {when}" if a else "")
        elif fac is not None:
            first = (f"Everyone we pick up goes to the shelter at {fac['name']}" if fac["type"] == "shelter" else
                     f"{fac['name']} is {STATE.get(fac.get('state'), 'in our plan')}") + (
                f", and {r['name']} gets to you {when}" if a else "")
        elif PET.search(said):
            first = "Yes, bring your pet in a carrier or on a leash" + (f"; {r['name']} gets to you {when}" if a else "")
        elif a is not None:
            first = f"We've got you: {r['name']} gets to you {when}"
        else:
            return None
        return " ".join([f"{first}.", self.action(thread, a)] if a else [f"{first}.", *computed])


def vet(reply: str, computed: list[str], sheet: list[str], names: list[str]) -> str | None:
    """Why a model answer can't be said on a call (None: it can): the reply guard (D76), a coordinator, help nobody
    planned, more than two sentences."""
    c = check(reply, computed, " ".join(sheet), names)
    if not c.ok:
        return c.why
    if COORDINATOR.search(reply):
        return "names a coordinator"
    if DEAD_END.search(reply.replace("’", "'")):
        return "a dead end"
    low, src = reply.lower(), " ".join(computed + sheet).lower()
    extra = [w for w in UNPLANNED if w in low and w not in src]
    if extra:
        return f"names {extra[0]}, which nobody planned"
    if len(re.findall(r"[.!?](?:\s|$)", reply)) > 2 or len(reply.split()) > 40:
        return "too long for a call"
    return None
