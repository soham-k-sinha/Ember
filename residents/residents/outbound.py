"""Outbound instructions (TECHNICAL.md §4): after each plan version, text each opted-in phone only if ITS
instruction materially changed, and ask the plan's info_requests for phone threads once.

The plan's `changes` list is per assignment and mostly ETA noise; what a person cares about is "who is
coming and roughly when". So per phone thread we compare the instruction in the new plan with the last
one we actually texted (kv `instr:<thread>`), and send when:
- a vehicle is newly assigned, or a different vehicle/assignment replaces the one we told them about;
- their pickup / generator is no longer coming (cancelled);
- the ETA moved by ≥ MATERIAL_ETA_S.
Texts are fixed templates over computed fields; every one carries plan_version and assignment_id, and
the assignment becomes `offered` until the recipient confirms (Task 5).
"""

from __future__ import annotations

import json
import logging

from .db import Store, thread_key
from .messaging import Messenger
from .threads import ROLES, resolve_thread

log = logging.getLogger("residents.outbound")

MATERIAL_ETA_S = 600.0


def _mins(eta_s: float, now: float) -> str:
    m = round((eta_s - now) / 60)
    return "now" if m <= 1 else f"in about {m} min"


class Outbound:
    def __init__(self, store: Store, messenger: Messenger):
        self.store, self.messenger = store, messenger

    def _names(self) -> tuple[dict, dict]:
        res = {r["id"]: r for r in self.store.snapshot()["resources"]}
        fac = {f["id"]: f for f in self.store.facilities()}
        return res, fac

    @staticmethod
    def instruction_for(view: dict, thread: dict, exclude: set[str] = frozenset()) -> dict | None:
        """The assignment this thread is told about: the household's rescue, or the generator heading to the
        facility. Earliest ETA if several; cancelled/done/rejected ones and vehicles this thread declined
        (`exclude`) don't count."""
        live = [a for a in view.get("assignments", []) if a["status"] not in ("cancelled", "rejected", "done")
                and a["resource_id"] not in exclude]
        if "household_id" in thread:
            mine = [a for a in live if a["task"] == "rescue" and a["target"].get("household_id") == thread["household_id"]]
        else:
            mine = [a for a in live if a["task"] == "protect" and a["target"].get("facility_id") == thread["facility_id"]]
        return min(mine, key=lambda a: a["eta_s"]) if mine else None

    def compose(self, a: dict, thread: dict, now: float, version: int) -> str:
        res, fac = self._names()
        r = res.get(a["resource_id"], {})
        who = r.get("name", a["resource_id"])
        if a.get("status") == "confirmed":  # they already said yes: just the update, no second confirmation
            return f"Update: {who} is now arriving {_mins(a['eta_s'], now)}. (plan v{version})"
        if "household_id" in thread:
            drop = fac.get(a.get("dropoff_facility_id") or "", {}).get("name")
            return (f"{who} will pick you up at your address {_mins(a['eta_s'], now)}"
                    + (f" and take you to {drop}" if drop else "")
                    + f". Reply YES to confirm, or tell us what changed. (plan v{version})")
        return (f"{who} is on its way to you, arriving {_mins(a['eta_s'], now)}. "
                f"Reply YES to confirm someone will meet it. (plan v{version})")

    async def on_plan(self, view: dict, raw: dict | None = None) -> list[dict]:
        await self.mark_declined(view)
        return await self.sync(self.store.plan_view() or view)

    async def sync(self, view: dict, only: str | None = None, ask: bool = True) -> list[dict]:
        """Send what changed for every phone thread (or only thread key `only`). Returns sent messages."""
        sent: list[dict] = []
        now = float(self.store.meta().get("t_s", 0.0))
        for role in ROLES:
            if not self.store.phone(role=role):
                continue
            thread = resolve_thread(self.store, role)
            if thread is None:
                continue
            key = thread_key(thread)
            if only is not None and key != only:
                continue
            msg = await self._instruction(view, thread, key, now)
            if msg:
                sent.append(msg)
            if ask and not msg:
                q = await self._info_request(view, thread, key)
                if q:
                    sent.append(q)
        return sent

    def rejected(self, key: str) -> set[str]:
        return set(json.loads(self.store.kv_get(f"rejected:{key}") or "[]"))

    async def _instruction(self, view: dict, thread: dict, key: str, now: float, force: bool = False) -> dict | None:
        a = self.instruction_for(view, thread, exclude=self.rejected(key))
        raw_last = self.store.kv_get(f"instr:{key}")
        last = json.loads(raw_last) if raw_last else None
        if a is not None:
            changed = force or (last is None or last.get("assignment_id") != a["id"] or last.get("resource_id") != a["resource_id"]
                                or abs(float(last.get("eta_s", 0)) - a["eta_s"]) >= MATERIAL_ETA_S)
            if not changed:
                # same instruction carried into a new version: the allocator rebuilds it as `proposed`,
                # but the person already has it → keep it `offered` (no new text)
                if a["status"] == "proposed":
                    self.store.mark_offered(view["version"], a["id"])
                return None
            text = self.compose(a, thread, now, view["version"])
            msg, delivery = await self.messenger.send_message(thread, text, view["version"], a["id"])
            self.store.kv_set(f"instr:{key}", json.dumps({"assignment_id": a["id"], "resource_id": a["resource_id"],
                                                           "eta_s": a["eta_s"], "plan_version": view["version"]}))
            if self.store.mark_offered(view["version"], a["id"]):
                await self.messenger.hub.broadcast("assignment", {
                    "plan_version": view["version"], "change": "status_changed", "assignment_id": a["id"],
                    "assignment": {**a, "status": "offered"}}, now)
            log.info("instruction v%s → %s (%s): %s", view["version"], key, delivery, a["id"])
            return msg
        if last and last.get("assignment_id"):  # we told them someone is coming; no longer true
            res, _ = self._names()
            who = res.get(last["resource_id"], {}).get("name", last["resource_id"])
            text = (f"Change of plan: {who} is no longer coming to you. We're re-planning and will text you "
                    f"as soon as we have a new instruction. (plan v{view['version']})")
            msg, _ = await self.messenger.send_message(thread, text, view["version"], last["assignment_id"])
            self.store.kv_set(f"instr:{key}", json.dumps({"assignment_id": None, "plan_version": view["version"]}))
            return msg
        return None

    async def mark_declined(self, view: dict) -> None:
        """The allocator doesn't know about declines yet: if it re-proposes a vehicle a thread rejected,
        keep that assignment `rejected` (bookkeeping only; the assignment itself is the allocator's)."""
        for a in view.get("assignments", []):
            t = a["target"]
            if "edge_ids" in t or a["status"] != "proposed":
                continue
            if a["resource_id"] in self.rejected(thread_key(t)):
                self.store.set_assignment_status(view["version"], a["id"], "rejected", ("proposed",))

    @staticmethod
    def describe_need(needs) -> str:
        if not isinstance(needs, dict):
            return ""
        n = needs.get("people")
        parts = [f"{n} {'person' if n == 1 else 'people'}"] if n else []
        if needs.get("accessible_vehicle"):
            parts.append("wheelchair-accessible vehicle")
        elif needs.get("mobility"):
            parts.append("limited mobility")
        if needs.get("medical"):
            parts.append("medical needs")
        return ", ".join(parts)

    def status_text(self, view: dict, thread: dict) -> str | None:
        """Where this person stands in the current plan, from computed fields only. None = nothing to say
        (needs still unknown and nothing assigned)."""
        key = thread_key(thread)
        now = float(self.store.meta().get("t_s", 0.0))
        v = view["version"]
        res, _ = self._names()
        a = self.instruction_for(view, thread, exclude=self.rejected(key))
        blocked = next((u for u in view.get("unresolved", []) if u["target"] == thread), None)
        if a is not None:
            who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
            if a["status"] == "confirmed":
                return f"Your pickup is confirmed: {who} is arriving {_mins(a['eta_s'], now)}. (plan v{v})" \
                    if "household_id" in thread else f"Confirmed: {who} is arriving {_mins(a['eta_s'], now)}. (plan v{v})"
            if "household_id" in thread:
                return f"{who} is assigned to pick you up, arriving {_mins(a['eta_s'], now)}. Reply YES to confirm. (plan v{v})"
            return f"{who} is assigned to you, arriving {_mins(a['eta_s'], now)}. Reply YES to confirm someone will meet it. (plan v{v})"
        if "household_id" in thread:
            h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), None)
            need = self.describe_need(h["needs"]) if h else ""
            if not need:
                return None
            if blocked:
                return (f"We have your details ({need}). No suitable vehicle is free yet: {blocked['blocked_by']}. "
                        f"We'll text you as soon as one is assigned. (plan v{v})")
            return f"We have your details ({need}) and are arranging a pickup; we'll text you. (plan v{v})"
        if blocked:
            return f"No generator is free for you right now: {blocked['blocked_by']}. We'll text you if that changes. (plan v{v})"
        return f"Noted. No generator is assigned to your site right now. (plan v{v})"

    def next_info_request(self, view: dict, thread: dict) -> dict | None:
        return next((q for q in view.get("info_requests", []) if q["to"] == thread and not self.store.kv_get(f"asked:{q['id']}")), None)

    async def send_status(self, thread: dict, prefix: str = "") -> dict | None:
        view = self.store.plan_view()
        text = self.status_text(view, thread) if view else None
        if text is None:
            return None
        msg, _ = await self.messenger.send_message(thread, prefix + text, view["version"])
        return msg

    async def ack(self, a: dict, decision: str, thread: dict) -> dict:
        """Reply to a YES / NO on an offered instruction."""
        res, _ = self._names()
        who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
        now = float(self.store.meta().get("t_s", 0.0))
        v = a["plan_version"]
        if decision == "confirm":
            text = (f"Confirmed: {who} is coming to you, arriving {_mins(a['eta_s'], now)}. "
                    f"Reply here if anything changes. (plan v{v})")
        else:
            text = (f"Understood, we won't send {who}. We're re-planning; reply here if you need help later. (plan v{v})")
        msg, _ = await self.messenger.send_message(thread, text, self.store.meta().get("plan_version"), a["id"])
        return msg

    async def latest(self, thread: dict) -> dict | None:
        """Re-send the current instruction (after a stale reply), or say there is none."""
        view = self.store.plan_view()
        key = thread_key(thread)
        now = float(self.store.meta().get("t_s", 0.0))
        msg = await self._instruction(view, thread, key, now, force=True)
        if msg is None:
            msg, _ = await self.messenger.send_message(
                thread, f"Thanks. That was an older message; nothing is scheduled for you right now. "
                        f"We'll text you as soon as that changes. (plan v{view['version']})", view["version"])
        return msg

    async def _info_request(self, view: dict, thread: dict, key: str) -> dict | None:
        q = self.next_info_request(view, thread)  # one question at a time
        if q is None:
            return None
        msg, _ = await self.messenger.send_message(thread, q["question"], view["version"])
        self.store.kv_set(f"asked:{q['id']}", str(view["version"]))
        return msg
