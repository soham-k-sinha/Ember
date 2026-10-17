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
    def instruction_for(view: dict, thread: dict) -> dict | None:
        """The assignment this thread is told about: the household's rescue, or the generator heading to the
        facility. Earliest ETA if several; cancelled/done ones don't count."""
        live = [a for a in view.get("assignments", []) if a["status"] not in ("cancelled", "rejected", "done")]
        if "household_id" in thread:
            mine = [a for a in live if a["task"] == "rescue" and a["target"].get("household_id") == thread["household_id"]]
        else:
            mine = [a for a in live if a["task"] == "protect" and a["target"].get("facility_id") == thread["facility_id"]]
        return min(mine, key=lambda a: a["eta_s"]) if mine else None

    def compose(self, a: dict, thread: dict, now: float, version: int) -> str:
        res, fac = self._names()
        r = res.get(a["resource_id"], {})
        who = r.get("name", a["resource_id"])
        if "household_id" in thread:
            drop = fac.get(a.get("dropoff_facility_id") or "", {}).get("name")
            return (f"{who} will pick you up at your address {_mins(a['eta_s'], now)}"
                    + (f" and take you to {drop}" if drop else "")
                    + f". Reply YES to confirm, or tell us what changed. (plan v{version})")
        return (f"{who} is on its way to you, arriving {_mins(a['eta_s'], now)}. "
                f"Reply YES to confirm someone will meet it. (plan v{version})")

    async def on_plan(self, view: dict, raw: dict | None = None) -> list[dict]:
        return await self.sync(view)

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

    async def _instruction(self, view: dict, thread: dict, key: str, now: float) -> dict | None:
        a = self.instruction_for(view, thread)
        raw_last = self.store.kv_get(f"instr:{key}")
        last = json.loads(raw_last) if raw_last else None
        if a is not None:
            changed = (last is None or last.get("assignment_id") != a["id"] or last.get("resource_id") != a["resource_id"]
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

    async def _info_request(self, view: dict, thread: dict, key: str) -> dict | None:
        for q in view.get("info_requests", []):
            if q["to"] != thread or self.store.kv_get(f"asked:{q['id']}"):
                continue
            msg, _ = await self.messenger.send_message(thread, q["question"], view["version"])
            self.store.kv_set(f"asked:{q['id']}", str(view["version"]))
            return msg  # one question at a time
        return None
