"""Where a resident is: their words → a point → a household and a pickup corner on the engine's map.

Deterministic, except the optional OpenStreetMap Nominatim lookup, which only turns a street address
or a landmark into coordinates (bounded to the town). Order of attempts (`Gazetteer.locate`):
1. coordinates in the text ("42.3637, -71.1250", or a maps link with ll= / q= / @lat,lon);
2. an intersection of two streets in town.json ("Western Ave and N Harvard St");
3. Nominatim, bounded to the town's box ("125 Western Ave", "Harvard Business School").
Nothing matched, or a point outside the town → None / "outside": the caller asks again, never guesses.

The engine's road graph is coarse (intersections only), so a household's pickup point is an
intersection, often 100–300 m from the door. `corner_label` names it from the streets that meet there.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from .engine_bridge import street_matches

log = logging.getLogger("residents.places")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ember-drill/0.1 (HackHarvard 2026 flood drill; residents backend)"
EDGE_PAD_M = 250.0      # how far outside the road network a point may be and still count as in town
MAX_HOUSEHOLD_M = 400.0  # nearest building farther than this → we can't place them

_COORDS = [
    re.compile(r"[?&](?:ll|q|sll|daddr|saddr)=(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)"),  # maps.apple.com / google ?q=
    re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),                                  # google.com/maps/@lat,lon
    re.compile(r"(?<![\d.])(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)(?![\d.])"),            # typed "42.3637, -71.125"
]
_JOIN = re.compile(r"\s+(?:and|&|at|@|/|x)\s+|\s*&\s*|\s*/\s*", re.I)
_LEAD = re.compile(r"^(?:i'?m|i am|we'?re|we are|at|on|near|corner of|the corner of|by)\s+", re.I)


@dataclass(frozen=True)
class Place:
    lon: float
    lat: float
    label: str     # how we say it back ("125 Western Ave", "Western Avenue and North Harvard Street")
    source: str    # coordinates | intersection | address


def parse_coords(text: str) -> tuple[float, float] | None:
    """(lon, lat) from the first coordinate pair in the text (written lat, lon as maps apps do)."""
    for rx in _COORDS:
        m = rx.search(text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lon, lat
    return None


Geocoder = Callable[[str, tuple[float, float, float, float]], Awaitable[tuple[float, float, str] | None]]


async def nominatim(query: str, box: tuple[float, float, float, float]) -> tuple[float, float, str] | None:
    """OSM's public geocoder, bounded to box = (west, south, east, north). (lon, lat, display) or None.
    One request per text a resident sends; fine for a drill (their policy: ≤ 1 request/s, a real UA)."""
    w, s, e, n = box
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as c:
            r = await c.get(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1, "bounded": 1,
                                               "viewbox": f"{w},{n},{e},{s}", "countrycodes": "us"})
            r.raise_for_status()
            hits = r.json()
    except (httpx.HTTPError, ValueError) as ex:
        log.warning("geocoder failed for %r: %s", query, ex)
        return None
    if not hits:
        return None
    h = hits[0]
    return float(h["lon"]), float(h["lat"]), h.get("display_name", query)


class Gazetteer:
    """Street names, intersections and buildings of town.json, for placing a resident."""

    def __init__(self, town: dict):
        self.nodes = {n["id"]: (n["lon"], n["lat"]) for n in town["nodes"]}
        clon, clat = town["meta"]["center"]
        self._kx = 111_320.0 * math.cos(math.radians(clat))
        self._ky = 110_540.0
        self.edges = town["edges"]
        self.streets: dict[int, set[str]] = {}
        for e in self.edges:
            if e.get("name"):
                for n in (e["u"], e["v"]):
                    self.streets.setdefault(n, set()).add(e["name"])
        self.households = [(h["id"], h["lon"], h["lat"], h["node"]) for h in town["households"]]
        lons = [p[0] for p in self.nodes.values()]
        lats = [p[1] for p in self.nodes.values()]
        pad_lon, pad_lat = EDGE_PAD_M / self._kx, EDGE_PAD_M / self._ky
        self.box = (min(lons) - pad_lon, min(lats) - pad_lat, max(lons) + pad_lon, max(lats) + pad_lat)

    # ---------- geometry ----------
    def dist_m(self, lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        return math.hypot((lon1 - lon2) * self._kx, (lat1 - lat2) * self._ky)

    def in_town(self, lon: float, lat: float) -> bool:
        w, s, e, n = self.box
        return w <= lon <= e and s <= lat <= n

    def bearing(self, lon1: float, lat1: float, lon2: float, lat2: float) -> str:
        """Compass word from point 1 to point 2 ("north", "south-east", ...)."""
        ang = math.degrees(math.atan2((lon2 - lon1) * self._kx, (lat2 - lat1) * self._ky)) % 360
        return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int((ang + 22.5) // 45) % 8]

    # ---------- names ----------
    def corner_label(self, node: int) -> str:
        """'the corner of Western Avenue and North Harvard Street' / 'Western Avenue' / 'the street'."""
        names = sorted(self.streets.get(node, set()))
        if len(names) >= 2:
            return f"the corner of {names[0]} and {names[1]}"
        return names[0] if names else "the nearest street corner"

    def intersection(self, a: str, b: str) -> tuple[float, float, str] | None:
        """The node where streets a and b meet (lon, lat, label), else the closest approach ≤ 60 m."""
        ea = [e for e in self.edges if street_matches(e.get("name"), a)]
        eb = [e for e in self.edges if street_matches(e.get("name"), b)]
        if not ea or not eb:
            return None
        na = {n for e in ea for n in (e["u"], e["v"])}
        nb = {n for e in eb for n in (e["u"], e["v"])}
        label = f"{ea[0]['name']} and {eb[0]['name']}"
        common = sorted(na & nb)
        if common:
            lon, lat = self.nodes[common[0]]
            return lon, lat, label
        best = None
        for e1 in ea:
            for p in e1["geom"]:
                for e2 in eb:
                    for q in e2["geom"]:
                        d = self.dist_m(p[0], p[1], q[0], q[1])
                        if best is None or d < best[0]:
                            best = (d, (p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        if best and best[0] <= 60.0:
            return best[1], best[2], label
        return None

    def nearest_household(self, lon: float, lat: float, exclude: set[int]) -> tuple[int, float] | None:
        """The closest town building (household id, metres) that isn't already someone's household."""
        best = None
        for hid, hlon, hlat, _ in self.households:
            if hid in exclude:
                continue
            d = self.dist_m(lon, lat, hlon, hlat)
            if best is None or d < best[1]:
                best = (hid, d)
        if best is None or best[1] > MAX_HOUSEHOLD_M:
            return None
        return best

    # ---------- words → place ----------
    async def locate(self, text: str, cross_street: str | None = None,
                     geocoder: Geocoder | None = nominatim) -> Place | str | None:
        """Place, or "outside" (found, but not in the drill area), or None (couldn't read it)."""
        c = parse_coords(text)
        if c is not None:
            return Place(c[0], c[1], f"{c[1]:.5f}, {c[0]:.5f}", "coordinates") if self.in_town(*c) else "outside"
        q = _LEAD.sub("", text.strip()).strip(" .!?")
        if not q:
            return None
        parts = [p.strip(" .,") for p in _JOIN.split(q) if p.strip(" .,")]
        pair = (parts[0], parts[1]) if len(parts) == 2 else ((q, cross_street) if cross_street else None)
        if pair and not any(ch.isdigit() for ch in pair[0][:4]):
            hit = self.intersection(*pair)
            if hit is not None:
                return Place(hit[0], hit[1], hit[2], "intersection")
        if geocoder is None:
            return None
        query = q if not cross_street else f"{q} and {cross_street}"
        found = await geocoder(query, self.box)  # bounded: an address outside the town is simply not found
        if found is None:
            return None
        lon, lat, _ = found
        if not self.in_town(lon, lat):
            return "outside"
        return Place(lon, lat, _short(q), "address")


def _short(q: str) -> str:
    """'125 western ave, allston' → '125 Western Ave' (how we echo an address back)."""
    first = q.split(",")[0].strip()
    return " ".join(w if any(ch.isdigit() for ch in w) else w[:1].upper() + w[1:] for w in first.split())

