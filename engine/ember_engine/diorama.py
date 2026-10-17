"""The diorama: the real district as a stylised 3D model's data (D52).

Pulls the most accurate open data for a rectangle around the Treehouse and writes one compact JSON the
web renders (web/public/diorama/<name>.json):

- buildings: City of Boston "Buildings with Roof Breaks" (height per roof part, 2011 LiDAR, feet) and
  City of Cambridge buildings + roofscape attributes (TOP_GL/ELEV_GL feet, RoofType, roof reflectance);
  Overture Maps fills what neither city has (the new Enterprise Research Campus) and lends names/classes.
  Heights from Microsoft ML (5 m low on average here) are never preferred over a city value.
- trees: Cambridge LiDAR crowns 2024 (height, radius) + Boston BPRD street/park trees (DBH → size).
- ground: Overture land use, water (the Charles) and transportation segments (roads, paths).

Raw downloads are cached under data/diorama_raw/ (gitignored). Not in the tick loop; not a contract
between teammates (the web is its only consumer). Every value carries its source; estimates say so.
"""

from __future__ import annotations

import json
import math
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import Point, box, mapping, shape
from shapely.strtree import STRtree

FT = 0.3048
BOSTON_BLDG = "https://gis.bostonplans.org/hosting/rest/services/Boston_Buildings/FeatureServer/9/query"
CAMB = "https://services1.arcgis.com/WnzC35krSYGuYov4/arcgis/rest/services"
CAMB_BLDG = f"{CAMB}/Buildings_Roofscapes_Attributes/FeatureServer/0/query"
CAMB_CANOPY = f"{CAMB}/Tree_Canopy_2024/FeatureServer/0/query"
BOSTON_TREES = "https://services.arcgis.com/sFnw0xNflSi8J0uh/arcgis/rest/services/BPRD_Trees/FeatureServer/0/query"

# Hand-set values for buildings no dataset has a height for yet (Harvard ERC, 2024–26). Estimates, labelled.
ESTIMATES = {
    "treehouse": 20.0,       # 3 storeys incl. double-height atrium + Canopy Hall (Studio Gang); height unpublished
    "atlas hotel": 45.0,     # "tallest and most prominent" on the ERC (Harvard Gazette 2026); height unpublished
    "verra": 58.0,           # 17-storey tower (MVRDV)
    "milestone": 38.0,       # One Milestone East/West, ~9 storeys of lab
}
ERC_UNKNOWN_H = 28.0         # other unnamed new ERC blocks without a height: ~6 lab storeys (estimate)
ERC_RADIUS_M = 320.0


def _estimate(name: str | None) -> float | None:
    low = (name or "").lower()
    return next((h for key, h in ESTIMATES.items() if key in low), None)


def _get(url: str, params: dict, cache: Path, timeout: int = 90) -> dict:
    if cache.exists():
        return json.loads(cache.read_text())
    q = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(q, timeout=timeout) as r:
                data = json.loads(r.read())
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
            return data
        except Exception:  # noqa: BLE001 - flaky public endpoints: retry, then raise
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def arcgis(url: str, bbox: tuple, fields: str, cache_dir: Path, name: str, where: str = "1=1") -> list[dict]:
    """All features in bbox from an ArcGIS FeatureServer as GeoJSON (paged, lon/lat)."""
    out, offset = [], 0
    while True:
        params = {"where": where, "geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope",
                  "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
                  "geometryPrecision": 7, "resultOffset": offset, "resultRecordCount": 2000, "f": "geojson"}
        page = _get(url, params, cache_dir / f"{name}_{offset}.json")
        feats = page.get("features", [])
        out += feats
        if len(feats) < 2000 and not page.get("exceededTransferLimit") and not page.get("properties", {}).get("exceededTransferLimit"):
            return out
        offset += 2000


def overture(kind: str, bbox: tuple, cache_dir: Path) -> list[dict]:
    path = cache_dir / f"overture_{kind}.geojson"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["uvx", "overturemaps", "download", f"--bbox={','.join(map(str, bbox))}", "-f", "geojson",
                        f"--type={kind}", "-o", str(path)], check=True, timeout=600)
    return json.loads(path.read_text()).get("features", [])


def _ring(geom) -> list | None:
    """Largest exterior ring as [[lon, lat], ...] (open), 6 decimals; None if degenerate."""
    if geom.is_empty:
        return None
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)
    if geom.geom_type != "Polygon":
        return None
    pts = [[round(x, 6), round(y, 6)] for x, y in list(geom.exterior.coords)[:-1]]
    return pts if len(pts) >= 3 else None


def _use(*hints: str | None) -> str:
    text = " ".join(h.lower() for h in hints if h)
    if any(k in text for k in ("residential", "apartments", "house", "dormitory", "r1", "r2", "r3", "r4", "detached")):
        return "residential"
    if any(k in text for k in ("university", "education", "college", "school", "library", "e ")):
        return "education"
    if any(k in text for k in ("hospital", "medical", "clinic")):
        return "medical"
    if any(k in text for k in ("industrial", "warehouse", "garage", "parking", "i ")):
        return "industrial"
    if any(k in text for k in ("commercial", "retail", "office", "hotel", "c ")):
        return "commercial"
    return "other"


