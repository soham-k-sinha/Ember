"""What the plan knows about one person, in words (D57). Deterministic: every sentence is built from the
current plan, its simulation and the scenario's fleet, never generated.

The allocator already plans around everyone (all households, every vehicle's queue, road travel times,
closures, flood deadlines, capacity, wheelchair access); this module makes that visible to the person
it affects:
- `why(a, thread)`: why this vehicle and what's ahead of you on it ("the only wheelchair-accessible
  vehicle; it picks up 1 other household at your corner first");
- `fits(thread)`: which vehicles could take this household at all, and what each is doing;
- `answer(topic, thread)`: a resident's question by topic (the LLM only labels the topic):
  eta / pickup_place / destination / others / vehicles / bring / flood / roads / safety. `plan` and anything
  these can't answer get the person's whole situation instead (Outbound.situation, D60): never a dead end.
"""

from __future__ import annotations

import json
import math
import re

from starlette.concurrency import run_in_threadpool

from .db import Store, thread_key
from .threads import phone_for_thread

VEHICLES = ("van", "accessible_van", "truck")
NEAR_M = 300.0          # "near you": other households of this run within this distance
WALK_MPS = 1.2          # an adult walking with a bag
WALK_DETOUR = 1.3       # street distance ≈ straight line × 1.3
OUTSIDE_M = 40.0        # pickup corner this close = "right outside"
LIVE = ("proposed", "offered", "confirmed", "en_route", "working")
SHARES = re.compile(r"shares the trip with household #(\d+)")  # the engine's rationale for a shared trip (D59)
TOPICS = ("plan", "eta", "pickup_place", "destination", "others", "vehicles", "bring", "flood", "roads", "safety", "other")
BRING = ("Bring medications (and prescriptions), ID, your phone and charger, glasses, and anything someone with you "
         "needs, like a walker or oxygen. Bring pets too, in a carrier or on a leash. One small bag each; leave "
         "everything else.")
# Fixed, vetted wording (Ready.gov flood guidance), never generated: the one answer that must be right every time.
SAFETY = ("In a real emergency, call 911. Don't walk or drive through floodwater: 6 inches of moving water can knock "
          "you down and 1 foot can sweep a car away. If water comes inside, go to a higher floor (not a closed attic), "
          "and stay away from downed power lines.")


# the one question first contact asks (D99): the planner asks a household for its needs; this is how we word it
ASK_NEEDS = "How many people are with you, and is anyone hurt, in a wheelchair, or in need of oxygen or medication?"


def ask(q: dict) -> str:
    """An info request in our words: a household is asked the one combined needs question (D99)."""
    return ASK_NEEDS if "household_id" in q["to"] else q["question"]


def mins(dt_s: float) -> str:
    if not math.isfinite(dt_s):
        return "soon"
    m = round(dt_s / 60)
    return "now" if m <= 1 else f"in about {m} min"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def walk_phrase(places, home: tuple[float, float, str] | None, node: int) -> str:
    """'walk to the pickup point: the corner of A and B, about 120 m north of you (about 2 min on foot)'."""
    corner = places.corner_label(node)
    if home is None:
        return f"go to the pickup point: {corner}"
    nlon, nlat = places.nodes[node]
    d = places.dist_m(home[0], home[1], nlon, nlat)
    if d <= OUTSIDE_M:
        return f"go out to the pickup point right outside: {corner}"
    return (f"walk to the pickup point: {corner}, about {round(d * WALK_DETOUR / 10) * 10} m "
            f"{places.bearing(home[0], home[1], nlon, nlat)} of you "
            f"(about {max(1, round(d * WALK_DETOUR / WALK_MPS / 60))} min on foot)")


