"""Inbound text → extraction → reports → one replan → (maybe) one clarifying question.

Runs as a Messenger inbound hook. The Photon worker calls hooks one message at a time, so two texts
in a row are handled in order, each against the plan the previous one produced.
"""

from __future__ import annotations

import json
import logging

from .db import Store, thread_key
from .extract import LLM, Outcome, extract
from .messaging import Messenger
from .outbound import Outbound
from .planner import Planner, ReportError

log = logging.getLogger("residents.intake")

SORRY = "Sorry, we couldn't read that. Could you say it another way?"


class Intake:
    def __init__(self, store: Store, messenger: Messenger, planner: Planner, llm: LLM, outbound: Outbound | None = None):
        self.store, self.messenger, self.planner, self.llm = store, messenger, planner, llm
        self.outbound = outbound

    async def _respond(self, rep: dict, thread: dict) -> None:
        """YES / NO to the last offered instruction → confirm / reject, or the latest instruction if stale."""
        async def ack(a: dict) -> None:
            if self.outbound is not None:
                await self.outbound.ack(a, rep["kind"], thread)

        res = await self.planner.respond(rep["assignment_id"], rep["kind"], rep.get("plan_version"), on_applied=ack)
        if res["stale"] and self.outbound is not None:
            await self.outbound.latest(thread)

    def _record(self, thread: dict) -> dict:
        """What the model may know about the sender (no routes, no plan)."""
        if "household_id" in thread:
            h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), None)
            return {k: h[k] for k in ("household_id", "label", "needs", "status") if k in h} if h else {}
        f = next((x for x in self.store.facilities() if x["id"] == thread["facility_id"]), None)
        return {k: f[k] for k in ("id", "name", "type", "state", "endurance_left_s") if k in f} if f else {}

    async def on_inbound(self, msg: dict, role: str) -> Outcome | None:
        thread = msg["thread"]
        key = thread_key(thread)
        pending_raw = self.store.kv_get(f"pending:{key}")
        pending = json.loads(pending_raw) if pending_raw else None
        earlier = [m for m in self.store.thread_messages(key) if m["direction"] == "out"]
        last_out = earlier[-1]["text"] if earlier else None
        last_assignment = next((m["assignment_id"] for m in reversed(earlier) if m.get("assignment_id")), None)
        try:
            out = await extract(self.llm, msg["text"], role=role, thread=thread, record=self._record(thread),
                                last_outbound=last_out, pending=pending, resolve_road=self.planner.bridge.resolve_road,
                                last_assignment_id=last_assignment)
        except Exception as e:  # noqa: BLE001 - API down, refusal, timeout: ask, never crash or guess
            log.error("extraction failed for %s: %r", msg["id"], e)
            await self.messenger.send_message(thread, SORRY, self.store.meta().get("plan_version"))
            return None

        if out.pending is not None:
            self.store.kv_set(f"pending:{key}", json.dumps(out.pending))
        elif out.clear_pending:
            self.store.kv_delete(f"pending:{key}")

        replanned = False
        outs_before = sum(1 for m in self.store.thread_messages(key) if m["direction"] == "out")
        stored: list[dict] = []
        for r in out.reports:
            try:
                rep, _ = await self.planner.submit_report({**r, "plan_version": msg.get("plan_version")}, replan=False)
                stored.append(rep)
            except ReportError as e:
                log.warning("extracted report rejected (%s): %s", e, r)
        for rep in [r for r in stored if r["kind"] in ("confirm", "reject")]:
            await self._respond(rep, thread)
        if stored:
            self.store.set_message_report(msg["id"], stored[0]["id"])
            msg = {**msg, "report_id": stored[0]["id"]}
            await self.messenger.hub.broadcast("message", msg, msg["t_s"])  # clients upsert by id
            facts = [r for r in stored if r["kind"] in ("need", "closure_report", "facility_status")]
            if facts:
                await self.planner.replan(trigger="; ".join(self.planner._trigger(r) for r in facts))
                replanned = True  # the plan hook already texted any changed instruction
        answered = any(r["kind"] in ("confirm", "reject") for r in stored)  # ack / latest already texted
        texted = sum(1 for m in self.store.thread_messages(key) if m["direction"] == "out") > outs_before
        version = self.store.meta().get("plan_version")
        if out.question and out.question_is_missing_info:
            await self.messenger.send_message(thread, out.question, version)  # finish the fact first
        elif replanned:
            if not texted and self.outbound is not None:  # never leave a fact unanswered
                if not await self.outbound.send_status(thread, prefix="Got it. "):
                    await self.messenger.send_message(thread, "Got it, thanks.", version)
        elif answered:
            pass
        elif self.outbound is not None:
            await self._reply_without_facts(thread, out, stored)
        elif out.question:
            await self.messenger.send_message(thread, out.question, version)
        return out

    async def _reply_without_facts(self, thread: dict, out: Outcome, stored: list[dict]) -> None:
        """Chatter or a question: the plan's open question first, else where they stand, else the model's
        own prompt. A resident's question is never answered by the LLM: we say it went to the coordinators."""
        view = self.store.plan_view()
        asked_q = any(r["kind"] == "question" for r in stored)
        q = self.outbound.next_info_request(view, thread) if view else None
        if q and not asked_q:
            await self.outbound.sync(view, only=thread_key(thread))
            return
        prefix = "We've passed your question to the coordinators. " if asked_q else ""
        if await self.outbound.send_status(thread, prefix=prefix):
            return
        if out.question:
            await self.messenger.send_message(thread, prefix + out.question, self.store.meta().get("plan_version"))
        elif prefix:
            await self.messenger.send_message(thread, prefix.strip(), self.store.meta().get("plan_version"))
