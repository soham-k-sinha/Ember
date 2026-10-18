"""Outbound instructions (TECHNICAL.md §4): after each plan version, text each opted-in phone only if ITS
instruction materially changed, and ask the plan's info_requests for phone threads once.

The plan's `changes` list is per assignment and mostly ETA noise; what a person cares about is "who is
coming and roughly when". So per phone thread we compare the instruction in the new plan with the last
one we actually texted (kv `instr:<thread>`, with why it last changed: "what changed?"), and send when:
- a vehicle is newly assigned, or a different vehicle/assignment replaces the one we told them about;
- their pickup / generator is no longer coming (cancelled);
- the ETA moved by ≥ MATERIAL_ETA_S.
Texts are fixed templates over computed fields; every one carries plan_version and assignment_id.

Proactive (D100): an offer is stated as the instruction ("Accessible Van 3 is coming to your door in about 3 min. Be
ready at the door with ..."), never "Reply YES". Once it reaches them the assignment is `confirmed` (silence means we
proceed; a NO or a new fact changes it) and the guide follows it with the later steps on the plan's clock. For a phone
that takes calls, a new or changed pickup (and the first question) is said on a call; the text follows the call.
"""

from __future__ import annotations

import json
import logging
import re

from .briefing import ASK_NEEDS, Briefing, ask  # noqa: F401 - ASK_NEEDS re-exported for app and tests
from .db import Store, thread_key
from .messaging import Messenger
from .threads import phone_for_thread, phone_thread

log = logging.getLogger("residents.outbound")

MATERIAL_ETA_S = 600.0
VERSION_TAG = re.compile(r"\s*\(plan v\d+\)\s*$")


def _mins(eta_s: float, now: float) -> str:
    m = round((eta_s - now) / 60)
    return "now" if m <= 1 else f"in about {m} min"