class Briefing:
    def __init__(self, store: Store, bridge):
        self.store, self.bridge = store, bridge

    # ---------- facts ----------
    def _now(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    def _view(self) -> dict:
        return self.store.plan_view() or {}

    def _raw(self) -> dict:
        return self.store.current_plan() or {}

    def _resources(self) -> dict[str, dict]:
        return {r["id"]: r for r in self.store.snapshot()["resources"]}

    def _facility_names(self) -> dict[str, str]:
        return {f["id"]: f["name"] for f in self.store.facilities()}

    def household(self, thread: dict) -> dict:
        return next((x for x in self.store.households() if x["household_id"] == thread.get("household_id")), {})

    def needs(self, thread: dict) -> dict:
        n = self.household(thread).get("needs")
        return n if isinstance(n, dict) else {}

    def rejected(self, thread: dict) -> set[str]:
        return set(json.loads(self.store.kv_get(f"rejected:{thread_key(thread)}") or "[]"))

    def home(self, thread: dict) -> tuple[float, float, str] | None:
        """Where the person actually is: the point they texted (located phones), else the building."""
        phone = phone_for_thread(self.store, thread)
        if phone:
            raw = self.store.kv_get(f"located:{phone['handle']}")
            if raw:
                loc = json.loads(raw)
                return loc["lon"], loc["lat"], loc["label"]
        h = self.household(thread)
        return (h["lon"], h["lat"], "your address") if h else None

    def mine(self, thread: dict) -> dict | None:
        """This thread's live assignment (earliest), not one they declined."""
        rej = self.rejected(thread)
        task = "rescue" if "household_id" in thread else "protect"
        own = [a for a in self._view().get("assignments", []) if a["task"] == task and a["target"] == thread
               and a["status"] in LIVE and a["resource_id"] not in rej]
        return min(own, key=lambda a: a["eta_s"]) if own else None

    def fits(self, thread: dict) -> list[dict]:
        """Every vehicle in the fleet that could carry this household (capacity + wheelchair access)."""
        n = self.needs(thread)
        people = n.get("people") or 1
        chair = bool(n.get("mobility") or n.get("accessible_vehicle"))
        return [r for r in self._resources().values() if r["kind"] in VEHICLES
                and (r.get("capacity_people") or 0) >= people and (r.get("accessible") or not chair)]

    def alternatives(self, thread: dict, without: str) -> list[dict]:
        """Vehicles that fit, other than `without` and the ones they already declined."""
        rej = self.rejected(thread) | {without}
        return [r for r in self.fits(thread) if r["id"] not in rej]

    def queue(self, resource_id: str) -> list[dict]:
        """The vehicle's live rescue pickups in plan order (by ETA)."""
        q = [a for a in self._view().get("assignments", []) if a["resource_id"] == resource_id
             and a["task"] == "rescue" and a["status"] in LIVE]
        return sorted(q, key=lambda a: a["eta_s"])

    def trip_mates(self, a: dict) -> set[int]:
        """Households on the same trip as rescue `a` (engine D59: a van collects a nearby household on its list
        before the drop-off). The engine's rationale names the household a chained pickup shares the trip with;
        read it both ways and follow the chain (A ← B ← C is one trip)."""
        q = self.queue(a["resource_id"])
        links: dict[int, set[int]] = {}
        for x in q:
            hid = x["target"].get("household_id")
            for other in map(int, SHARES.findall(x.get("rationale") or "")):
                links.setdefault(hid, set()).add(other)
                links.setdefault(other, set()).add(hid)
        me = a["target"].get("household_id")
        seen, todo = {me}, [me]
        while todo:
            for n in links.get(todo.pop(), set()) - seen:
                seen.add(n)
                todo.append(n)
        return seen - {me}

    def people(self, hid: int) -> int:
        n = next((h.get("needs") for h in self.store.households() if h["household_id"] == hid), None)
        return (n.get("people") if isinstance(n, dict) else None) or 1

    def node(self, hid: int) -> int | None:
        try:
            return self.bridge.household_node(hid)
        except (KeyError, AttributeError):
            return None

    def neighbors(self, thread: dict) -> list[dict]:
        """Other households of this run near this one: [{household_id, distance_m, same_corner, phone}]."""
        me = self.household(thread)
        if not me:
            return []
        places, my_node = self.bridge.places, self.node(me["household_id"])
        out = []
        for h in self.store.households():
            if h["household_id"] == me["household_id"]:
                continue
            d = places.dist_m(me["lon"], me["lat"], h["lon"], h["lat"])
            if d <= NEAR_M:
                out.append({"household_id": h["household_id"], "distance_m": d,
                            "same_corner": self.node(h["household_id"]) == my_node,
                            "phone": phone_for_thread(self.store, {"household_id": h["household_id"]}) is not None})
        return sorted(out, key=lambda x: x["distance_m"])

    # ---------- sentences ----------
    def why(self, a: dict, thread: dict) -> str:
        """One sentence on why this vehicle and what's ahead on it (household offers)."""
        res = self._resources()
        who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
        n = self.needs(thread)
        chair = bool(n.get("mobility") or n.get("accessible_vehicle"))
        fits = self.fits(thread)
        parts = []
        if len(fits) == 1 and fits[0]["id"] == a["resource_id"]:
            parts.append(f"{who} is the only {'wheelchair-accessible ' if chair else ''}vehicle that fits "
                         f"{plural(n.get('people') or 1, 'person', 'people')}")
        q = self.queue(a["resource_id"])
        ahead = [x for x in q if x["eta_s"] < a["eta_s"] and x["id"] != a["id"]]
        if ahead:
            my_node = self.node(thread["household_id"])
            here = sum(1 for x in ahead if self.node(x["target"]["household_id"]) == my_node)
            parts.append(f"it picks up {plural(len(ahead), 'other household')} first"
                         + (f" ({'it is' if here == 1 else 'they are'} at your corner)" if here and here == len(ahead) else
                            f" ({here} at your corner)" if here else ""))
        mates = self.trip_mates(a)
        if mates:
            parts.append(f"you share the trip with {plural(len(mates), 'other household')}: it collects "
                         f"{'you both' if len(mates) == 1 else 'you all'} before the drop-off")
        if not parts:
            return ""
        s = "; ".join(parts)
        return s[0].upper() + s[1:] + "."

    def vehicles_text(self, thread: dict) -> str:
        res = self._resources()
        n = self.needs(thread)
        if not n:
            return ("Tell us how many people need pickup and whether anyone needs a wheelchair-accessible vehicle, "
                    "and we'll tell you which vehicles can take you.")
        chair = bool(n.get("mobility") or n.get("accessible_vehicle"))
        fits = self.fits(thread)
        others = [r["name"] for r in res.values() if r["kind"] in VEHICLES and r not in fits]
        reserved = set(self._raw().get("reserved") or [])
        rej = self.rejected(thread)
        mine = self.mine(thread)
        lines = []
        for r in fits:
            q = self.queue(r["id"])
            if mine and mine["resource_id"] == r["id"]:
                ahead = sum(1 for x in q if x["eta_s"] < mine["eta_s"])
                doing = "assigned to you" + (f", after {plural(ahead, 'other pickup')}" if ahead else "")
            elif r["id"] in rej:
                doing = "you declined it"
            elif r["id"] in reserved:
                doing = "held in reserve for emergencies"
            elif q:
                doing = f"busy with {plural(len(q), 'pickup')}"
            else:
                doing = "free"
            lines.append(f"{r['name']} ({doing})")
        need = f"{plural(n.get('people') or 1, 'person', 'people')}{' with a wheelchair' if chair else ''}"
        if not fits:
            return f"No vehicle in the fleet fits {need}; a coordinator has been told."
        return (f"Vehicles that fit {need}: " + "; ".join(lines) + "."
                + (f" Not suitable: {', '.join(others)}{' (no wheelchair access or too small)' if chair else ' (too small)'}." if others else ""))

    def others_text(self, thread: dict) -> str:
        near = self.neighbors(thread)
        if not near:
            return "No other household we're helping is near you right now."
        texted = [x for x in near if x["phone"]]
        corner = [x for x in near if x["same_corner"]]
        s = f"{plural(len(near), 'other household')} we're helping {'is' if len(near) == 1 else 'are'} within {int(NEAR_M)} m of you"
        if corner:
            s += f" ({len(corner)} at your pickup corner)"
        s += "."
        mine = self.mine(thread)
        if mine:
            res = self._resources()
            who = res.get(mine["resource_id"], {}).get("name", mine["resource_id"])
            near_ids = {x["household_id"] for x in near}
            shared = [x for x in self.queue(mine["resource_id"]) if x["target"].get("household_id") in near_ids]
            mates = self.trip_mates(mine)
            together = [x for x in shared if x["target"].get("household_id") in mates]
            if shared:
                before = sum(1 for x in shared if x["eta_s"] < mine["eta_s"])
                s += (f" {who} also picks up {plural(len(shared), 'of them', 'of them')}"
                      f" ({before} before you, {len(shared) - before} after)")
                if together:
                    s += (f", and you share the trip with {'it' if len(together) == 1 else len(together)}: {who} "
                          f"collects {'you both' if len(together) == 1 else 'you all'} before the drop-off.")
                else:
                    seats = res.get(mine["resource_id"], {}).get("capacity_people") or 0
                    total = self.people(mine["target"]["household_id"]) + min(
                        self.people(x["target"]["household_id"]) for x in shared)
                    s += (f", on separate trips: together you'd be {total} people and it has {seats} seats."
                          if seats and total > seats else ", on separate trips in this plan.")
            if not together and texted:
                s += " A coordinator can see the request to travel together."
        elif texted:
            s += " A coordinator can see the request to travel together."
        return s

    def flood_text(self, thread: dict) -> str:
        """Where the forecast water is and when it reaches them (the scenario's flood keyframes, D60)."""
        now, margin = self._now(), self.bridge.margin_s
        h = self.household(thread)
        if not h:
            own = ""
        elif h.get("deadline_s") is None:
            own = "Your street is outside the forecast flood area. "
        elif (water := h["deadline_s"] + margin) <= now:
            own = "Your street is flooding now. "
        else:
            own = f"The river reaches your street in about {round((water - now) / 60)} min. "
        first = []
        for d, label in self.bridge.flood_corners(3):
            water = d + margin
            first.append(f"{label} ({'flooding now' if water <= now else 'in about ' + str(round((water - now) / 60)) + ' min'})")
        return own + ("The river flood reaches these corners first: " + "; ".join(first) + "." if first else "")

    def roads_text(self, road: dict | None) -> str:
        """Is <street> open? From the closures in the current picture (flood + reports), whole street by name."""
        now = self._now()
        closed = {c["edge_id"] for c in self.store.snapshot()["closures"] if c.get("closed_from_t_s", 0) <= now}
        names = sorted({self.bridge.edge_name(e) for e in closed if not self.bridge.edge_name(e).startswith("edge ")})
        summary = (f"Closed right now: {', '.join(names[:5])}{' and others' if len(names) > 5 else ''}." if names
                   else "No roads are closed in the current picture.")
        if not road or not road.get("road_hint"):
            return summary + " Vehicles are routed around closed roads."
        edges = self.bridge.named_edges(road["road_hint"], road.get("cross_street"))
        if not edges:
            return f"We couldn't find \"{road['road_hint']}\" on our map. {summary}"
        name = self.bridge.edge_name(edges[0]["id"])
        shut = [e for e in edges if e["id"] in closed]
        if not shut:
            return (f"{name}{' at ' + road['cross_street'] if road.get('cross_street') else ''} is open right now. Roads "
                    f"close as the water rises; if it closes on your route, we re-route and text you.")
        at = sorted({self.bridge.places.corner_label(n) for e in shut for n in (e["u"], e["v"])
                     if len(self.bridge.places.streets.get(n, set())) >= 2})
        return (f"{name} is closed" + (f" near {' and near '.join(at[:2])}" if at else "")
                + ": flooded or reported blocked. Vehicles are routed around it.")

    async def answer(self, topic: str, thread: dict, road: dict | None = None) -> str | None:
        """A question by topic, from the plan. None: this topic has nothing specific for them (no live
        assignment, or not a topic we know) → the caller answers with their whole situation."""
        if topic == "bring":
            return BRING
        if topic == "safety":
            return SAFETY
        if topic == "flood":
            return self.flood_text(thread)
        if topic == "roads":
            return self.roads_text(road)
        if topic == "others":
            return self.others_text(thread)
        if topic == "vehicles":
            return self.vehicles_text(thread)
        if topic not in ("eta", "pickup_place", "destination"):
            return None
        a = self.mine(thread)
        res = self._resources()
        if a is None:
            shelters = [f["name"] for f in self.store.facilities() if f["type"] == "shelter"]
            if topic == "destination" and shelters and "household_id" in thread:  # then what we still need to know
                q = next((x for x in self._view().get("info_requests", []) if x["to"] == thread), None)
                return f"Everyone we pick up goes to {' or '.join(shelters)}." + (f" {ask(q)}" if q else "")
            return None  # nothing scheduled: the status text says why
        who = res.get(a["resource_id"], {}).get("name", a["resource_id"])
        now = self._now()
        o = (await self._outcomes()).get(a["id"], {})
        arrive = o.get("arrive_t") if o.get("arrive_t") is not None else a["eta_s"]
        if "facility_id" in thread:
            if topic == "eta":
                done = o.get("complete_t")
                return (f"{who} reaches you {mins(arrive - now)}"
                        + (f"; it should be connected and powering the site {mins(done - now)}." if done is not None else "."))
            return None
        drop = self._facility_names().get(a.get("dropoff_facility_id") or "", "the shelter")
        pickup, safe = o.get("pickup_t"), o.get("complete_t")
        if topic == "eta":
            s = f"{who} {'is there now' if arrive <= now + 60 else 'reaches you ' + mins(arrive - now)}"
            if safe is not None and safe > now:
                s += f", and you should be at {drop} {mins(safe - now)}"
            h = self.household(thread)
            if h.get("deadline_s") is not None and h["deadline_s"] > now:
                s += f". The pickup has to happen within about {round((h['deadline_s'] - now) / 60)} min, before the water reaches your street"
            return s + "."
        if topic == "destination":
            ride = round((safe - pickup) / 60) if safe is not None and pickup is not None else None
            return f"{who} takes you to {drop}" + (f", about {ride} min from the pickup." if ride else ".")
        n = self.needs(thread)
        if n.get("mobility") or n.get("accessible_vehicle"):
            return f"Stay inside at {(self.home(thread) or (0, 0, 'your address'))[2]}: the crew comes to your door."
        node = self.node(thread["household_id"])
        s = walk_phrase(self.bridge.places, self.home(thread), node) if node is not None else "go to your pickup point"
        return s[0].upper() + s[1:] + "."

    async def _outcomes(self) -> dict[str, dict]:
        plan = self._raw()
        if not plan:
            return {}
        now = self._now()
        known = [r for r in self.store.reports() if r["observed_at_t_s"] <= now]
        return await run_in_threadpool(self.bridge.outcomes, plan, known)
