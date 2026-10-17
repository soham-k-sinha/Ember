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
from .planner import Planner, ReportError

log = logging.getLogger("residents.intake")

SORRY = "Sorry, we couldn't read that. Could you say it another way?"


class Intake:
    def __init__(self, store: Store, messenger: Messenger, planner: Planner, llm: LLM):
        self.store, self.messenger, self.planner, self.llm = store, messenger, planner, llm

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

        stored: list[dict] = []
        for r in out.reports:
            try:
                rep, _ = await self.planner.submit_report({**r, "plan_version": msg.get("plan_version")}, replan=False)
                stored.append(rep)
            except ReportError as e:
                log.warning("extracted report rejected (%s): %s", e, r)
        if stored:
            self.store.set_message_report(msg["id"], stored[0]["id"])
            msg = {**msg, "report_id": stored[0]["id"]}
            await self.messenger.hub.broadcast("message", msg, msg["t_s"])  # clients upsert by id
            facts = [r for r in stored if r["kind"] in ("need", "closure_report", "facility_status")]
            if facts:
                await self.planner.replan(trigger="; ".join(self.planner._trigger(r) for r in facts))
        if out.question:
            await self.messenger.send_message(thread, out.question, self.store.meta().get("plan_version"))
        return out
