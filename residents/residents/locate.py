"""A resident who isn't on the map yet texts where they are; we put them there (D56).

A phone registered with `locate` has no household. Its texts come here (Messenger lobby hook):
1. ask where they are (first text, or anything without a place in it);
2. the LLM pulls out the place as written (and any needs they mentioned), deterministic code turns it
   into a point (places.Gazetteer: coordinates → intersection → address lookup bounded to the town);
3. the nearest town building nobody else has becomes their household (needs unknown) in this run, the
   phone is bound to it, and we replan once: the plan asks its own question ("How many people…") or,
   if they already said, makes an offer. From then on the normal path (Intake) handles their texts.
Nothing is guessed: no place, or a place outside the town → we ask again.

A drill player (texted the join phrase, D78) isn't asked: we choose where they live, a free town building
the forecast flood reaches, and a burst of joins shares one replan.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter

from starlette.concurrency import run_in_threadpool

from .db import Store, thread_key
from .extract import LLM, NEED_FIELDS, SYSTEM, build_prompt
from .messaging import FULL, Messenger
from .places import Geocoder, Place, nominatim, parse_coords
from .planner import Planner
from .threads import player, unplaced

log = logging.getLogger("residents.locate")

AREA = "Allston and the Cambridge riverside, around Harvard Business School and the Treehouse"
WELCOME = ("Welcome to the EMBER flood drill. Where are you right now? Reply with your street address "
           "(e.g. 125 Western Ave) or the nearest intersection (e.g. Western Ave and N Harvard St).")
ASK = "Where are you right now? Send your street address or the nearest intersection (e.g. Putnam Ave and Western Ave)."
ASK_AFTER_NEEDS = "Thanks, noted. Where are you right now? Send your street address or the nearest intersection."
NOT_FOUND = ("We couldn't find \"{q}\" in the drill area ({area}). Send a street address or the two nearest "
             "cross streets there.")
OUTSIDE = "That spot is outside the drill area ({area}). Send an address or intersection inside it."
NO_BUILDING = "We couldn't match that spot to a building on our map. Send your street address, please."
PLACED = "Got it: we have you at {label}. Your nearest pickup point is {corner}."
ASK_FIRST = "We can tell you exactly what to do once we know where you are. "  # a question before a place (D60)
JOINED = "Welcome to the EMBER flood drill. You're Player {n}: for this drill you live by {corner}, your pickup point."
JOIN_LEAD_S = 1200.0    # a player's building floods at least this long after they join, so they can still be saved
JOIN_DEBOUNCE_S = 2.0   # joins this close together share one replan


class Locator:
    def __init__(self, store: Store, messenger: Messenger, planner: Planner, llm: LLM | None = None,
                 geocoder: Geocoder | None = nominatim, drill_tips: bool = False):
        self.store, self.messenger, self.planner, self.llm = store, messenger, planner, llm
        self.geocoder = geocoder
        self.drill_tips = drill_tips  # the drill: tell testers outside the flood where to text instead
        self._lock = asyncio.Lock()  # one placement at a time: two phones must not take the same building
        self.replan_task: asyncio.Task | None = None  # the replan waiting for a burst of joins to end
        self._last_join = 0.0

    @property
    def places(self):
        return self.planner.bridge.places

    # ---------- welcome ----------
    async def welcome(self) -> int:
        """Ask every opted-in, unplaced phone where it is (once per run). Returns how many were asked."""
        n = 0
        for p in self.store.phones():
            if not unplaced(self.store, p) or player(self.store, p["handle"]) or (
                    self.messenger.photon is not None and not self.messenger.opted_in(p)):
                continue  # a shared line can't text first: they get the welcome when they text in
            if self.store.kv_get(f"welcomed:{p['handle']}"):
                continue
            delivery = await self.messenger.send_to_phone(p["handle"], WELCOME)
            if delivery in ("sent", "dev", "failed"):
                self.store.kv_set(f"welcomed:{p['handle']}", "1")
                n += 1
        return n

    async def on_plan(self, view: dict, raw: dict | None = None) -> None:
        if view.get("version") == 1:  # a fresh run (startup reseed / reset): players get a new building, others start over
            for p in self.store.phones():
                if player(self.store, p["handle"]):
                    await self.on_lobby(p, "")
            await self.welcome()

    # ---------- a text from an unplaced phone ----------
    async def on_lobby(self, phone: dict, text: str) -> None:
        async with self._lock:
            phone = self.store.phone(handle=phone["handle"])
            if phone is None or not unplaced(self.store, phone):
                return  # placed meanwhile (a second text raced the first)
            if player(self.store, phone["handle"]):
                await self._join(phone)
            else:
                await self._handle(phone, text)

    def _needs_key(self, handle: str) -> str:
        return f"lobby:{handle}:needs"

    async def _handle(self, phone: dict, text: str) -> None:
        handle = phone["handle"]
        welcomed = bool(self.store.kv_get(f"welcomed:{handle}"))
        where, cross, needs, asked = await self._read(handle, text)
        if needs:
            known = json.loads(self.store.kv_get(self._needs_key(handle)) or "{}")
            self.store.kv_set(self._needs_key(handle), json.dumps({**known, **needs}))
        if where is None:
            self.store.kv_set(f"welcomed:{handle}", "1")
            if asked:  # "what's going on?": the honest answer is that it depends on where they are
                await self.messenger.send_to_phone(handle, ASK_FIRST + (WELCOME if not welcomed else ASK))
                return
            await self.messenger.send_to_phone(handle, ASK_AFTER_NEEDS if needs else ASK if welcomed else WELCOME)
            return
        found = await self.places.locate(where, cross, self.geocoder)
        if found == "outside":
            await self.messenger.send_to_phone(handle, OUTSIDE.format(area=AREA))
            return
        if found is None:
            q = where if not cross else f"{where} and {cross}"
            await self.messenger.send_to_phone(handle, NOT_FOUND.format(q=q, area=AREA))
            return
        await self.place(phone, found)

    async def _read(self, handle: str, text: str) -> tuple[str | None, str | None, dict, bool]:
        """(place as written, cross street, need fields, asked a question) from one text."""
        if parse_coords(text) is not None:
            return text, None, {}, False
        if self.llm is None:  # no extraction: take the text as the place if it looks like one
            looks = any(ch.isdigit() for ch in text) or any(w in text.lower() for w in (" and ", "&", " st", " ave", " street", " road"))
            return (text if looks else None), None, {}, False
        last = next((m["text"] for m in reversed(self.messenger.lobby_log(handle)) if m["direction"] == "out"), None)
        try:
            log_ = self.messenger.lobby_log(handle)
            history = [{"from": "them" if m["direction"] == "in" else "EMBER", "text": m["text"].removeprefix("[EMBER drill] ")}
                       for m in log_[:-1][-8:]]
            ex = await self.llm(SYSTEM, build_prompt(text, "resident", {}, last,
                                                     {"kind": "location", "note": "we don't know where the sender is yet"},
                                                     history))
        except Exception as e:  # noqa: BLE001 - API down: keyword parser for needs/questions, the text as a place if it looks like one
            log.error("location extraction failed: %r", e)
            from . import fallback
            ex = fallback.parse(text)
            needs = {k: getattr(f, k) for f in (ex.facts if ex else []) if f.kind == "need"
                     for k in NEED_FIELDS if getattr(f, k) is not None}
            asked = bool(ex and any(f.kind == "question" for f in ex.facts))
            low = text.lower()
            looks = bool(fallback.STREET.search(low)) or (("and" in low.split() or "&" in low) and not needs)  # street / intersection
            return (text if looks else None), None, needs, asked
        where = cross = None
        needs: dict = {}
        for f in ex.facts:
            if f.kind == "location" and f.address and where is None:
                where, cross = f.address, f.cross_street
            if f.kind == "need":
                needs.update({k: getattr(f, k) for k in NEED_FIELDS if getattr(f, k) is not None})
        return where, cross, needs, any(f.kind == "question" for f in ex.facts)

    # ---------- placing ----------
    def _taken(self) -> set[int]:
        return {h["household_id"] for h in self.store.households()} | {h["household_id"] for h in self.planner.extra_households()}

    async def _join(self, phone: dict) -> None:
        """A drill player lives in a free town building the forecast flood reaches more than JOIN_LEAD_S from
        now, at the pickup corner with the fewest households so far (players spread out), earliest flood first."""
        bridge = self.planner.bridge
        taken = self._taken()
        per_corner = Counter(bridge.household_node(h) for h in taken)
        soon = self.planner.now() + JOIN_LEAD_S
        free = [(per_corner[node], d, hid, node) for d, hid, node in await run_in_threadpool(bridge.flood_buildings)
                if d > soon and hid not in taken]
        if not free:
            await self.messenger.send_to_phone(phone["handle"], FULL)
            return
        _, _, hid, node = min(free)
        lon, lat = next((x, y) for h, x, y, _ in self.places.households if h == hid)
        await self.place(phone, Place(lon, lat, self.places.corner_label(node), "player"), player(self.store, phone["handle"]))

    def _replan_soon(self) -> None:
        self._last_join = time.monotonic()
        if self.replan_task is None:
            self.replan_task = asyncio.create_task(self._replan_after_joins())

    async def _replan_after_joins(self) -> None:
        while (wait := self._last_join + JOIN_DEBOUNCE_S - time.monotonic()) > 0:
            await asyncio.sleep(wait)
        self.replan_task = None  # a join from here on waits for the next replan
        try:
            await self.planner.replan(trigger="drill players joined")
        except Exception:  # noqa: BLE001 - placed; the next replan picks them up
            log.exception("replan after players joined failed")

    async def place(self, phone: dict, where: Place, as_player: int | None = None) -> dict | None:
        """Bind `phone` to the nearest free building at `where` and replan (a player: once their burst of joins
        is over). Returns the new thread."""
        handle = phone["handle"]
        bridge = self.planner.bridge
        hit = self.places.nearest_household(where.lon, where.lat, exclude=self._taken())
        if hit is None:
            await self.messenger.send_to_phone(handle, NO_BUILDING)
            return None
        hid, dist = hit
        corner = self.places.corner_label(bridge.household_node(hid))
        label = f"Player {as_player}" if as_player else f"{where.label} (texted in)"
        await self.planner.add_household({"household_id": hid, "label": label, "needs": "unknown",
                                          "lon": where.lon, "lat": where.lat, "handle": handle})
        deadline = bridge.deadline(hid)
        now = self.planner.now()
        if deadline is None:
            flood = " Your street is outside the forecast flood area."
            corners = bridge.flood_corners(1) if self.drill_tips else []
            if corners:
                flood += (f" (Drill tip: to test an evacuation, start over from a spot the water reaches, "
                          f"e.g. {corners[0][1]}.)")
        elif (m := round((deadline + bridge.margin_s - now) / 60)) > 0:
            flood = f" Water is forecast to reach your street in about {m} min."
        else:
            flood = " Your street is flooding now."
        intro = JOINED.format(n=as_player, corner=corner) if as_player else PLACED.format(label=where.label, corner=corner)
        await self.messenger.send_to_phone(handle, intro + flood)
        thread = {"household_id": hid}
        self.store.kv_set(f"located:{handle}", json.dumps({"household_id": hid, "lon": where.lon, "lat": where.lat,
                                                          "label": where.label, "source": where.source,
                                                          "building_m": round(dist)}))
        self.store.upsert_phone(handle, "resident", thread_key=thread_key(thread))
        self.messenger.move_lobby_to_thread(handle, thread)
        log.info("%s placed at %s → household #%s (%d m from the building)", handle, where.label, hid, dist)
        needs = json.loads(self.store.kv_get(self._needs_key(handle)) or "{}")
        self.store.kv_delete(self._needs_key(handle))
        if needs.get("people"):
            await self.planner.submit_report({"source": "resident", "kind": "need", "household_id": hid, "payload": needs,
                                              "confidence": 1.0, "text": "(from their first texts)"}, replan=False)
        elif needs:  # e.g. "my mom uses a wheelchair" but no head count: the plan's question completes it
            self.store.kv_set(f"pending:{thread_key(thread)}", json.dumps({"kind": "need", **needs}))
        if as_player:
            self._replan_soon()
            return thread
        try:
            await self.planner.replan(trigger=f"household #{hid} texted their location ({where.label})")
        except Exception:  # noqa: BLE001 - placed; the next text or replan picks it up
            log.exception("replan after placing %s failed", handle)
        return thread
