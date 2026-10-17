"""Conversation threads: inbound texts → stored messages (+ hooks), outbound instructions → Photon.

Rules enforced here, not left to callers:
- every outbound text starts with "[EMBER drill]" and carries the plan_version it was generated from;
- a shared iMessage line may only reply to a tester who texted it first (opt-in): until then the
  message is stored and shown on the dashboard with delivery "not_opted_in", never sent;
- inbound messages are deduped by Photon message id (socket redelivery + polling overlap);
- an inbound reply records the plan_version of the last message we sent on that thread, so a reply
  to an old instruction can be detected later (Task 5).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from .bus import Hub
from .db import PhoneConflict, Store, thread_key
from .photon import Inbound, PhotonClient, PhotonError
from .threads import ROLES, normalize_handle, resolve_thread, phone_thread, phone_for_thread, select_thread

log = logging.getLogger("residents.messaging")

DRILL = "[EMBER drill]"
RUN_STARTED_KEY = "run_started_at"  # wall-clock UTC ISO of the last bootstrap (startup reseed / reset)

# Called after a new inbound message is stored: (message, role). Task 3/4 hang extraction + replan here.
InboundHook = Callable[[dict, str], Awaitable[Any]]


def with_drill_prefix(text: str) -> str:
    text = text.strip()
    return text if text.startswith(DRILL) else f"{DRILL} {text}"


def new_message_id() -> str:
    # Random, not a counter: ids feed Photon's Idempotency-Key, and counters restart after /dev/reset.
    return f"m-{uuid.uuid4().hex[:12]}"


class Messenger:
    def __init__(self, store: Store, hub: Hub, photon: PhotonClient | None):
        self.store, self.hub, self.photon = store, hub, photon
        self.inbound_hooks: list[InboundHook] = []
        self._registration_lock = asyncio.Lock()
        # Freeze the old role-only registrations to the existing scenario before a reset.
        for phone in self.store.phones():
            phone_thread(self.store, phone)

    def _t_s(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    # ---------- phones ----------
    async def register_phone(self, role: str, raw_handle: str, household_id: int | None = None,
                             facility_id: str | None = None) -> dict:
        """Assign a shared line and pin this phone to one validated household/facility."""
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        handle = normalize_handle(raw_handle)
        async with self._registration_lock:
            thread = resolve_thread(self.store, role, household_id, facility_id)
            if thread is None:
                raise ValueError(f"No {role} target in the current scenario.")
            previous = self.store.phone(handle=handle)
            existing = phone_for_thread(self.store, thread)
            if existing and existing["handle"] != handle:
                raise PhoneConflict(f"{thread_key(thread)} already has a phone. Choose another household_id/facility_id.")
            if previous and (phone_thread(self.store, previous) != thread or previous["role"] != role):
                raise PhoneConflict("This phone is already bound to another household/facility or scenario.")
            fields: dict[str, str | None] = {"thread_key": thread_key(thread),
                                           "scenario_id": self.store.meta().get("scenario_id")}
            if self.photon is not None:
                a = await self.photon.create_assignment(handle)
                fields.update(assignment_id=a.get("assignmentId"), assigned_number=a.get("assignedPhoneNumber"))
                # A newly assigned line has not opted in, even if this phone used a different line before.
                if previous and previous["assigned_number"] != fields["assigned_number"]:
                    self.store.clear_phone_opt_in(handle)
            self.store.upsert_phone(handle, role, **fields)
            return next(p for p in self.phones_view() if p["handle"] == handle)

    @staticmethod
    def opted_in(phone: dict) -> bool:
        return bool(phone["last_inbound_at"] and phone["space_id"] and phone["agent_user_id"])

    def phones_view(self) -> list[dict]:
        out = []
        for p in self.store.phones():
            thread = phone_thread(self.store, p)
            ready = self.opted_in(p)
            action = None if ready else self._opt_in_instruction(p)
            if thread is None:
                action = "This phone's household/facility is not in the current scenario."
            out.append({**p, "thread": thread, **(thread or {}), "opted_in": ready,
                        "action_needed": action})
        return out

    @staticmethod
    def _opt_in_instruction(phone: dict) -> str:
        if phone.get("assigned_number"):
            return f"Text HI from {phone['handle']} to {phone['assigned_number']} first, then retry /ask."
        return "Enable Photon and register this phone to obtain its assigned_number; then text that number first."

    def delivery_details(self, thread: dict, delivery: str) -> dict:
        phone = phone_for_thread(self.store, thread)
        action = None
        if delivery == "not_opted_in" and phone:
            action = self._opt_in_instruction(phone)
        elif delivery == "no_phone":
            action = "Register a phone for this household/facility with POST /phones."
        elif delivery == "dev":
            action = "Photon is disabled; this message was stored only."
        elif delivery == "failed":
            action = "Photon did not accept this send. Check backend logs; failed sends are retried automatically."
        return {"action_needed": action, "assigned_number": phone["assigned_number"] if phone else None}

    # ---------- inbound ----------
    async def handle_inbound(self, inbound: Inbound) -> dict | None:
        """Photon text → stored thread message → WS `message` → hooks. None if duplicate/unknown sender."""
        try:
            handle = normalize_handle(inbound.handle)
        except ValueError:
            handle = inbound.handle
        phone = self.store.phone(handle=handle)
        if phone is None:
            log.warning("text from unregistered handle %s ignored", handle)
            return None
        thread = phone_thread(self.store, phone)
        if thread is None:
            log.warning("text for a household/facility outside the current scenario ignored")
            return None
        if self.store.has_external_id(inbound.external_id) or self.store.inbound_seen(inbound.external_id):
            return None
        self.store.mark_inbound_seen(inbound.external_id)
        if self._before_this_run(inbound.created_at):
            log.warning("ignoring %s from %s: sent %s, before this run started (%s)", inbound.external_id, handle,
                        inbound.created_at, self.store.kv_get(RUN_STARTED_KEY))
            return None
        # learned from the first text: what we need to reply on this line (and the opt-in timestamp)
        first_contact = not self.opted_in(phone)
        self.store.upsert_phone(handle, phone["role"], peer_user_id=inbound.peer_user_id, agent_user_id=inbound.agent_user_id,
                                space_id=inbound.space_id, last_inbound_at=inbound.created_at or datetime.now(timezone.utc).isoformat())
        if first_contact:
            # Repair markers left by older code that counted blocked sends as delivered.
            self.store.kv_delete(f"instr:{thread_key(thread)}")
            for q in (self.store.plan_view() or {}).get("info_requests", []):
                if q["to"] == thread:
                    self.store.kv_delete(f"asked:{q['id']}")
        return await self._store_inbound(phone["role"], inbound.text, external_id=inbound.external_id, thread=thread)

    def _before_this_run(self, created_at: str | None) -> bool:
        """A text sent before the last reset/bootstrap belongs to an earlier run; never answer it."""
        started = self.store.kv_get(RUN_STARTED_KEY)
        if not (started and created_at):
            return False
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")) < datetime.fromisoformat(started)
        except ValueError:
            return False

    async def simulate_inbound(self, role: str, text: str, household_id: int | None = None,
                               facility_id: str | None = None) -> dict | None:
        """Dev / stage fallback: the same path as a real text, without a phone."""
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return await self._store_inbound(role, text, external_id=None,
                                         thread=select_thread(self.store, role, household_id, facility_id))

    async def _store_inbound(self, role: str, text: str, external_id: str | None, thread: dict | None) -> dict | None:
        if thread is None:
            log.warning("no %s thread in the current state; text dropped", role)
            return None
        msg = {"id": new_message_id(), "thread": thread, "direction": "in", "text": text.strip(), "t_s": self._t_s(),
               "plan_version": self.store.last_outbound_plan_version(thread_key(thread)),
               "assignment_id": None, "report_id": None}
        if not self.store.add_message(msg, external_id=external_id):
            return None  # lost a race with the other delivery path
        await self.hub.broadcast("message", msg, msg["t_s"])
        for hook in self.inbound_hooks:
            await hook(msg, role)
        return msg

    # ---------- outbound ----------
    async def retry_failed(self, max_age_s: float = 600.0) -> int:
        """Re-send outbound messages whose delivery failed (e.g. Photon was down), with the SAME
        Idempotency-Key, so a send that actually went through can't arrive twice. Returns how many sent."""
        if self.photon is None:
            return 0
        sent = 0
        for m in self.store.failed_outbound(max_age_s):
            phone = phone_for_thread(self.store, m["thread"])
            if not phone or not self.opted_in(phone) or m["recipient_handle"] != phone["handle"]:
                continue
            try:
                res = await self.photon.send_text(phone["space_id"], phone["agent_user_id"], m["text"],
                                                  idempotency_key=f"ember-{m['id']}")
                self.store.set_delivery(m["id"], "sent", external_id=(res or {}).get("id"))
                if m.get("assignment_id") and m.get("plan_version") is not None:
                    self.store.mark_offered(m["plan_version"], m["assignment_id"])
                sent += 1
            except Exception as e:  # noqa: BLE001 - still down: try again next round
                log.info("retry of %s failed: %s", m["id"], e)
                break
        return sent

    async def send_message(self, thread: dict, text: str, plan_version: int | None,
                           assignment_id: str | None = None) -> tuple[dict, str]:
        """Store + broadcast an outbound message, then deliver it if this thread has an opted-in phone.
        Returns (message, delivery)."""
        msg = {"id": new_message_id(), "thread": thread, "direction": "out", "text": with_drill_prefix(text),
               "t_s": self._t_s(), "plan_version": plan_version, "assignment_id": assignment_id, "report_id": None}
        phone = phone_for_thread(self.store, thread)
        if self.photon is None:
            delivery = "dev"
        elif phone is None:
            delivery = "no_phone"
        elif not self.opted_in(phone):
            delivery = "not_opted_in"
        else:
            delivery = "pending"
        self.store.add_message(msg, delivery=delivery, recipient_handle=phone["handle"] if phone else None)
        await self.hub.broadcast("message", msg, msg["t_s"])
        if delivery != "pending":
            if delivery == "not_opted_in":
                log.warning("%s phone hasn't texted the line yet; message %s not sent", thread_key(thread), msg["id"])
            return msg, delivery
        try:
            res = await self.photon.send_text(phone["space_id"], phone["agent_user_id"], msg["text"],  # type: ignore[union-attr]
                                              idempotency_key=f"ember-{msg['id']}")
            delivery = "sent"
            self.store.set_delivery(msg["id"], delivery, external_id=(res or {}).get("id"))
        except (PhotonError, Exception) as e:  # noqa: BLE001 - a failed send must not break the replan loop
            delivery = "failed"
            log.error("send %s to %s failed: %s", msg["id"], thread_key(thread), e)
            self.store.set_delivery(msg["id"], delivery)
        return msg, delivery