class Outbound:
    def __init__(self, store: Store, messenger: Messenger, bridge=None):
        self.store, self.messenger = store, messenger
        self.bridge = bridge  # for the pickup corner's name (engine_bridge.EngineBridge); optional
        self.briefing = Briefing(store, bridge) if bridge is not None else None
        self.guide = None  # guide.Guide, set by the app: the current step is part of situation()

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

    def confirmed(self, a: dict) -> bool:
        """Did they say yes to `a`? The view shows sim progress (en_route…), so the stored plan's status decides."""
        return a["status"] == "confirmed" or any(x["id"] == a["id"] and x["status"] == "confirmed"
                                                 for x in (self.store.current_plan() or {}).get("assignments", []))

    def compose(self, a: dict, thread: dict, now: float, version: int, changed: bool = False) -> str:
        """The instruction for `a`, stated as what happens and what to do (D100), or, once they have it, the update and
        why. `changed`: it replaces a pickup we told them about, so it says why first."""
        res, _ = self._names()
        who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
        if self.confirmed(a):  # they have it: just the change and why
            return (f"Your pickup changed: {self.news(version, thread)}, so {who} is now arriving {_mins(a['eta_s'], now)}. "
                    f"(plan v{version})")
        lead = f"Your pickup changed because {self.news(version, thread)}. " if changed else ""
        if self.guide is not None:  # step 1 of the guide: who, when, what to bring, where to be
            text = self.guide.steps(a, thread, None)[0].text
        elif "household_id" in thread:
            text = f"{who} will pick you up {_mins(a['eta_s'], now)}."
        else:
            text = f"{who} is on its way to you, arriving {_mins(a['eta_s'], now)}. Have someone meet the crew."
        if "household_id" in thread:
            h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), {})
            why = self.briefing.why(a, thread) if self.briefing is not None else ""
            text += (f" {why}" if why else "") + (
                " Your street isn't forecast to flood, so this is a precaution; tell us if you'd rather stay put."
                if h.get("deadline_s") is None and self.bridge is not None else "")
        return f"{lead}{text} (plan v{version})"

    def news(self, version: int, thread: dict) -> str:
        """Why plan `version` moved this thread's pickup, in a resident's words: the roads it newly knows are blocked, else
        new needs (theirs, or other households'), else the re-plan itself (a decline, the robust optimization)."""
        new = self.store.reports_by_id(sorted(set(self.store.plan_reports_used(version)) - set(self.store.plan_reports_used(version - 1))))
        roads = sorted({self.bridge.edge_name(e) for r in new if r["kind"] == "closure_report" for e in r["payload"]["edge_ids"]})
        if roads:
            return f"{' and '.join(roads)} {'was' if len(roads) == 1 else 'were'} reported blocked"
        mine = {r.get("household_id") == thread.get("household_id") for r in new if r["kind"] == "need"}
        return ("your household's needs changed" if True in mine else "other households asked for pickups" if mine
                else "we re-planned the routes")

    async def on_plan(self, view: dict, raw: dict | None = None) -> list[dict]:
        await self.mark_declined(view)
        return await self.sync(self.store.plan_view() or view)

    async def sync(self, view: dict, only: str | None = None, ask: bool = True) -> list[dict]:
        """Send what changed for every phone thread (or only thread key `only`). Returns sent messages."""
        sent: list[dict] = []
        now = float(self.store.meta().get("t_s", 0.0))
        for phone in self.store.phones():
            thread = phone_thread(self.store, phone)
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
        if last and last.get("assignment_id") and not last.get("message_id"):
            # Pre-migration instruction markers did not record their message ID.
            prior = next((m for m in reversed(self.store.thread_messages(key))
                          if m["direction"] == "out" and m.get("assignment_id") == last["assignment_id"]
                          and m.get("plan_version") == last.get("plan_version")), None)
            if prior:
                last["message_id"] = prior["id"]
        if last and last.get("assignment_id"):
            if self.store.message_delivery(last.get("message_id", ""))[0] not in ("sent", "dev", "failed"):
                last = None
        if a is not None:
            changed = force or (last is None or last.get("assignment_id") != a["id"] or last.get("resource_id") != a["resource_id"]
                                or abs(float(last.get("eta_s", 0)) - a["eta_s"]) >= MATERIAL_ETA_S)
            if not changed:
                # same instruction carried into a new version: the allocator may rebuild it as `proposed`,
                # but the person already has it → keep it `confirmed` (no new text)
                delivery = self.store.message_delivery(last.get("message_id", ""))[0]
                if delivery in ("sent", "dev"):
                    self.store.set_assignment_status(view["version"], a["id"], "confirmed", ("proposed", "offered"))
                return None
            told = self.confirmed(a)
            phone = phone_for_thread(self.store, thread)
            if phone is not None and self.messenger.voice is not None and not force:  # D100: a new or changed pickup is a call
                self.messenger.voice.ring(phone["handle"], "instruction" if last is None else "pickup_changed")
            text = self.compose(a, thread, now, view["version"], changed=last is not None and not force)
            msg, delivery = await self.messenger.send_message(thread, text, view["version"], a["id"])
            if delivery not in ("sent", "dev", "failed"):
                return msg  # not opted in / no phone: they don't have the instruction
            self.store.kv_set(f"instr:{key}", json.dumps({"assignment_id": a["id"], "resource_id": a["resource_id"],
                                                           "eta_s": a["eta_s"], "plan_version": view["version"],
                                                           "message_id": msg["id"],
                                                           "why": self.news(view["version"], thread)
                                                           if last is not None and not force else None}))
            if delivery in ("sent", "dev") and not told:  # silence means we proceed (D100): it's theirs, step 1 is done
                if self.store.set_assignment_status(view["version"], a["id"], "confirmed", ("proposed", "offered")):
                    await self.messenger.hub.broadcast("assignment", {
                        "plan_version": view["version"], "change": "status_changed", "assignment_id": a["id"],
                        "assignment": {**a, "status": "confirmed"}}, now)
                if self.guide is not None:
                    self.guide.adopt(a, thread)
            log.info("instruction v%s → %s (%s): %s", view["version"], key, delivery, a["id"])
            return msg
        if last and last.get("assignment_id") and self._underway(view, thread, last):
            return None  # it happened (picked up / connected): the step-by-step guide does the talking
        if last and last.get("assignment_id"):  # we told them someone is coming; no longer true
            res, _ = self._names()
            who = res.get(last["resource_id"], {}).get("name", last["resource_id"])
            text = (f"Change of plan: {who} is no longer coming to you. We're re-planning and will text you "
                    f"as soon as we have a new instruction. (plan v{view['version']})")
            msg, delivery = await self.messenger.send_message(thread, text, view["version"], last["assignment_id"])
            if delivery in ("sent", "dev", "failed"):
                self.store.kv_set(f"instr:{key}", json.dumps({"assignment_id": None, "plan_version": view["version"]}))
            return msg
        return None

    @staticmethod
    def _last_rescue(view: dict, thread: dict) -> dict | None:
        """The rescue that picked this household up (working / done in the simulated view)."""
        return next((a for a in view.get("assignments", []) if a["task"] == "rescue" and a["target"] == thread
                     and a["status"] in ("working", "done")), None)

    def _underway(self, view: dict, thread: dict, last: dict) -> bool:
        """The instruction we texted is being carried out or is finished, so "no longer coming" would be
        wrong: its assignment is working / done in the simulated view, or the household is picked up."""
        prev = next((x for x in view.get("assignments", []) if x["id"] == last["assignment_id"]), None)
        if prev is not None and prev["status"] in ("working", "done"):
            return True
        if "household_id" in thread:
            h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), None)
            return bool(h and h["status"] in ("picked_up", "safe"))
        return False

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
        if "household_id" in thread:  # picked up / dropped off: say so, not "arriving"
            h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), None)
            done = self._last_rescue(view, thread)
            if h and h["status"] in ("picked_up", "safe") and done is not None:
                who = res.get(done["resource_id"], {}).get("name", done["resource_id"])
                drop = {f["id"]: f["name"] for f in self.store.facilities()}.get(done.get("dropoff_facility_id") or "", "the shelter")
                return (f"You're with {who} on the way to {drop}. (plan v{v})" if h["status"] == "picked_up" else
                        f"You're checked in at {drop}. Stay there until the all-clear; we'll text you if anything "
                        f"changes. (plan v{v})")
        if a is not None:
            who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
            if self.confirmed(a):
                why = f"{self.why(key, a)}, so " if self.why(key, a) else ""  # "what changed?": the reason we gave
                return f"Your pickup is confirmed: {why}{who} is arriving {_mins(a['eta_s'], now)}. (plan v{v})" \
                    if "household_id" in thread else f"Confirmed: {who} is arriving {_mins(a['eta_s'], now)}. (plan v{v})"
            if "household_id" in thread:
                return f"{who} is coming to pick you up, arriving {_mins(a['eta_s'], now)}. (plan v{v})"
            return f"{who} is on its way to you, arriving {_mins(a['eta_s'], now)}. (plan v{v})"
        if "household_id" in thread:
            h = next((x for x in self.store.households() if x["household_id"] == thread["household_id"]), None)
            need = self.describe_need(h["needs"]) if h else ""
            if not need:
                return None
            fits = self.briefing.fits(thread) if self.briefing is not None else None
            declined = [r for r in fits or [] if r["id"] in self.rejected(key)]
            if fits and len(declined) == len(fits):  # before `blocked`: since D58 the engine lists them as unresolved
                names = " and ".join(r["name"] for r in declined)
                return (f"You declined {names}, the only {'vehicle' if len(declined) == 1 else 'vehicles'} that can "
                        f"take {need}, so no pickup is scheduled. Tell us if you want {declined[0]['name']} "
                        f"after all. (plan v{v})")
            if blocked and h.get("deadline_s") is None:
                return (f"We have your details ({need}). Your street is outside the forecast flood area, so no "
                        f"pickup is planned: stay where you are, above the ground floor if you can. We'll text you "
                        f"if that changes. (plan v{v})")
            if blocked:
                # the engine's own fallbacks; walking only for people who can
                alts = [x for x in blocked.get("alternatives", [])
                        if not (("walk" in x) and isinstance(h.get("needs"), dict) and (h["needs"].get("mobility") or h["needs"].get("accessible_vehicle")))]
                return (f"We have your details ({need}). No suitable vehicle is free yet: {blocked['blocked_by']}. "
                        + (f"Until one is: {' or '.join(alts)}. " if alts else "")
                        + f"We'll text you as soon as one is assigned. (plan v{v})")
            if fits is not None and not fits:
                return f"We have your details ({need}). No vehicle in the fleet fits that; a coordinator has been told. (plan v{v})"
            return (f"We have your details ({need}). No vehicle is scheduled for you in the current plan yet; "
                    f"we'll text you as soon as one is. (plan v{v})")
        if blocked:
            return f"No generator is free for you right now: {blocked['blocked_by']}. We'll text you if that changes. (plan v{v})"
        f = next((x for x in self.store.facilities() if x["id"] == thread.get("facility_id")), {})
        if f.get("powered_by"):
            gen = res.get(f["powered_by"], {}).get("name", f["powered_by"])
            return f"{f.get('name', 'Your site')} is on {gen} power. Text us if anything changes (fuel, load, water). (plan v{v})"
        power = {"ok": "on grid power", "backup": "on backup power", "down": "without power"}.get(f.get("state"), "")
        return ("Noted. No generator is assigned to your site right now"
                + (f"; our plan has {f.get('name', 'your site')} {power}" if power else "")
                + f". Text us if that changes, e.g. 'on backup, about 40 minutes of fuel left'. (plan v{v})")

    ask = staticmethod(ask)  # the plan's question in our words (briefing.ask)

    def why(self, key: str, a: dict | None) -> str | None:
        """The reason we gave when this thread's pickup `a` last changed (kv `instr:`), if it did."""
        told = json.loads(self.store.kv_get(f"instr:{key}") or "{}")
        return told.get("why") if a is not None and told.get("assignment_id") == a["id"] else None

    async def situation(self, thread: dict, brief: bool = False) -> str | None:
        """Everything the plan says about this person right now, in one text (D60): the step they're on (which says
        who, when, where and what to bring), else where they stand and what we still need from them. It answers
        "what's the plan?" / "what do I do?" and any question the plan has nothing more specific for, so no question is
        left without an answer. `brief` (a call): only the most pressing of those, since a call says one thing at a time.
        Computed fields only; None only before there is a plan."""
        view = self.store.plan_view()
        if not view:
            return None
        status = self.status_text(view, thread)
        stand = VERSION_TAG.sub("", status) if status is not None else self.flood_text(thread)
        step = await self.guide.current_text(thread) if self.guide is not None else None
        q = next((x for x in view.get("info_requests", []) if x["to"] == thread), None)
        if step:  # a pickup that just changed says why first, then what to do now
            key = thread_key(thread)
            why = self.why(key, self.instruction_for(view, thread, exclude=self.rejected(key)))
            fresh = why and (self.guide.state(key) or {}).get("sent") == 0
            parts, q = [fresh and f"Your pickup changed because {why}.", step], None
        elif brief and status is not None:
            parts, q = [stand], None
        elif brief and q is not None:
            parts = [self.ask(q)]
        else:
            parts = [stand, q and self.ask(q)]
        if q is not None:
            self.store.kv_set(f"asked:{q['id']}", str(view["version"]))
        parts = [p for p in parts if p]
        if not parts:
            return None
        return " ".join(parts) + f" (plan v{view['version']})"

    def water_s(self, thread: dict) -> float | None:
        """When the forecast flood reaches this household's street (None: it never does)."""
        h = next((x for x in self.store.households() if x["household_id"] == thread.get("household_id")), {})
        return None if h.get("deadline_s") is None else h["deadline_s"] + (self.bridge.margin_s if self.bridge else 0)

    def _water_words(self, thread: dict) -> str:
        now = float(self.store.meta().get("t_s", 0.0))
        if (water := self.water_s(thread)) is None:
            return "your street is outside the forecast flood area"
        return f"the river reaches your street in about {round((water - now) / 60)} min" if water > now \
            else "your street is flooding now"

    def flood_text(self, thread: dict) -> str | None:
        """What the forecast flood means for a household whose details we don't know yet."""
        if "household_id" not in thread:
            return None
        words = self._water_words(thread)
        if self.water_s(thread) is None:
            return f"{words[0].upper()}{words[1:]}, so no pickup is planned: stay where you are, above the ground floor if you can."
        return f"{words[0].upper()}{words[1:]}, so we're planning to pick you up."

    def where_when(self, thread: dict) -> str | None:
        """First contact (D100), one sentence: where we have them and when the water comes there."""
        if "household_id" not in thread:
            return None
        home = self.briefing.home(thread) if self.briefing is not None else None
        words = self._water_words(thread)
        if home is None or home[2] == "your address":
            return f"{words[0].upper()}{words[1:]}."
        said = words.replace("your street", home[2].removeprefix("the corner of "), 1)  # "the river reaches A and B in about 90 min"
        return f"{said[0].upper()}{said[1:]}."

    def next_info_request(self, view: dict, thread: dict) -> dict | None:
        return next((q for q in view.get("info_requests", []) if q["to"] == thread and not self.store.kv_get(f"asked:{q['id']}")), None)

    async def send_status(self, thread: dict, prefix: str = "") -> dict | None:
        """Where they stand, in one text: the step they're on while a pickup is under way (it says who, when and what to
        bring, so a new fact like "she needs oxygen" is answered with the instruction that now includes it)."""
        view = self.store.plan_view()
        step = await self.guide.current_text(thread) if view and self.guide is not None else None
        text = f"{step} (plan v{view['version']})" if step else self.status_text(view, thread) if view else None
        if text is None:
            return None
        msg, _ = await self.messenger.send_message(thread, prefix + text, view["version"])
        return msg

    async def ack(self, a: dict, decision: str, thread: dict) -> dict:
        """Reply to a YES / NO on an instruction (never needed, always understood, D100)."""
        res, _ = self._names()
        who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
        now = float(self.store.meta().get("t_s", 0.0))
        v = a["plan_version"]
        if decision == "confirm":
            text = f"Thanks. {who} is on the way, arriving {_mins(a['eta_s'], now)}. (plan v{v})"
        else:
            water = self.water_s(thread)
            stay = (f" The water reaches your street in about {round((water - now) / 60)} min; if you stay, go to the "
                    f"highest floor and keep your phone with you." if water is not None and water > now else "")
            text = f"Understood, we won't send {who}.{stay} Tell us if you change your mind. (plan v{v})"
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
        phone = phone_for_thread(self.store, thread)
        if phone is not None and self.messenger.voice is not None and "household_id" in thread:
            self.messenger.voice.ring(phone["handle"], "first_contact")  # D100: first contact is a call
        msg, delivery = await self.messenger.send_message(thread, self.ask(q), view["version"])
        if delivery in ("sent", "dev", "failed"):  # failed is queued for retry, not silently discarded
            self.store.kv_set(f"asked:{q['id']}", str(view["version"]))
        return msg
