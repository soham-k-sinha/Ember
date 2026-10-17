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
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from .bus import Hub
from .db import PhoneConflict, Store, thread_key
from .photon import Inbound, PhotonClient, PhotonError
from .threads import ROLES, normalize_handle, resolve_thread, phone_thread, phone_for_thread, select_thread, unplaced

log = logging.getLogger("residents.messaging")

DRILL = "[EMBER drill]"
RUN_STARTED_KEY = "run_started_at"  # wall-clock UTC ISO of the last bootstrap (startup reseed / reset)

# Called after a new inbound message is stored: (message, role). Task 3/4 hang extraction + replan here.
InboundHook = Callable[[dict, str], Awaitable[Any]]
# A text from a phone that has no household yet (registered with `locate`): (phone row, text).
LobbyHook = Callable[[dict, str], Awaitable[Any]]
# Every message in or out, for the drill console: {direction, who (thread or handle), text, delivery}.
Tap = Callable[[dict], Any]


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
        self.lobby_hooks: list[LobbyHook] = []
        self.taps: list[Tap] = []
        self.voice = None  # voice.Voice: while a call is live, texts to that phone are said on the call (D74)
        # D76: one natural reply per inbound turn. `writer(handle, said, drafts, thread)` → the reply, or None to
        # send the computed messages as they are. None (tests, no API key): every message goes out as computed.
        self.writer = None
        self._turns: dict[str, dict] = {}  # handle → {"said": text, "drafts": [...]} while its text is handled
        self._registration_lock = asyncio.Lock()
        # Freeze the old role-only registrations to the existing scenario before a reset.
        for phone in self.store.phones():
            phone_thread(self.store, phone)

    def _t_s(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    # ---------- phones ----------
    def _tap(self, event: dict) -> None:
        for tap in self.taps:
            try:
                tap(event)
            except Exception:  # noqa: BLE001 - a console printer must never break messaging
                log.exception("tap failed")

    async def register_phone(self, role: str, raw_handle: str, household_id: int | None = None,
                             facility_id: str | None = None, locate: bool = False) -> dict:
        """Assign a shared line and pin this phone to one validated household/facility. `locate`: a
        resident with no household yet; it is placed where its first texts say it is (Locator)."""
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        handle = normalize_handle(raw_handle)
        if locate:
            return await self._register_unplaced(role, handle, household_id, facility_id)
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

    async def _register_unplaced(self, role: str, handle: str, household_id: int | None, facility_id: str | None) -> dict:
        if role != "resident" or household_id is not None or facility_id is not None:
            raise ValueError("locate is for residents without a household_id: they text where they are")
        async with self._registration_lock:
            previous = self.store.phone(handle=handle)
            scenario = self.store.meta().get("scenario_id")
            if previous and (previous["role"] != role or (previous["thread_key"] is not None
                                                           and not self.store.kv_get(f"located:{handle}"))):
                raise PhoneConflict("This phone is already registered to a household/facility; it can't be re-placed by location.")
            fields: dict[str, str | None] = {"scenario_id": scenario}
            if self.photon is not None:
                a = await self.photon.create_assignment(handle)
                fields.update(assignment_id=a.get("assignmentId"), assigned_number=a.get("assignedPhoneNumber"))
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
            if thread is None and unplaced(self.store, p):
                action = (action if self.photon is not None else None) or "Waiting for this resident's location: they text where they are (address or intersection)."
            elif thread is None:
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
        lobby = thread is None and unplaced(self.store, phone)
        if thread is None and not lobby:
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
        if lobby:
            await self._in_turn(handle, inbound.text, self._lobby_inbound(self.store.phone(handle=handle), inbound.text))
            return None
        if first_contact:
            # Repair markers left by older code that counted blocked sends as delivered.
            self.store.kv_delete(f"instr:{thread_key(thread)}")
            for q in (self.store.plan_view() or {}).get("info_requests", []):
                if q["to"] == thread:
                    self.store.kv_delete(f"asked:{q['id']}")
        return await self._in_turn(handle, inbound.text, self._store_inbound(
            phone["role"], inbound.text, external_id=inbound.external_id, thread=thread))

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

    async def phone_inbound(self, raw_handle: str, text: str) -> dict | None:
        """Dev / drill console: a text "from" a registered phone, without Photon (no opt-in learned).
        Placed phones go the normal path; unplaced ones to the lobby (location first)."""
        phone = self.store.phone(handle=normalize_handle(raw_handle))
        if phone is None:
            raise ValueError(f"{raw_handle} is not a registered phone")
        thread = phone_thread(self.store, phone)
        if thread is None:
            if not unplaced(self.store, phone):
                raise ValueError(f"{raw_handle} is not bound to anything in the current scenario")
            await self._in_turn(phone["handle"], text, self._lobby_inbound(phone, text))
            return None
        return await self._in_turn(phone["handle"], text, self._store_inbound(phone["role"], text, external_id=None, thread=thread))

    # ---------- one reply per turn (D76) ----------
    async def _in_turn(self, handle: str, said: str, work):
        """Run the handling of one inbound text; what it would send that phone is held and goes out as one reply."""
        if self.writer is None or handle in self._turns:
            return await work
        self._turns[handle] = {"said": said, "drafts": []}
        try:
            return await work
        finally:
            await self._end_turn(handle)

    def _held(self, handle: str | None) -> dict | None:
        return self._turns.get(handle) if handle else None

    async def _end_turn(self, handle: str) -> None:
        t = self._turns.pop(handle, None)
        drafts = t["drafts"] if t else []
        if not drafts:
            return
        live = [d for d in drafts if d["delivery"] in ("sent", "dev")]
        on_call = self.voice is not None and self.voice.live(handle) is not None
        reply = None
        if live:
            try:
                reply = await self.writer(handle, t["said"], [d["text"] for d in live], live[-1]["thread"])
            except Exception:  # noqa: BLE001 - the computed messages are always a correct reply
                log.exception("reply writer failed")
                reply = None
        if reply:
            text = with_drill_prefix(reply)
            delivery = live[-1]["delivery"]
            if on_call:
                self.voice.capture(handle, text)
            elif delivery == "sent" and self.photon is not None:
                delivery = await self._photon_send(handle, text, f"{live[-1]['id']}-r")
                if delivery == "failed":
                    for d in live:
                        if d["id"]:
                            self.store.set_delivery(d["id"], "failed")
            thread_ids = [d["id"] for d in live if d["id"]]
            if thread_ids:
                self.store.set_said(thread_ids, text)
            self._tap({"direction": "out", "who": live[-1]["thread"] or handle, "text": text,
                       "delivery": "voice" if on_call else delivery})
            for d in drafts:
                if d not in live:
                    self._tap({"direction": "out", "who": d["thread"] or handle, "text": d["text"], "delivery": d["delivery"]})
            return
        for d in drafts:  # as computed, one by one (exactly the behaviour without a writer)
            delivery = d["delivery"]
            if delivery in ("sent", "dev"):
                if on_call:
                    self.voice.capture(handle, d["text"])
                elif delivery == "sent" and self.photon is not None:
                    delivery = await self._photon_send(handle, d["text"], d["id"] or new_message_id())
                    if d["id"]:
                        self.store.set_delivery(d["id"], delivery)
            self._tap({"direction": "out", "who": d["thread"] or handle, "text": d["text"],
                       "delivery": "voice" if on_call and delivery in ("sent", "dev") else delivery})

    async def _photon_send(self, handle: str, text: str, key: str) -> str:
        phone = self.store.phone(handle=handle)
        if phone is None or not self.opted_in(phone):
            return "not_opted_in"
        try:
            await self.photon.send_text(phone["space_id"], phone["agent_user_id"], text, idempotency_key=f"ember-{key}")
            return "sent"
        except Exception as e:  # noqa: BLE001 - a failed send must not break the turn
            log.error("send to %s failed: %s", handle, e)
            return "failed"

    def lobby_log(self, handle: str) -> list[dict]:
        return json.loads(self.store.kv_get(f"lobby:{handle}") or "[]")

    def _lobby_append(self, handle: str, m: dict) -> None:
        self.store.kv_set(f"lobby:{handle}", json.dumps(self.lobby_log(handle) + [m]))

    async def _lobby_inbound(self, phone: dict, text: str) -> None:
        """A text from a phone with no household yet: kept in the phone's lobby log (moved into its
        household's thread once placed) and handed to the Locator."""
        self._lobby_append(phone["handle"], {"direction": "in", "text": text.strip(), "t_s": self._t_s()})
        self._tap({"direction": "in", "who": phone["handle"], "text": text.strip(), "delivery": None})
        for hook in self.lobby_hooks:
            await hook(phone, text.strip())

    async def send_to_phone(self, handle: str, text: str) -> str:
        """Text a phone that has no household yet (the Locator's questions). Same rules as send_message
        (drill prefix, opt-in); kept in the lobby log. Returns delivery."""
        phone = self.store.phone(handle=handle)
        text = with_drill_prefix(text)
        turn = self._held(handle)
        if turn is not None:  # part of this turn's reply (D76)
            on_call = self.voice is not None and self.voice.live(handle) is not None
            delivery = ("sent" if on_call else "dev" if self.photon is None else "no_phone" if phone is None
                        else "not_opted_in" if not self.opted_in(phone) else "sent")
            self._lobby_append(handle, {"direction": "out", "text": text, "t_s": self._t_s(), "delivery": delivery})
            turn["drafts"].append({"id": None, "thread": None, "text": text, "delivery": delivery})
            return delivery
        if self.voice is not None and self.voice.capture(handle, text):
            delivery = "sent"  # said on the live call
        elif self.photon is None:
            delivery = "dev"
        elif phone is None:
            delivery = "no_phone"
        elif not self.opted_in(phone):
            delivery = "not_opted_in"
        else:
            try:
                await self.photon.send_text(phone["space_id"], phone["agent_user_id"], text,
                                            idempotency_key=f"ember-{new_message_id()}")
                delivery = "sent"
            except Exception as e:  # noqa: BLE001 - tell the console, keep going
                log.error("lobby send to %s failed: %s", handle, e)
                delivery = "failed"
        self._lobby_append(handle, {"direction": "out", "text": text, "t_s": self._t_s(), "delivery": delivery})
        self._tap({"direction": "out", "who": handle, "text": text,
                   "delivery": "voice" if self.voice is not None and self.voice.live(handle) else delivery})
        return delivery

    def move_lobby_to_thread(self, handle: str, thread: dict) -> None:
        """Once placed: the pre-placement chat becomes the start of the household's thread (dashboard)."""
        for m in self.lobby_log(handle):
            msg = {"id": new_message_id(), "thread": thread, "direction": m["direction"], "text": m["text"],
                   "t_s": m["t_s"], "plan_version": None, "assignment_id": None, "report_id": None}
            self.store.add_message(msg, delivery=m.get("delivery") if m["direction"] == "out" else None)
        self.store.kv_delete(f"lobby:{handle}")

    async def _store_inbound(self, role: str, text: str, external_id: str | None, thread: dict | None) -> dict | None:
        if thread is None:
            log.warning("no %s thread in the current state; text dropped", role)
            return None
        msg = {"id": new_message_id(), "thread": thread, "direction": "in", "text": text.strip(), "t_s": self._t_s(),
               "plan_version": self.store.last_outbound_plan_version(thread_key(thread)),
               "assignment_id": None, "report_id": None}
        if not self.store.add_message(msg, external_id=external_id):
            return None  # lost a race with the other delivery path
        self._tap({"direction": "in", "who": thread, "text": msg["text"], "delivery": None})
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
        turn = self._held(phone["handle"] if phone else None)
        if turn is not None:  # part of this turn's reply (D76): recorded now, delivered at the end of the turn
            on_call = self.voice is not None and self.voice.live(phone["handle"]) is not None
            delivery = ("sent" if on_call else "dev" if self.photon is None
                        else "not_opted_in" if not self.opted_in(phone) else "sent")
            self.store.add_message(msg, delivery=delivery, recipient_handle=phone["handle"])
            await self.hub.broadcast("message", msg, msg["t_s"])
            turn["drafts"].append({"id": msg["id"], "thread": thread, "text": msg["text"], "delivery": delivery})
            return msg, delivery
        spoken = self.voice is not None and phone is not None and self.voice.capture(phone["handle"], msg["text"])
        if spoken:
            delivery = "sent"  # said on the live call (D74); counts as delivered everywhere a text would
        elif self.photon is None:
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
            self._tap({"direction": "out", "who": thread, "text": msg["text"], "delivery": "voice" if spoken else delivery})
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
        self._tap({"direction": "out", "who": thread, "text": msg["text"], "delivery": delivery})
        return msg, delivery
