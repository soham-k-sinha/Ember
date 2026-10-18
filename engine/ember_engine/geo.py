"""Local equirectangular projection helpers (meters around a center).

Good to <0.1% over a few km, which is all the engine needs. Everything stored
on disk stays [lon, lat]; the engine works in local meters.
"""

from __future__ import annotations

import math

import numpy as np

EARTH_R = 6371008.8


def local_projector(lon0: float, lat0: float):
    k = float(np.cos(np.radians(lat0)))

    def to_xy(lon, lat):
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        return np.radians(lon - lon0) * EARTH_R * k, np.radians(lat - lat0) * EARTH_R

    def to_lonlat(x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        return lon0 + np.degrees(x / (EARTH_R * k)), lat0 + np.degrees(y / EARTH_R)

    return to_xy, to_lonlat


def metres_per_deg(lat: float) -> tuple[float, float]:
    """Metres per degree of longitude and of latitude at `lat` (WGS84)."""
    return 111_320 * math.cos(math.radians(lat)), 110_540


def local_metres(a, b) -> float:
    """Metres between two [lon, lat] points a few km apart."""
    mx, my = metres_per_deg((a[1] + b[1]) / 2)
    return math.hypot((b[0] - a[0]) * mx, (b[1] - a[1]) * my)


def heading_to_unit(heading_deg: float) -> tuple[float, float]:
    """Compass heading (0 = north, 90 = east) → unit vector (dx, dy) in local meters."""
    h = np.radians(heading_deg)
    return float(np.sin(h)), float(np.cos(h))
