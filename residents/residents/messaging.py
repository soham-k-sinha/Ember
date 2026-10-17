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

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from .bus import Hub
from .db import Store, thread_key
from .photon import Inbound, PhotonClient, PhotonError
from .threads import ROLES, normalize_handle, resolve_thread, role_for_thread

log = logging.getLogger("residents.messaging")

DRILL = "[EMBER drill]"

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

    def _t_s(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    # ---------- phones ----------
    async def register_phone(self, role: str, raw_handle: str) -> dict:
        """Assign the tester's phone to a Photon shared line (if Photon is on) and remember its role."""
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        handle = normalize_handle(raw_handle)
        fields: dict[str, str | None] = {}
        if self.photon is not None:
            a = await self.photon.create_assignment(handle)
            fields = {"assignment_id": a.get("assignmentId"), "assigned_number": a.get("assignedPhoneNumber")}
        return self.store.upsert_phone(handle, role, **fields)

    def phones_view(self) -> list[dict]:
        out = []
        for p in self.store.phones():
            out.append({**p, "thread": resolve_thread(self.store, p["role"]),
                        "opted_in": bool(p["last_inbound_at"] and p["space_id"])})
        return out

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
        if self.store.has_external_id(inbound.external_id):
            return None
        # learned from the first text: what we need to reply on this line (and the opt-in timestamp)
        self.store.upsert_phone(handle, phone["role"], peer_user_id=inbound.peer_user_id, agent_user_id=inbound.agent_user_id,
                                space_id=inbound.space_id, last_inbound_at=inbound.created_at or datetime.now(timezone.utc).isoformat())
        return await self._store_inbound(phone["role"], inbound.text, external_id=inbound.external_id)

    async def simulate_inbound(self, role: str, text: str) -> dict | None:
        """Dev / stage fallback: the same path as a real text, without a phone."""
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return await self._store_inbound(role, text, external_id=None)

    async def _store_inbound(self, role: str, text: str, external_id: str | None) -> dict | None:
        thread = resolve_thread(self.store, role)
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
            role = role_for_thread(self.store, m["thread"])
            phone = self.store.phone(role=role) if role else None
            if not phone or not (phone["space_id"] and phone["agent_user_id"]):
                continue
            try:
                res = await self.photon.send_text(phone["space_id"], phone["agent_user_id"], m["text"],
                                                  idempotency_key=f"ember-{m['id']}")
                self.store.set_delivery(m["id"], "sent", external_id=(res or {}).get("id"))
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
        role = role_for_thread(self.store, thread)
        phone = self.store.phone(role=role) if role else None
        if self.photon is None:
            delivery = "dev"
        elif phone is None:
            delivery = "no_phone"
        elif not (phone["last_inbound_at"] and phone["space_id"] and phone["agent_user_id"]):
            delivery = "not_opted_in"
        else:
            delivery = "pending"
        self.store.add_message(msg, delivery=delivery)
        await self.hub.broadcast("message", msg, msg["t_s"])
        if delivery != "pending":
            if delivery == "not_opted_in":
                log.warning("%s phone hasn't texted the line yet; message %s not sent", role, msg["id"])
            return msg, delivery
        try:
            res = await self.photon.send_text(phone["space_id"], phone["agent_user_id"], msg["text"],  # type: ignore[union-attr]
                                              idempotency_key=f"ember-{msg['id']}")
            delivery = "sent"
            self.store.set_delivery(msg["id"], delivery, external_id=(res or {}).get("id"))
        except (PhotonError, Exception) as e:  # noqa: BLE001 - a failed send must not break the replan loop
            delivery = "failed"
            log.error("send %s to %s failed: %s", msg["id"], role, e)
            self.store.set_delivery(msg["id"], delivery)
        return msg, delivery
