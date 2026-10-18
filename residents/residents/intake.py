"""Inbound text → extraction → reports → one replan → (maybe) one clarifying question.

Runs as a Messenger inbound hook. The Photon worker calls hooks one message at a time, so two texts
in a row are handled in order, each against the plan the previous one produced.

Every question gets an answer computed from the plan (D60): the topic's own answer (briefing.py), else
the person's whole situation (Outbound.situation). A question the plan can't cover also goes to the
coordinators' queue (kv `question:<report id>`, GET /questions, answered with POST /questions/{id}/answer
or the drill console's `tell`), but the person is never left with only "passed to the coordinators".
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable

from .db import Store, thread_key
from . import fallback
from .extract import LLM, Outcome, extract, to_outcome
from .guide import STEP_DONE
from .messaging import Messenger, plain
from .outbound import Outbound
from .planner import Planner, ReportError

log = logging.getLogger("residents.intake")

# a bare yes to the offer we just made: no model needed (and no ambiguity when the reply also asked something)
YES_ONLY = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|confirm(ed)?|yes please|yes,? confirm)\s*[.!]*\s*$", re.I)
SORRY = "Sorry, we couldn't read that. Could you say it another way?"
# the LLM is unavailable and the keyword parser found nothing: ask for something it can read (never a loop of SORRY)
HELP = ("Sorry, I didn't catch that. Short answers work best, like \"2 of us, one in a wheelchair\", \"no\" or "
        "\"what's the plan?\"")
_outage = {"logged": 0.0}  # one console line per minute while the LLM is down, not one per text
PLANNER_DOWN = "Got your message. Our planner hit a problem; a coordinator is looking at it and will text you."
ESCALATED = "Our plan doesn't cover that, so we've passed your question to a coordinator, who will reply here."
NO_PLAN = "Got your question. We're still building the plan; we'll text you as soon as we have something for you."
URGENT = ("We hear you, and we're on it. If water comes inside, go to a higher floor (not a closed attic) and stay there; "
          "in a real emergency, call 911.")


class Intake:
    def __init__(self, store: Store, messenger: Messenger, planner: Planner, llm: LLM | None, outbound: Outbound | None = None,
                 guide=None):
        self.store, self.messenger, self.planner, self.llm = store, messenger, planner, llm
        self.outbound = outbound
        self.guide = guide  # step-by-step directions on the plan's clock (guide.Guide), optional
        self.escalation_hooks: list[Callable[[dict], Any]] = []  # a question went to the coordinators (drill console)
        # one message at a time, end to end: the next text must see what the previous one changed
        # (known needs, pending questions, the new plan). Photon's worker is serial; HTTP isn't.
        self._lock = asyncio.Lock()

    async def on_inbound(self, msg: dict, role: str) -> Outcome | None:
        async with self._lock:
            return await self._on_inbound(msg, role)

    def _duplicate(self, r: dict) -> bool:
        """Same fact as this thread's previous report of that kind (double-sent text): don't replan again."""
        same = [x for x in self.store.reports() if x["kind"] == r["kind"] and x.get("source") != "scenario"
                and x.get("household_id") == r.get("household_id") and x.get("facility_id") == r.get("facility_id")]
        return bool(same) and same[-1].get("payload") == r.get("payload") and r["kind"] in ("need", "closure_report", "facility_status")

    async def _respond(self, rep: dict, thread: dict) -> None:
        """YES / NO to the last offered instruction → confirm / reject, or the latest instruction if stale.
        A NO to the only vehicle that can take them is checked first ("reply YES to keep it, NO to decline
        anyway"), and a YES after declining takes the decline back (D57)."""
        async def ack(a: dict) -> None:
            if self.guide is not None and rep["kind"] == "confirm":
                await self.guide.start(a, thread)  # they never got the instruction: send it now
            elif self.outbound is not None:
                await self.outbound.ack(a, rep["kind"], thread)

        key = thread_key(thread)
        plan = self.store.current_plan() or {}
        a = next((x for x in plan.get("assignments", []) if x["id"] == rep["assignment_id"]), None)
        holding = self.store.kv_get(f"keep:{key}")
        self.store.kv_delete(f"keep:{key}")
        briefing = self.outbound.briefing if self.outbound is not None else None
        if rep["kind"] == "reject" and a is not None and briefing is not None and holding != a["id"] \
                and "household_id" in thread and a["status"] != "rejected" and not briefing.alternatives(thread, a["resource_id"]):
            await self._check_decline(a, thread)
            return
        if rep["kind"] == "confirm" and a is not None and a["status"] == "rejected":
            self._undo_decline(a, thread)
        res = await self.planner.respond(rep["assignment_id"], rep["kind"], rep.get("plan_version"), on_applied=ack)
        if res["stale"] and self.outbound is not None:
            await self.outbound.latest(thread)
        elif not res["applied"] and res["assignment"] is not None and self.outbound is not None:
            await self.outbound.ack(res["assignment"], rep["kind"], thread)  # a yes to what's already going ahead (D99)

    async def _check_decline(self, a: dict, thread: dict) -> None:
        """They said no to the only vehicle that fits them: make sure, instead of leaving them with nothing."""
        briefing = self.outbound.briefing
        res = {r["id"]: r for r in self.store.snapshot()["resources"]}
        who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
        n = briefing.needs(thread)
        chair = bool(n.get("mobility") or n.get("accessible_vehicle"))
        h = briefing.household(thread)
        flood = h.get("deadline_s") is not None
        self.store.kv_set(f"keep:{thread_key(thread)}", a["id"])
        await self.messenger.send_message(
            thread, f"{who} is the only {'wheelchair-accessible ' if chair else ''}vehicle that can take "
                    f"{n.get('people') or 1} {'person' if n.get('people') == 1 else 'people'}"
                    f"{' with a wheelchair' if chair else ''}, and we have no other way to pick you up"
                    f"{' before the water reaches your street' if flood else ''}. It's still coming unless you say no "
                    f"again.", self.store.meta().get("plan_version"), a["id"])

    def _undo_decline(self, a: dict, thread: dict) -> None:
        """YES after a NO: the vehicle may be offered to them again; the assignment goes back to offered."""
        key = thread_key(thread)
        rejected = [r for r in json.loads(self.store.kv_get(f"rejected:{key}") or "[]") if r != a["resource_id"]]
        self.store.kv_set(f"rejected:{key}", json.dumps(rejected))
        self.store.set_assignment_status(self.store.meta()["plan_version"], a["id"], "offered", ("rejected",))
        log.info("%s took back their decline of %s", key, a["resource_id"])

    async def _answer(self, thread: dict, topics: list[str], road: dict | None = None,
                      question: dict | None = None, situation: bool = True) -> None:
        """Answer every question topic (D60): the topic's own answer from the plan, else the person's whole
        situation (sent once per message, however many topics fall back to it). `other` (nothing in the plan
        covers it) also goes to the coordinators' queue. situation=False: only topic answers (we're about
        to ask for missing details, which is what their situation would say)."""
        briefing = self.outbound.briefing if self.outbound is not None else None
        version = self.store.meta().get("plan_version")
        situation_sent = False
        for t in dict.fromkeys(topics):
            text = await briefing.answer(t, thread, road) if briefing is not None else None  # plan / other: None
            if text is None:
                if t == "other":
                    self._escalate(thread, question)
                if situation_sent or not situation:
                    continue
                situation_sent = True
                sit = await self.outbound.situation(thread) if self.outbound is not None else None
                text = (f"{ESCALATED} Meanwhile, here's where you stand: {sit}" if sit else ESCALATED) if t == "other" \
                    else (sit or NO_PLAN)
            await self.messenger.send_message(thread, text, version)

    def _escalate(self, thread: dict, question: dict | None) -> None:
        """Put a question the plan can't answer on the coordinators' queue (GET /questions)."""
        if question is None:
            return
        item = {"report_id": question["id"], "thread": thread, "text": question.get("text", ""),
                "t_s": question.get("observed_at_t_s", 0.0), "answer": None}
        self.store.kv_set(f"question:{question['id']}", json.dumps(item))
        log.info("question %s from %s → coordinators", question["id"], thread_key(thread))
        for hook in self.escalation_hooks:
            try:
                hook(item)
            except Exception:  # noqa: BLE001 - a console printer must not break the reply
                log.exception("escalation hook")

    def _record(self, thread: dict) -> dict:
        """What the model may know about the sender (no routes, no plan)."""
        if "household_id" in thread:
            h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), None)
            return {k: h[k] for k in ("household_id", "label", "needs", "status") if k in h} if h else {}
        f = next((x for x in self.store.facilities() if x["id"] == thread["facility_id"]), None)
        return {k: f[k] for k in ("id", "name", "type", "state", "endurance_left_s") if k in f} if f else {}

    async def _on_inbound(self, msg: dict, role: str) -> Outcome | None:
        thread = msg["thread"]
        key = thread_key(thread)
        if self.guide is not None and self.guide.guiding(thread) and STEP_DONE.match(msg["text"]):
            await self.guide.done(thread)  # "done" / "here" / "yes" while a pickup is under way: no LLM needed
            return None
        pending_raw = self.store.kv_get(f"pending:{key}")
        pending = json.loads(pending_raw) if pending_raw else None
        earlier = self.store.delivered_outbound(key)
        last_out = earlier[-1]["text"] if earlier else None
        last_assignment = next((m["assignment_id"] for m in reversed(earlier) if m.get("assignment_id")), None)
        record = self._record(thread)
        if YES_ONLY.match(msg["text"]) and last_assignment is not None:
            out = Outcome(reports=[{"source": "resident" if role == "resident" else "operator", "kind": "confirm",
                                    "assignment_id": last_assignment, "confidence": 1.0, "text": msg["text"],
                                    **({"household_id": thread["household_id"]} if "household_id" in thread else {}),
                                    **({"facility_id": thread["facility_id"]} if "facility_id" in thread else {})}])
            return await self._handle(msg, role, thread, key, out, pending)
        out = None
        if self.llm is not None:
            try:
                history = [x for x in self.store.conversation(key, 9)]
                if history and history[-1] == {"from": "them", "text": msg["text"]}:
                    history = history[:-1]  # the message itself is already stored
                out = await extract(self.llm, msg["text"], role=role, thread=thread, record=record,
                                    last_outbound=last_out, pending=pending, resolve_road=self.planner.bridge.resolve_road,
                                    last_assignment_id=last_assignment, history=history[-8:])
            except Exception as e:  # noqa: BLE001 - API down, usage limit, refusal, timeout: never crash or guess
                if time.monotonic() - _outage["logged"] > 60:
                    log.error("the LLM is unavailable (%s); reading texts with the keyword parser until it's back", str(e)[:200])
                    _outage["logged"] = time.monotonic()
        if out is None:  # no model configured, or it failed: the keyword parser
            ex = fallback.parse(msg["text"], role)
            if ex is None:
                await self._help(thread, last_out)
                return None
            out = to_outcome(ex, role=role, thread=thread, text=msg["text"], pending=pending,
                             resolve_road=self.planner.bridge.resolve_road, last_assignment_id=last_assignment,
                             known_needs=record.get("needs"))

        return await self._handle(msg, role, thread, key, out, pending)

    async def _handle(self, msg: dict, role: str, thread: dict, key: str, out: Outcome, pending: dict | None) -> Outcome:
        """What was understood (by the model, the keyword parser or the YES fast path) → reports, replan, replies."""
        if self.messenger.revising_thread(thread):  # a call's revised words (D99): the facts count, a yes / no already did
            out.reports = [r for r in out.reports if r["kind"] not in ("confirm", "reject")]
        if out.step_done and self.guide is not None and await self.guide.done(thread):  # "we're at the corner now"
            if not out.reports and not out.question:
                return out
        if out.pending is not None:
            self.store.kv_set(f"pending:{key}", json.dumps(out.pending))
        elif out.clear_pending:
            self.store.kv_delete(f"pending:{key}")

        replanned = False
        outs_before = sum(1 for m in self.store.thread_messages(key) if m["direction"] == "out")
        stored: list[dict] = []
        dupes = [r for r in out.reports if self._duplicate(r)]
        out.reports = [r for r in out.reports if r not in dupes]
        for r in out.reports:
            try:
                rep, _ = await self.planner.submit_report({**r, "plan_version": msg.get("plan_version")}, replan=False)
                stored.append(rep)
            except ReportError as e:
                log.warning("extracted report rejected (%s): %s", e, r)
        decisions = [r for r in stored if r["kind"] in ("confirm", "reject")]
        question = next((r for r in stored if r["kind"] == "question"), None)
        if decisions and out.topics:  # "no, is anyone near me?": the answer, then the decision's reply
            await self._answer(thread, out.topics, out.road, question)
            out.topics = []
        for rep in decisions:
            await self._respond(rep, thread)
        if stored:
            self.store.set_message_report(msg["id"], stored[0]["id"])
            msg = {**msg, "report_id": stored[0]["id"]}
            await self.messenger.hub.broadcast("message", msg, msg["t_s"])  # clients upsert by id
            facts = [r for r in stored if r["kind"] in ("need", "closure_report", "facility_status")]
            if facts:
                try:
                    await self.planner.replan(trigger="; ".join(self.planner._trigger(r) for r in facts))
                except Exception:  # noqa: BLE001 - the report is stored (unresolved); tell them, keep serving
                    log.exception("replan failed after %s", [r["id"] for r in facts])
                    await self.messenger.send_message(thread, PLANNER_DOWN, self.store.meta().get("plan_version"))
                    return out
                replanned = True  # the plan hook already texted any changed instruction
        if dupes and not stored:
            replanned = True  # nothing new: answer with where they stand
        answered = any(r["kind"] in ("confirm", "reject") for r in stored)  # ack / latest already texted
        texted = sum(1 for m in self.store.thread_messages(key) if m["direction"] == "out") > outs_before
        version = self.store.meta().get("plan_version")
        if out.urgent:  # D92: a replan now (a vehicle that can come sooner does; the plan hook texts the new time), then a
            # calm word, what to do meanwhile and where they stand with the current ETA; never "didn't catch that"
            if not replanned:
                await self.planner.replan(trigger=self.planner._trigger({"kind": "urgent", "source": role, **thread}))
            await self.messenger.send_message(thread, f"{URGENT} {await self.outbound.situation(thread) or ''}".strip(),
                                              self.store.meta().get("plan_version"))
            if not out.question:
                return out
        if out.question and out.question_is_missing_info:
            topics = [t for t in out.topics if t != "plan"]  # answer what they asked, then what we still need
            if topics:
                await self._answer(thread, topics, out.road, question, situation=False)
            await self.messenger.send_message(thread, out.question, version)  # finish the fact first
        elif replanned:
            if not texted and self.outbound is not None:  # never leave a fact unanswered
                if not stored and self.guide is not None and await self.guide.done(thread, lead="Got it."):
                    pass  # nothing new while their pickup is under way: a short "got it" and the ETA, not the whole plan
                elif not await self.outbound.send_status(thread, prefix="Got it. "):
                    await self.messenger.send_message(thread, "Got it, thanks.", version)
            if out.follow_up:
                await self.messenger.send_message(thread, out.follow_up, version)
            topics = [t for t in out.topics if t != "plan"]  # "2 of us, what should we bring?": the instruction is the plan
            if topics:
                await self._answer(thread, topics, out.road, question)
        elif answered:
            pass  # the ack / latest instruction is the reply; questions were answered above
        elif self.outbound is not None:
            await self._reply_without_facts(thread, out, stored)
        elif out.question:
            await self.messenger.send_message(thread, out.question, version)
        return out

    async def _help(self, thread: dict, last_out: str | None) -> None:
        """Nothing readable without the LLM: repeat what we need from them (the plan's open question, else where they
        stand, e.g. the offer waiting for their YES), with examples, never the same apology twice in a row."""
        view = self.store.plan_view() or {}
        q = next((Outbound.ask(x) for x in view.get("info_requests", []) if x["to"] == thread), None) or (
            self.outbound.status_text(view, thread) if view and self.outbound is not None else None)
        text = f"Sorry, I didn't catch that. {q}" if q else HELP
        if last_out and plain(last_out).startswith(text[:40]):
            text = HELP if q else "Sorry, I still didn't catch that. Try a few words, like \"yes\" or \"done\"."
        await self.messenger.send_message(thread, text, self.store.meta().get("plan_version"))

    async def _reply_without_facts(self, thread: dict, out: Outcome, stored: list[dict]) -> None:
        """Chatter or a question. A question is answered from the plan by topic (briefing.py, never
        generated), falling back to their whole situation (D60). Chatter gets the plan's open question
        first, else where they stand, else the model's own prompt."""
        view = self.store.plan_view()
        question = next((r for r in stored if r["kind"] == "question"), None)
        if out.topics:
            await self._answer(thread, out.topics, out.road, question)
            return
        if view:
            # A newly opted-in phone may already have a computed assignment. Send the
            # actual offer (with assignment_id) so its next YES can confirm that offer.
            if await self.outbound.sync(view, only=thread_key(thread)):
                return
        if await self.outbound.send_status(thread):
            return
        if out.question:
            await self.messenger.send_message(thread, out.question, self.store.meta().get("plan_version"))