def build(bbox: tuple, cache_dir: Path, venue_lonlat: tuple | None = None) -> dict:
    """bbox = (west, south, east, north); venue_lonlat names the building it stands in (the Treehouse)."""
    area = box(*bbox)
    venue = Point(*venue_lonlat) if venue_lonlat else None
    lon0, lat0 = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2

    # ---------- buildings ----------
    bos = arcgis(BOSTON_BLDG, bbox, "BLDG_HGT_2010,PART_USE,BRA_Land_Use,IEL_TYPE", cache_dir, "boston_bldg")
    cam = arcgis(CAMB_BLDG, bbox, "TYPE,TOP_GL,ELEV_GL,RoofType,RoofReflect2021_2_n,BldgID", cache_dir, "camb_bldg")
    ov = overture("building", bbox, cache_dir)

    ov_rows = []
    for f in ov:
        try:
            g = shape(f["geometry"])
        except Exception:  # noqa: BLE001
            continue
        p = f.get("properties", {})
        names = p.get("names") or {}
        name = names.get("primary") if isinstance(names, dict) else None
        srcs = p.get("sources") or []
        hsrc = next((s.get("dataset") for s in srcs if isinstance(s, dict) and s.get("property") in ("/properties/height", "properties/height")), None)
        ov_rows.append({"g": g, "name": name, "class": p.get("class"), "subtype": p.get("subtype"), "height": p.get("height"),
                        "floors": p.get("num_floors"), "roof": p.get("roof_shape"), "hsrc": hsrc or ""})
    ov_tree = STRtree([r["g"] for r in ov_rows]) if ov_rows else None

    def ov_at(pt: Point) -> dict | None:
        if ov_tree is None:
            return None
        for i in ov_tree.query(pt):
            if ov_rows[int(i)]["g"].contains(pt):
                return ov_rows[int(i)]
        return None

    buildings, city_polys = [], []
    for f in bos:
        p = f.get("properties", {})
        if (p.get("IEL_TYPE") or "BLDG") not in ("BLDG", "OUTBLDG"):
            continue
        g = shape(f["geometry"]).intersection(area) if f.get("geometry") else None
        ring = _ring(g) if g is not None else None
        if not ring:
            continue
        h = p.get("BLDG_HGT_2010")
        o = ov_at(g.representative_point())
        buildings.append({"ring": ring, "h": round(h * FT, 1) if h else None, "eave": None, "roof": "flat",
                          "use": _use(p.get("PART_USE"), p.get("BRA_Land_Use"), o and o["class"], o and o["subtype"]),
                          "name": o and o["name"], "src": "boston"})
        city_polys.append(g)
    bos_tree = STRtree(city_polys) if city_polys else None
    for f in cam:
        p = f.get("properties", {})
        if (p.get("TYPE") or "BLDG") not in ("BLDG", "OUTBLDG"):
            continue
        g = shape(f["geometry"]).intersection(area) if f.get("geometry") else None
        ring = _ring(g) if g is not None else None
        if not ring:
            continue
        pt = g.representative_point()
        if bos_tree is not None and any(city_polys[int(i)].contains(pt) for i in bos_tree.query(pt)):
            continue  # Cambridge's 200 ft buffer overlaps Boston: Boston wins on its side
        top, eave = p.get("TOP_GL"), p.get("ELEV_GL")
        roof = {"Pitched": "pitched", "Flat": "flat", "Hybrid": "hybrid"}.get(p.get("RoofType") or "", "flat")
        o = ov_at(pt)
        buildings.append({"ring": ring, "h": round(top * FT, 1) if top else None,
                          "eave": round(eave * FT, 1) if eave else None, "roof": roof,
                          "tone": p.get("RoofReflect2021_2_n"),
                          "use": _use(o and o["class"], o and o["subtype"]), "name": o and o["name"], "src": "cambridge"})
        city_polys.append(g)
    all_city = STRtree(city_polys) if city_polys else None
    for r in ov_rows:
        g = r["g"].intersection(area)
        ring = _ring(g)
        if not ring:
            continue
        pt = g.representative_point()
        if all_city is not None and any(city_polys[int(i)].contains(pt) for i in all_city.query(pt)):
            continue
        h = r["height"]
        if h and "microsoft" in r["hsrc"].lower():
            h = h + 5.0  # Microsoft ML heights run ~5 m low here (checked against both cities)
        name = r["name"]
        if venue is not None and r["g"].contains(venue):
            name = name or "David Rubenstein Treehouse"  # OSM way 1338781017 carries no name in Overture
        est = _estimate(name)
        src = "overture"
        if est:
            h, src = est, "estimate"
        elif not h and r["floors"]:
            h, src = r["floors"] * 3.4, "overture-floors"
        elif not h and venue is not None and g.distance(venue) * 82_000 < ERC_RADIUS_M and g.area * 82_000 * 111_000 > 600:
            h, src = ERC_UNKNOWN_H, "estimate"
        roof = {"gabled": "pitched", "hipped": "pitched", "saltbox": "pitched", "mansard": "pitched"}.get(r["roof"] or "", "flat")
        buildings.append({"ring": ring, "h": round(h, 1) if h else None, "eave": None, "roof": roof,
                          "use": _use(r["class"], r["subtype"]), "name": name, "src": src})
    for b in buildings:
        if not b["h"]:
            b["h"], b["src"] = (8.0 if b["use"] != "residential" else 9.5), b["src"] + "+default-height"
        if b["roof"] == "pitched" and not b.get("eave"):
            b["eave"] = round(b["h"] * 0.78, 1)
        if b.get("name") is None:
            b.pop("name", None)
        if b.get("eave") is None:
            b.pop("eave", None)
        if b.get("tone") is None:
            b.pop("tone", None)

    # ---------- trees ----------
    trees = []
    for f in arcgis(CAMB_CANOPY, bbox, "Height_ft,Radius", cache_dir, "camb_canopy"):
        p = f.get("properties", {})
        try:
            c = shape(f["geometry"]).centroid
        except Exception:  # noqa: BLE001
            continue
        if not area.contains(c):
            continue
        h = (p.get("Height_ft") or 30) * FT
        r = (p.get("Radius") or 10) * (FT if (p.get("Radius") or 0) > 3 else 1)
        trees.append([round(c.x, 6), round(c.y, 6), round(min(h, 30), 1), round(min(max(r, 1.5), 12), 1), 0])
    for f in arcgis(BOSTON_TREES, bbox, "dbh", cache_dir, "boston_trees"):
        g = f.get("geometry")
        if not g:
            continue
        c = shape(g)
        if not area.contains(c):
            continue
        dbh = (f.get("properties") or {}).get("dbh") or 10
        try:
            dbh = float(dbh)
        except (TypeError, ValueError):
            dbh = 10.0
        trees.append([round(c.x, 6), round(c.y, 6), round(min(4 + 0.45 * dbh, 22), 1), round(min(1.5 + 0.22 * dbh, 9), 1), 1])

    # ---------- ground ----------
    land = []
    for f in overture("land_use", bbox, cache_dir):
        p = f.get("properties", {})
        g = shape(f["geometry"]).intersection(area)
        for part in getattr(g, "geoms", [g]):
            ring = _ring(part)
            if ring:
                land.append({"ring": ring, "k": p.get("class") or p.get("subtype") or "other", "sub": p.get("subtype")})
    water = []
    for f in overture("water", bbox, cache_dir):
        g = shape(f["geometry"]).intersection(area)
        for part in getattr(g, "geoms", [g]):
            if part.geom_type == "Polygon" and part.area > 0:
                water.append({"ring": _ring(part), "holes": [[[round(x, 6), round(y, 6)] for x, y in list(h.coords)[:-1]] for h in part.interiors]})
    roads = []
    for f in overture("segment", bbox, cache_dir):
        p = f.get("properties", {})
        if p.get("subtype") not in (None, "road"):
            continue
        g = shape(f["geometry"]).intersection(area)
        for part in getattr(g, "geoms", [g]):
            if part.geom_type == "LineString" and part.length > 0:
                roads.append({"path": [[round(x, 6), round(y, 6)] for x, y in part.coords], "k": p.get("class") or "unknown"})

    return {
        "version": "0.1",
        "bbox": list(bbox),
        "origin": [lon0, lat0],
        "attribution": "Buildings and trees: City of Boston (Planning Dept GIS Lab, BPRD) and City of Cambridge GIS, PDDL. "
                       "© OpenStreetMap contributors (ODbL) via Overture Maps Foundation. Colours, roof forms where unmeasured, "
                       "and heights marked 'estimate' or 'default-height' are synthetic.",
        "counts": {"buildings": len(buildings), "trees": len(trees), "land": len(land), "water": len(water), "roads": len(roads)},
        "buildings": buildings,
        "trees": trees,
        "land": land,
        "water": water,
        "roads": roads,
    }


def rect_around(lon: float, lat: float, half_w_m: float, half_h_m: float, dx_m: float = 0.0, dy_m: float = 0.0) -> tuple:
    k = math.cos(math.radians(lat))
    cx, cy = lon + dx_m / (111_320 * k), lat + dy_m / 110_540
    return (round(cx - half_w_m / (111_320 * k), 6), round(cy - half_h_m / 110_540, 6),
            round(cx + half_w_m / (111_320 * k), 6), round(cy + half_h_m / 110_540, 6))


def bbox_mapping(bbox: tuple) -> dict:
    return mapping(box(*bbox))
