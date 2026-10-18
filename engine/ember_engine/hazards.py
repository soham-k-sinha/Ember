"""Hazards: anything that closes roads over time.

Interface:
    polygon_at(t_s) -> shapely Polygon | None   (local meters)
    closed_mask_at(t_s, world) -> np.ndarray[bool] over edges

The engine never knows what kind of hazard it is.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Point, Polygon

from .geo import heading_to_unit


class Hazard(Protocol):
    def polygon_at(self, t_s: float):
        ...

    def closed_mask_at(self, t_s: float, world) -> np.ndarray:
        ...


def _edges_touching(polygon, world) -> np.ndarray:
    if polygon is None or polygon.is_empty:
        return np.zeros(world.n_edges, dtype=bool)
    # edge closed when its geometry touches the polygon (catches long edges with no vertex inside)
    shapely.prepare(polygon)
    return shapely.intersects(polygon, world.edge_lines())


class _Cached:
    recompute_every_s: float = 60.0

    def __init__(self):
        self._last_bucket = None
        self._last_mask = None

    def closed_mask_at(self, t_s: float, world) -> np.ndarray:
        b = int(t_s // self.recompute_every_s)
        if b != self._last_bucket:
            self._last_mask = _edges_touching(self.polygon_at(t_s), world)
            self._last_bucket = b
        return self._last_mask


class GrowingEllipseHazard(_Cached):
    """Wind-driven front: an ellipse that grows from an ignition point and drifts downwind.

    origin: (lon, lat) of the local frame (the world's center); center: (lon, lat) of ignition;
    heading_deg: compass direction the front moves toward; speed_mps: growth of the semi-major axis; ratio: length/breadth.
    """

    def __init__(self, origin_lonlat, center_lonlat, start_t_s=0.0, speed_mps=0.6, heading_deg=90.0, ratio=2.5, min_radius_m=60.0):
        super().__init__()
        from .geo import local_projector
        to_xy, _ = local_projector(*origin_lonlat)
        cx, cy = to_xy(center_lonlat[0], center_lonlat[1])
        self.cx, self.cy = float(cx), float(cy)
        self.start, self.speed, self.heading, self.ratio, self.min_r = start_t_s, speed_mps, heading_deg, ratio, min_radius_m

    def polygon_at(self, t_s: float):
        if t_s < self.start:
            return None
        a = self.min_r + self.speed * (t_s - self.start)      # semi-major (m)
        b = max(self.min_r * 0.6, a / self.ratio)              # semi-minor
        dx, dy = heading_to_unit(self.heading)
        # drift downwind: the ignition point stays near the upwind end
        cx, cy = self.cx + dx * (a - self.min_r) * 0.6, self.cy + dy * (a - self.min_r) * 0.6
        ell = Point(0, 0).buffer(1.0, quad_segs=24)
        ell = affinity.scale(ell, xfact=b, yfact=a, origin=(0, 0))      # major axis along +y (north)
        ell = affinity.rotate(ell, -self.heading, origin=(0, 0))        # compass → math rotation
        return affinity.translate(ell, cx, cy)


class KeyframePolygonHazard(_Cached):
    """Stepwise polygons (e.g. flood extents from public layers): the latest keyframe ≤ t applies.

    keyframes: list of (t_s, [[lon,lat],...]) rings in lon/lat; converted to local meters.
    """

    def __init__(self, world, keyframes):
        super().__init__()
        from .geo import local_projector
        to_xy, _ = local_projector(*world.center)
        self.frames = []
        for t, ring in sorted(keyframes, key=lambda k: k[0]):
            r = np.asarray(ring, dtype=np.float64)
            x, y = to_xy(r[:, 0], r[:, 1])
            self.frames.append((float(t), Polygon(np.c_[x, y])))

    def polygon_at(self, t_s: float):
        poly = None
        for t, p in self.frames:
            if t <= t_s:
                poly = p
            else:
                break
        return poly


class NoHazard(_Cached):
    def polygon_at(self, t_s: float):
        return None


def ellipse_from(origin_lonlat, h: dict) -> GrowingEllipseHazard:
    """An `ellipse` hazard spec (job or scenario contract) in the local frame around origin."""
    return GrowingEllipseHazard(origin_lonlat, h.get("center", origin_lonlat), start_t_s=h.get("start_t_s", 0.0),
                                speed_mps=h.get("speed_mps", 0.6), heading_deg=h.get("heading_deg", 90.0), ratio=h.get("ratio", 2.5))


def hazard_from_scenario(world, scenario: dict) -> Hazard:
    h = scenario.get("hazard", {"type": "none"})
    typ = h.get("type", "none")
    if typ == "ellipse":
        return ellipse_from(world.center, h)
    if typ == "keyframes":
        return KeyframePolygonHazard(world, h["keyframes"])
    if typ == "flood_keyframes":   # scenario.schema.json: [{t_s, geometry: GeoJSON Polygon|MultiPolygon}]
        from .scenario import flood_keyframes
        hz = KeyframePolygonHazard(world, [])
        hz.frames = flood_keyframes(scenario, world)
        return hz
    return NoHazard()
