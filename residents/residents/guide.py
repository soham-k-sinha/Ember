"""Step-by-step directions after someone says YES (D56).

An offer says who is coming and when; once the person confirms it, they get one text per step and
reply DONE when they've done it. Every step comes from the plan and its simulation, never from the
LLM: the pickup corner is the household's node in town.json, the times are the plan simulator's
arrive / pickup / drop-off times for that assignment (plan_sim Outcome), the names are the scenario's.

Rescue (a resident):           1 get ready + go to the pickup corner (or wait inside, if someone needs
                               help to walk; the crew comes to the door) → 2 board when the vehicle is
                               there → 3 ride to the drop-off → 4 checked in (no reply needed).
Protect (a facility operator): 1 meet the generator crew → 2 it's connecting → 3 powered.

Step k+1 is texted when the sim clock reaches its time (the web's playback, `POST /clock`, or the drill
console). With `auto_clock` (the drill), a DONE from the last person anyone was waiting on moves the
clock straight to the next event, so a drill advances one step at a time, driven by the texts.

State per thread in kv `guide:<thread>`: {assignment_id, resource_id, sent, done: [step indexes], finished}.
A guide ends when its assignment leaves the plan or changes vehicle (outbound texts the change; the next
YES starts a new guide).
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from .db import Store, thread_key
from .messaging import Messenger
from .threads import phone_for_thread

log = logging.getLogger("residents.guide")

WALK_MPS = 1.2          # an adult walking with a bag
WALK_DETOUR = 1.3       # street distance ≈ straight line × 1.3
OUTSIDE_M = 40.0        # pickup corner this close = "right outside"

STEP_DONE = re.compile(
    r"^\s*(?:ok(?:ay)?[,!. ]*)?(?:done|ready|here|i'?m here|we'?re here|i am here|we are here|aboard|on board|"
    r"in the (?:van|truck|vehicle)|on the (?:van|truck|bus)|arrived|we'?ve arrived|i'?ve arrived|at the corner|"
    r"connected|it'?s connected|checked in|yes|yep|yeah|y|ok|okay|k|👍)\s*[.!]*\s*$", re.I)


@dataclass(frozen=True)
class Step:
    name: str
    due_t: float      # sim time it becomes current (inf = unknown: not reached in the simulation)
    text: str
    wants_done: bool


def _mins(dt_s: float) -> str:
    if not math.isfinite(dt_s):
        return "soon"
    m = round(dt_s / 60)
    return "now" if m <= 1 else f"in about {m} min"


def _t(*vals) -> float:
    """The first value that is set (0 is a real time); inf if none."""
    return next((float(v) for v in vals if v is not None), math.inf)


class Guide:
    def __init__(self, store: Store, messenger: Messenger, planner, auto_clock: bool = False):
        self.store, self.messenger, self.planner = store, messenger, planner
        self.auto_clock = auto_clock

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

    def awaiting(self) -> list[str]:
        """Threads whose current step asks for a DONE they haven't sent."""
        out = []
        for key, st in self.active().items():
            if not st.get("finished") and st.get("wants_done") and st["sent"] not in st["done"]:
                out.append(key)
        return out

    def awaiting_done(self, thread: dict) -> bool:
        return thread_key(thread) in self.awaiting()

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
        """The directions for one assignment, from its simulated outcome `o`."""
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
                Step("meet", now, f"Confirmed: {who} is on its way to {site}. Step 1 of 3: Have someone meet the crew at "
                                  f"the entrance {_mins(arrive - now)} and clear the way to your generator connection "
                                  f"point. Reply DONE when someone is waiting.", True),
                Step("connect", arrive, f"Step 2 of 3: {who} has arrived. The crew needs about "
                                        f"{round((connect or 900) / 60)} min to connect it. Reply DONE when it's "
                                        f"connected and powering the site.", True),
                Step("powered", done, f"Step 3 of 3: {site} is on {who} power now. Text us if anything changes "
                                      f"(fuel, load, water on site).", False),
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
        if door:
            first = (f"Confirmed: {who} is coming to your door. Step 1 of 4: Stay inside at {here}. Get medications, "
                     f"ID, your phone and charger ready, plus anything the person who needs help uses (walker, "
                     f"oxygen). The crew arrives {_mins(arrive - now)}. Reply DONE when you're ready.")
            board = (f"Step 2 of 4: {who} is outside {here} now and the crew is coming to your door. "
                     f"Reply DONE once everyone is aboard.")
        else:
            nlon, nlat = places.nodes[node]
            if home is not None:
                d = places.dist_m(home[0], home[1], nlon, nlat)
                walk = (f"walk to the pickup point: {corner}, about {round(d * WALK_DETOUR / 10) * 10} m "
                        f"{places.bearing(home[0], home[1], nlon, nlat)} of you "
                        f"(about {max(1, round(d * WALK_DETOUR / WALK_MPS / 60))} min on foot)"
                        if d > OUTSIDE_M else f"go out to the pickup point right outside: {corner}")
            else:
                walk = f"go to the pickup point: {corner}"
            first = (f"Confirmed: {who} is coming to you. Step 1 of 4: Pack medications, ID, your phone and charger, "
                     f"then {walk}. {who} gets there {_mins(arrive - now)}. Reply DONE when you're there.")
            board = (f"Step 2 of 4: {who} is at {corner} now. Tell the driver your address"
                     f"{f' and that you are {people}' if people and people > 1 else ''}, then get in. "
                     f"Reply DONE once everyone is aboard.")
        ride = round((safe - pickup) / 60) if math.isfinite(safe) and math.isfinite(pickup) else None
        return [
            Step("prepare", now, first, True),
            Step("board", arrive, board, True),
            Step("ride", pickup, f"Step 3 of 4: You're on your way to {drop}"
                                 f"{f' (about {ride} min)' if ride else ''}. Stay with the crew; they'll take you "
                                 f"inside. Reply DONE when you've arrived and checked in.", True),
            Step("arrived", safe, f"Step 4 of 4: You're checked in at {drop}, out of the flood area. Stay there "
                                  f"until the all-clear; we'll text you if anything changes. Thanks for taking part "
                                  f"in the drill.", False),
        ]

    # ---------- events ----------
    def _assignment(self, assignment_id: str) -> dict | None:
        plan = self.store.current_plan()
        return next((x for x in (plan or {}).get("assignments", []) if x["id"] == assignment_id), None)

    async def start(self, a: dict, thread: dict) -> dict | None:
        """They confirmed `a` (by text): text step 1 now. Returns the message sent."""
        key = thread_key(thread)
        outcomes = await self._outcomes()
        steps = self.steps(a, thread, outcomes.get(a["id"]))
        st = {"assignment_id": a["id"], "resource_id": a["resource_id"], "sent": 0, "done": [],
              "wants_done": steps[0].wants_done, "finished": False, "steps": len(steps)}
        self._save(key, st)
        msg, _ = await self.messenger.send_message(thread, steps[0].text, self.store.meta().get("plan_version"), a["id"])
        await self.tick()  # a step already due (e.g. the van is already there) goes out right away
        return msg

    async def on_plan(self, view: dict, raw: dict | None = None) -> None:
        await self.tick()

    async def tick(self) -> int:
        """Send every step that has become current; start guides for assignments confirmed outside a
        text (the web console); drop guides whose assignment changed. Returns how many texts were sent."""
        plan = self.store.current_plan()
        if plan is None:
            return 0
        sent = 0
        outcomes = await self._outcomes()
        now = self._now()
        guides = self.active()
        for a in plan.get("assignments", []):  # confirmed on the web, never texted step 1
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
            await self.messenger.send_message(thread, step.text, self.store.meta().get("plan_version"), a["id"])
            st.update(sent=due, wants_done=step.wants_done, finished=due == len(steps) - 1)
            self._save(key, st)
            sent += 1
        return sent

    async def done(self, thread: dict) -> bool:
        """They finished the current step. False if no step was waiting on them."""
        key = thread_key(thread)
        st = self.state(key)
        if st is None or st.get("finished"):
            return False
        if st["sent"] in st["done"]:
            await self.messenger.send_message(thread, "Thanks, noted. We'll text you the next step.",
                                              self.store.meta().get("plan_version"), st["assignment_id"])
            return True
        st["done"].append(st["sent"])
        self._save(key, st)
        await self.tick()  # a step that is already due goes out now
        if self._advanced(key, st):
            return True
        if self.auto_clock and not self.awaiting():
            t = await self.next_event_t()
            if t is not None and t > self._now():
                await self.planner.set_clock(min(t, self.planner.bridge.t_end_s))  # clock hooks → tick
                if self._advanced(key, st):
                    return True
        a = self._assignment(st["assignment_id"])
        nxt = await self.next_step(key)
        when = f" {_mins(nxt.due_t - self._now())}" if nxt and math.isfinite(nxt.due_t) else ""
        await self.messenger.send_message(thread, f"Thanks. We'll text you the next step{when}.",
                                          self.store.meta().get("plan_version"), a["id"] if a else None)
        return True

    def _advanced(self, key: str, before: dict) -> bool:
        now = self.state(key)
        return now is None or now["sent"] > before["sent"] or now["assignment_id"] != before["assignment_id"]

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
