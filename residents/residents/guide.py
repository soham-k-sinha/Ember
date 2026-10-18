"""What to do, step by step, on the plan's clock (D56; proactive since D100).

The pickup instruction is step 1 and goes out as soon as the plan assigns a vehicle (outbound.py calls or texts it;
nobody has to say YES: silence means we proceed, only a decline or a new fact changes it). Every later step goes out
by itself when the sim clock reaches its time; nothing waits for a DONE ("done" / "we're ready" is understood, never
required). Every step comes from the plan and its simulation, never from the LLM: the pickup corner is the
household's node in town.json, the times are the plan simulator's arrive / pickup / drop-off times for that
assignment (plan_sim Outcome), the names are the scenario's.

Rescue (a resident):           1 the instruction: who, when, what to bring, where to be (the crew comes to the door
                               if someone needs help to walk) → 2 "2 minutes away, come to the door / corner now"
                               (a call, D100) → 3 outside now (a player: a call, and the clock waits for it, D112)
                               → 4 on board, on the way → 5 checked in at the shelter.
Protect (a facility operator): 1 meet the generator crew → 2 it's connecting → 3 powered.

Steps go out when the clock reaches them: the web's playback, `POST /clock`, or the drill console (`next`, `+N`).

State per thread in kv `guide:<thread>`: {assignment_id, resource_id, sent, finished, steps}.
A guide ends when its assignment leaves the plan or changes vehicle (outbound says the change; the new instruction
starts a new guide).
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from .briefing import walk_phrase
from .db import Store, thread_key
from .messaging import Messenger
from .threads import phone_for_thread, player

log = logging.getLogger("residents.guide")

# "done" / "we're ready" / "yes" while a pickup is under way: answered with when the vehicle gets there, never needed
STEP_DONE = re.compile(
    r"^\s*(?:ok(?:ay)?[,!. ]*)?(?:done|ready|i'?m ready|we'?re ready|here|i'?m here|we'?re here|i am here|we are here|"
    r"aboard|on board|in the (?:van|truck|vehicle)|on the (?:van|truck|bus)|arrived|we'?ve arrived|i'?ve arrived|"
    r"at the corner|connected|it'?s connected|checked in|yes|yep|yeah|y|ok|okay|k|👍)\s*[.!]*\s*$", re.I)
SOON_S = 120.0  # "2 minutes away, come to the door now": one of the calls that matter (D100)


@dataclass(frozen=True)
class Step:
    name: str
    due_t: float      # sim time it becomes current (inf = unknown: not reached in the simulation)
    text: str


def _mins(dt_s: float) -> str:
    if not math.isfinite(dt_s):
        return "soon"
    m = round(dt_s / 60)
    return "now" if m <= 1 else f"in about {m} min"


def _t(*vals) -> float:
    """The first value that is set (0 is a real time); inf if none."""
    return next((float(v) for v in vals if v is not None), math.inf)


class Guide:
    def __init__(self, store: Store, messenger: Messenger, planner):
        self.store, self.messenger, self.planner = store, messenger, planner

    # ---------- state ----------
    def state(self, key: str) -> dict | None:
        raw = self.store.kv_get(f"guide:{key}")
        return json.loads(raw) if raw else None

    def _save(self, key: str, st: dict | None) -> None:
        if st is None:
            self.store.kv_delete(f"guide:{key}")
        else:
            self.store.kv_set(f"guide:{key}", json.dumps(st))

    def active(self) -> dict[str, dict]:
        return {k[len("guide:"):]: json.loads(v) for k, v in self.store.kv_prefix("guide:").items()}

    def guiding(self, thread: dict) -> bool:
        """A pickup / generator is under way for this thread and not finished."""
        st = self.state(thread_key(thread))
        return st is not None and not st.get("finished")

    # ---------- plan facts ----------
    def _now(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    async def _outcomes(self) -> dict[str, dict]:
        plan = self.store.current_plan()
        if plan is None:
            return {}
        now = self._now()
        known = [r for r in self.store.reports() if r["observed_at_t_s"] <= now]
        return await run_in_threadpool(self.planner.bridge.outcomes, plan, known)

    def _names(self) -> tuple[dict, dict]:
        snap = self.store.snapshot()
        return {r["id"]: r for r in snap["resources"]}, {f["id"]: f for f in snap["facilities"]}

    def _home(self, thread: dict) -> tuple[float, float, str] | None:
        """Where the person actually is: the point they texted (located phones) or the building."""
        phone = phone_for_thread(self.store, thread)
        if phone:
            raw = self.store.kv_get(f"located:{phone['handle']}")
            if raw:
                loc = json.loads(raw)
                return loc["lon"], loc["lat"], loc["label"]
        h = next((x for x in self.store.households() if x["household_id"] == thread.get("household_id")), None)
        return (h["lon"], h["lat"], "your address") if h else None

    def steps(self, a: dict, thread: dict, o: dict | None) -> list[Step]:
        """The directions for one assignment, from its simulated outcome `o` (None: the plan's ETA). Step 1 is the
        instruction itself. Always the same number of steps, so the index in the guide's state stays valid."""
        res, fac = self._names()
        who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
        now = self._now()
        o = o or {}
        arrive = _t(o.get("arrive_t"), a.get("eta_s"))
        if "facility_id" in thread:
            f = fac.get(thread["facility_id"], {})
            site = f.get("name", thread["facility_id"])
            done = _t(o.get("complete_t"))
            connect = max(done - arrive, 0) if math.isfinite(done) and math.isfinite(arrive) else None
            return [
                Step("meet", now, f"{who} is on its way to {site}, arriving {_mins(arrive - now)}. Have someone meet the "
                                  f"crew at the entrance and clear the way to your generator connection point."),
                Step("connect", arrive, f"{who} has arrived. The crew needs about {round((connect or 900) / 60)} min to "
                                        f"connect it."),
                Step("powered", done, f"{site} is on {who} power now. Text us if anything changes (fuel, load, water on "
                                      f"site)."),
            ]
        hid = thread["household_id"]
        h = next((x for x in self.store.households() if x["household_id"] == hid), {})
        needs = h.get("needs") if isinstance(h.get("needs"), dict) else {}
        door = bool(needs.get("mobility") or needs.get("accessible_vehicle"))
        people = needs.get("people")
        pickup = _t(o.get("pickup_t"))
        safe = _t(o.get("complete_t"))
        drop = fac.get(a.get("dropoff_facility_id") or "", {}).get("name", "the shelter")
        places = self.planner.bridge.places
        node = self.planner.bridge.household_node(hid)
        corner = places.corner_label(node)
        home = self._home(thread)
        here = home[2] if home else "your address"
        aid = ["the wheelchair"] if needs.get("accessible_vehicle") else ["any walker or cane"] if door else []
        items = ["medications", *(["prescriptions", "any oxygen"] if needs.get("medical") else []), "ID", "your phone", *aid]
        bring = ", ".join(items[:-1]) + " and " + items[-1]
        medical = "; the crew knows someone needs medical care" if needs.get("medical") else ""
        if door:
            first = f"{who} is coming to your door {_mins(arrive - now)}. Be ready at the door with {bring}{medical}."
            soon = f"{who} is 2 minutes away. Come to the door now with your medications{' and ' + aid[0] if aid else ''}."
            board = f"{who} is outside {here} now, and the crew is coming to your door."
        else:
            first = (f"{who} picks you up {_mins(arrive - now)}. Pack {bring}, then "
                     f"{walk_phrase(places, home, node)}{medical}.")
            soon = f"{who} is 2 minutes away. Go to {corner} now."
            board = (f"{who} is at {corner} now. Tell the driver your address"
                     f"{f' and that you are {people}' if people and people > 1 else ''}, then get in.")
        ride = round((safe - pickup) / 60) if math.isfinite(safe) and math.isfinite(pickup) else None
        return [
            Step("prepare", now, first),
            Step("soon", arrive - SOON_S, soon),
            Step("board", arrive, board),
            Step("ride", pickup, f"You're on board, on your way to {drop}{f' (about {ride} min)' if ride else ''}. Stay "
                                 f"with the crew; they'll take you inside."),
            Step("arrived", safe, f"You're checked in at {drop}, out of the flood area. Stay there until the all-clear; "
                                  f"we'll text you if anything changes."),
        ]

    # ---------- events ----------
    def _assignment(self, assignment_id: str) -> dict | None:
        plan = self.store.current_plan()
        return next((x for x in (plan or {}).get("assignments", []) if x["id"] == assignment_id), None)

    def _ring(self, thread: dict, reason: str) -> bool:
        """One of the moments that matter (D100): the next text to this phone is said on a call, if it takes calls.
        True: a call is queued or on."""
        phone = phone_for_thread(self.store, thread)
        return (phone is not None and self.messenger.voice is not None
                and self.messenger.voice.ring(phone["handle"], reason) is not None)

    # ---------- the clock waits where a player's vehicle arrives (D112) ----------
    async def arrivals(self, after: float, until: float) -> list[dict]:
        """`arrival`s in (after, until], earliest first: a player's vehicle reaching them (their guide's "outside now"
        step, not said yet). Only players: the scenario's synthetic households have no phone and never stop the clock."""
        found, outcomes = [], None
        for key, st in self.active().items():
            if st.get("finished") or not key.startswith("household:"):
                continue
            thread = {"household_id": int(key.split(":", 1)[1])}
            phone = phone_for_thread(self.store, thread)
            n = player(self.store, phone["handle"]) if phone else None
            a = self._assignment(st["assignment_id"]) if n else None
            if a is None or a["resource_id"] != st["resource_id"] or a["status"] in ("cancelled", "rejected"):
                continue
            outcomes = outcomes if outcomes is not None else await self._outcomes()
            i, board = next((i, s) for i, s in enumerate(self.steps(a, thread, outcomes.get(a["id"]))) if s.name == "board")
            if st["sent"] < i and after < board.due_t <= until:
                found.append({"t_s": board.due_t, "household_id": thread["household_id"], "resource_id": a["resource_id"],
                              "resource_name": self._names()[0].get(a["resource_id"], {}).get("name", a["resource_id"]),
                              "player": n, "call": False})
        return sorted(found, key=lambda x: x["t_s"])

    def ring(self, arrival: dict) -> bool:
        """The vehicle is outside: the player's phone rings and the "outside now" step is said on the call (texted when
        they don't take calls). True: a call is queued or on."""
        return self._ring({"household_id": arrival["household_id"]}, "soon")

    def waiting(self, arrival: dict) -> bool:
        """The clock still waits at `arrival`: its call is queued or on (with no call, until the operator resumes)."""
        phone = phone_for_thread(self.store, {"household_id": arrival["household_id"]})
        return not arrival["call"] or (phone is not None and self.messenger.voice.live(phone["handle"]) is not None)

    def adopt(self, a: dict, thread: dict) -> None:
        """The instruction for `a` (step 1) just went out: follow it with the later steps, on the clock. A step that is
        already due (the vehicle is 2 minutes away right now) is covered by the instruction's own time."""
        steps = self.steps(a, thread, None)
        now = self._now()
        sent = max(i for i, s in enumerate(steps) if s.due_t <= now)
        self._save(thread_key(thread), {"assignment_id": a["id"], "resource_id": a["resource_id"], "sent": sent,
                                        "finished": sent == len(steps) - 1, "steps": len(steps)})

    async def start(self, a: dict, thread: dict) -> dict | None:
        """`a` was confirmed before its instruction went out (the web console): send it now. Returns the message."""
        self._ring(thread, "instruction")
        steps = self.steps(a, thread, (await self._outcomes()).get(a["id"]))
        msg, _ = await self.messenger.send_message(thread, steps[0].text, self.store.meta().get("plan_version"), a["id"])
        self.adopt(a, thread)
        await self.tick()  # a step already due (e.g. the van is already there) goes out right away
        return msg

    async def on_plan(self, view: dict, raw: dict | None = None) -> None:
        await self.tick()

    async def tick(self) -> int:
        """Send every step that has become current ("2 minutes away" is a call); start guides for assignments confirmed
        outside a text (the web console); drop guides whose assignment changed. Returns how many texts were sent."""
        plan = self.store.current_plan()
        if plan is None:
            return 0
        sent = 0
        outcomes = await self._outcomes()
        now = self._now()
        guides = self.active()
        for a in plan.get("assignments", []):  # confirmed on the web, never told
            t = a["target"]
            if a["status"] != "confirmed" or "edge_ids" in t or phone_for_thread(self.store, t) is None:
                continue
            st = guides.get(thread_key(t))
            if st is None or st["assignment_id"] != a["id"]:
                await self.start(a, t)
                return sent + 1  # start() ticks again for everyone else
        for key, st in guides.items():
            if st.get("finished"):
                continue
            kind, value = key.split(":", 1)
            thread = {"household_id": int(value)} if kind == "household" else {"facility_id": value}
            a = self._assignment(st["assignment_id"])
            if a is None or a["resource_id"] != st["resource_id"] or a["status"] in ("cancelled", "rejected"):
                log.info("guide for %s ended: %s changed", key, st["assignment_id"])
                self._save(key, None)
                continue
            try:
                steps = self.steps(a, thread, outcomes.get(a["id"]))
            except Exception:  # noqa: BLE001 - one bad guide must not stop everyone else's steps
                log.exception("guide for %s: can't compute steps", key)
                continue
            due = max(i for i, s in enumerate(steps) if s.due_t <= now)
            if due <= st["sent"]:
                continue
            step = steps[due]  # only the latest: after a jump, earlier steps are already history
            if step.name == "soon":
                self._ring(thread, "soon")
            await self.messenger.send_message(thread, step.text, self.store.meta().get("plan_version"), a["id"])
            st.update(sent=due, finished=due == len(steps) - 1)
            self._save(key, st)
            sent += 1
        return sent

    async def done(self, thread: dict, lead: str = "Thanks.") -> bool:
        """"done" / "we're ready" / "yes" while a pickup is under way: understood, never required (D100). Nothing moves on
        because of it (the next step comes on the plan's clock, so a repeated or re-sent "done" can't skip a step); the
        reply says when the vehicle gets there. False if nothing is under way for them."""
        key = thread_key(thread)
        st = self.state(key)
        a = self._assignment(st["assignment_id"]) if st else None
        if st is None or st.get("finished") or a is None:
            return False
        steps = self.steps(a, thread, (await self._outcomes()).get(a["id"]))
        arrive = steps[1 if "facility_id" in thread else 2].due_t
        who = self._names()[0].get(a["resource_id"], {}).get("name", a["resource_id"])
        now = self._now()
        text = f"{lead} {who} gets to you {_mins(arrive - now)}." if arrive > now else f"{lead[:-1]}, noted."
        await self.messenger.send_message(thread, text, self.store.meta().get("plan_version"), a["id"])
        return True

    async def current_text(self, thread: dict) -> str | None:
        """The step they're on now, re-computed so its times are current: part of the answer to "what do I
        do?" (D60). None: no guide, or it's finished (the status says they're checked in / powered)."""
        key = thread_key(thread)
        st = self.state(key)
        a = self._assignment(st["assignment_id"]) if st else None
        if not st or st.get("finished") or a is None:
            return None
        steps = self.steps(a, thread, (await self._outcomes()).get(a["id"]))
        return steps[min(st["sent"], len(steps) - 1)].text

    async def next_step(self, key: str) -> Step | None:
        st = self.state(key)
        a = self._assignment(st["assignment_id"]) if st else None
        if not st or st.get("finished") or a is None:
            return None
        kind, value = key.split(":", 1)
        thread = {"household_id": int(value)} if kind == "household" else {"facility_id": value}
        steps = self.steps(a, thread, (await self._outcomes()).get(a["id"]))
        return steps[st["sent"] + 1] if st["sent"] + 1 < len(steps) else None

    async def next_event_t(self) -> float | None:
        """The sim time of the earliest next step across everyone being guided (None: nothing scheduled)."""
        ts = []
        for key in self.active():
            s = await self.next_step(key)
            if s is not None and math.isfinite(s.due_t):
                ts.append(s.due_t)
        return min(ts) if ts else None
