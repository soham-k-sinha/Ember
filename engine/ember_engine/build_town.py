"""Build data/town.json from OpenStreetMap around the venue.

    uv run ember build --dist 1200

Everything synthetic (household counts, vehicles, flags, capacities) is
generated with a fixed seed and labeled in meta.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

VENUE_QUERIES = [
    "David Rubenstein Treehouse, Boston, MA",
    "150 Western Avenue, Boston, MA 02134",
    "Western Avenue & North Harvard Street, Boston, MA",
]
# Harvard Enterprise Research Campus, Allston (approximate; used only if geocoding fails).
VENUE_FALLBACK_LATLON = (42.3645, -71.1232)

LANES_BY_HIGHWAY = {
    "motorway": 3, "motorway_link": 1, "trunk": 2, "trunk_link": 1,
    "primary": 2, "primary_link": 1, "secondary": 2, "secondary_link": 1,
    "tertiary": 1, "tertiary_link": 1, "residential": 1, "unclassified": 1,
    "living_street": 1, "service": 1, "road": 1,
}
SATURATION_FLOW_VPH_PER_LANE = 1800   # standard planning value
JAM_DENSITY_VPKM_PER_LANE = 150       # standard planning value

NON_RESIDENTIAL = {
    "commercial", "retail", "industrial", "office", "school", "university", "college",
    "hospital", "church", "cathedral", "chapel", "mosque", "synagogue", "garage", "garages",
    "parking", "warehouse", "hotel", "stadium", "roof", "shed", "service", "kiosk", "public",
    "government", "civic", "greenhouse", "hangar", "transportation", "train_station",
    "sports_hall", "sports_centre", "grandstand", "pavilion", "library", "museum", "boathouse",
    "carport", "construction", "bridge", "toilets", "fire_station", "police", "supermarket",
    "temple", "shrine", "gatehouse", "barn", "farm_auxiliary", "silo", "storage_tank", "ruins",
}
SINGLE_FAMILY = {"house", "detached", "semidetached_house", "bungalow", "villa", "cabin"}
MULTI_FAMILY = {"apartments", "residential"}

ASSET_TAGS = {
    "amenity": ["hospital", "clinic", "fire_station", "police"],
    "power": ["substation", "plant"],
    "man_made": ["pumping_station", "water_works", "wastewater_plant", "water_tower", "storage_tank"],
    "emergency": ["ambulance_station"],
}


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _parse_int_tag(v) -> int | None:
    v = _first(v)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return int(float(str(v).split(";")[0]))
    except ValueError:
        return None


def _is_nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def geocode_venue():
    import osmnx as ox

    for q in VENUE_QUERIES:
        try:
            lat, lon = ox.geocode(q)
            return q, float(lat), float(lon)
        except Exception:  # noqa: BLE001 — geocoder misses are expected; fall through
            continue
    return "fallback", *VENUE_FALLBACK_LATLON


def kmeans(xy: np.ndarray, k: int, rng: np.random.Generator, iters: int = 25) -> np.ndarray:
    centers = xy[rng.choice(len(xy), size=k, replace=False)]
    labels = np.zeros(len(xy), dtype=np.int64)
    for _ in range(iters):
        d = ((xy[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
        labels = d.argmin(1)
        for j in range(k):
            m = labels == j
            if m.any():
                centers[j] = xy[m].mean(0)
    return labels


def build(center_latlon: tuple[float, float] | None = None, dist_m: int = 1200,
          out: Path = Path("../data/town.json"), seed: int = 7, with_walk: bool = True) -> dict:
    import osmnx as ox
    from shapely.geometry import LineString

    ox.settings.use_cache = True
    ox.settings.log_console = False
    t0 = time.time()
    rng = np.random.default_rng(seed)

    venue_src, vlat, vlon = geocode_venue()
    if center_latlon is None:
        center_latlon = (vlat, vlon)
    clat, clon = center_latlon
    print(f"[build] venue via {venue_src!r} at lat={vlat:.5f} lon={vlon:.5f}; center=({clat:.5f},{clon:.5f}) dist={dist_m} m")

    # ---------- drive network ----------
    G = ox.graph_from_point((clat, clon), dist=dist_m, network_type="drive", simplify=True)
    G = ox.routing.add_edge_speeds(G)
    G = ox.routing.add_edge_travel_times(G)
    nodes_gdf, edges_gdf = ox.convert.graph_to_gdfs(G, nodes=True, edges=True, fill_edge_geometry=True)
    print(f"[build] drive graph: {len(nodes_gdf)} nodes, {len(edges_gdf)} edges ({time.time()-t0:.1f}s)")

    node_ids = list(nodes_gdf.index)
    node_pos = {nid: i for i, nid in enumerate(node_ids)}
    nodes = [{"id": int(nid), "lon": round(float(r.x), 6), "lat": round(float(r.y), 6)}
             for nid, r in nodes_gdf.iterrows()]

    edges = []
    for eid, ((u, v, key), r) in enumerate(edges_gdf.iterrows()):
        hwy = _first(r.get("highway")) or "unclassified"
        oneway = bool(r.get("oneway")) if not _is_nan(r.get("oneway")) else False
        lanes_tag = _parse_int_tag(r.get("lanes"))
        if lanes_tag:
            lanes = max(1, round(lanes_tag / (1 if oneway else 2)))
        else:
            lanes = LANES_BY_HIGHWAY.get(hwy, 1)
        length = float(r["length"])
        speed_kph = float(r.get("speed_kph") or 30.0)
        tt = float(r.get("travel_time") or (length / (speed_kph / 3.6)))
        geom = r.geometry if r.geometry is not None else LineString([(nodes_gdf.loc[u].x, nodes_gdf.loc[u].y), (nodes_gdf.loc[v].x, nodes_gdf.loc[v].y)])
        coords = [[round(x, 6), round(y, 6)] for x, y in geom.coords]
        name = _first(r.get("name"))
        edges.append({
            "id": eid, "u": int(u), "v": int(v), "key": int(key),
            "length_m": round(length, 1), "lanes": int(lanes), "speed_kph": round(speed_kph, 1),
            "travel_time_s": round(tt, 1),
            "capacity_vph": int(lanes * SATURATION_FLOW_VPH_PER_LANE),
            "storage_veh": max(1, int(round(lanes * length / 1000.0 * JAM_DENSITY_VPKM_PER_LANE))),
            "oneway": oneway, "highway": hwy, "name": None if _is_nan(name) else str(name),
            "geom": coords,
        })

    # ---------- exits: boundary nodes ----------
    from .geo import local_projector
    to_xy, _ = local_projector(clon, clat)
    nx_, ny_ = to_xy(nodes_gdf.x.values, nodes_gdf.y.values)
    ndist = np.hypot(nx_, ny_)
    deg = dict(G.degree())
    exits = [int(nid) for nid, d in zip(node_ids, ndist) if d > 0.9 * dist_m and deg.get(nid, 0) <= 2]
    # keep nodes that actually have an incoming edge (reachable)
    has_in = {e["v"] for e in edges}
    exits = [n for n in exits if n in has_in]
    print(f"[build] exits (boundary nodes): {len(exits)}")

    # ---------- walk network (optional) ----------
    paths = []
    if with_walk:
        try:
            Gw = ox.graph_from_point((clat, clon), dist=dist_m, network_type="walk", simplify=True)
            _, wedges = ox.convert.graph_to_gdfs(Gw, nodes=False, edges=True, fill_edge_geometry=True)
            for pid, ((u, v, key), r) in enumerate(wedges.iterrows()):
                if not bool(r.get("oneway")) and u > v:
                    continue  # one record per undirected footway
                paths.append({"id": pid, "u": int(u), "v": int(v), "length_m": round(float(r["length"]), 1),
                              "highway": _first(r.get("highway")),
                              "geom": [[round(x, 6), round(y, 6)] for x, y in r.geometry.coords]})
            print(f"[build] walk network: {len(paths)} path segments ({time.time()-t0:.1f}s)")
        except Exception as ex:  # noqa: BLE001
            print(f"[build] walk network skipped: {ex}")

    # ---------- buildings → households ----------
    bld = ox.features_from_point((clat, clon), tags={"building": True}, dist=dist_m)
    bld = bld[bld.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    bld_p = ox.projection.project_gdf(bld)
    bld["area_m2"] = bld_p.geometry.area.values
    cent = bld_p.geometry.centroid
    cent_ll = cent.to_crs(epsg=4326)
    bld["clon"] = cent_ll.x.values
    bld["clat"] = cent_ll.y.values
    print(f"[build] building footprints: {len(bld)} ({time.time()-t0:.1f}s)")

    households = []
    hh_xy = []
    hid = 0
    for bid, r in bld.iterrows():
        b = _first(r.get("building")) or "yes"
        amen, shop, office = r.get("amenity"), r.get("shop"), r.get("office")
        if any(not _is_nan(x) for x in (amen, shop, office)) and b not in MULTI_FAMILY | SINGLE_FAMILY | {"dormitory"}:
            continue
        if b in NON_RESIDENTIAL:
            continue
        area = float(r["area_m2"])
        levels = _parse_int_tag(r.get("building:levels"))
        no_car = False
        if b in SINGLE_FAMILY:
            n = 1
        elif b == "terrace":
            n = max(1, round(area / 90))
        elif b in MULTI_FAMILY:
            floors = levels or (4 if area > 800 else 3)
            n = max(1, round(floors * area / 90))
        elif b == "dormitory":
            floors = levels or 4
            n = max(1, round(floors * area / 60))
            no_car = True
        else:  # building=yes / unknown
            if area < 250:
                n = 1
            elif area < 1000:
                n = max(1, round(area / 120))
            else:
                n = max(1, round(area / 150))
        n = min(n, 400)
        multi = b in MULTI_FAMILY or b == "dormitory" or n > 2
        for _ in range(n):
            size = int(rng.choice([1, 2, 3, 4], p=[0.30, 0.35, 0.20, 0.15]))
            if no_car:
                veh = 0
                size = 1
            elif multi:
                veh = int(rng.choice([0, 1, 2], p=[0.40, 0.45, 0.15]))
            else:
                veh = int(rng.choice([0, 1, 2], p=[0.15, 0.55, 0.30]))
            flags = {
                "elderly": bool(rng.random() < 0.15) and not no_car,
                "mobility": bool(rng.random() < 0.05),
                "medical": bool(rng.random() < 0.03),
                "no_car": veh == 0,
            }
            households.append({"id": hid, "lon": round(float(r["clon"]), 6), "lat": round(float(r["clat"]), 6),
                               "building_id": str(bid[1]) if isinstance(bid, tuple) else str(bid),
                               "building": b, "node": None, "zone": None,
                               "size": size, "vehicles": veh, "flags": flags})
            hh_xy.append((float(r["clon"]), float(r["clat"])))
            hid += 1
    hh_xy = np.array(hh_xy) if hh_xy else np.zeros((0, 2))
    print(f"[build] households: {len(households)} ({time.time()-t0:.1f}s)")

    # nearest drive node per household (projected cKDTree)
    if len(households):
        Gp = ox.projection.project_graph(G)
        import geopandas as gpd
        from shapely.geometry import Point
        pts = gpd.GeoDataFrame(geometry=[Point(x, y) for x, y in hh_xy], crs="EPSG:4326").to_crs(Gp.graph["crs"])
        nn = ox.distance.nearest_nodes(Gp, pts.geometry.x.values, pts.geometry.y.values)
        for h, n in zip(households, nn):
            h["node"] = int(n)
        # zones
        hx, hy = to_xy(hh_xy[:, 0], hh_xy[:, 1])
        k = min(10, max(1, len(households) // 50))
        labels = kmeans(np.c_[hx, hy], k, rng)
        for h, z in zip(households, labels):
            h["zone"] = int(z)
        _, to_ll = local_projector(clon, clat)
        zones = []
        for z in range(k):
            m = labels == z
            cx, cy = hx[m].mean(), hy[m].mean()
            zlon, zlat = to_ll(cx, cy)
            zones.append({"id": z, "centroid": [round(float(zlon), 6), round(float(zlat), 6)], "n_households": int(m.sum())})
    else:
        zones = []

    # ---------- assets ----------
    assets = []
    try:
        af = ox.features_from_point((clat, clon), tags=ASSET_TAGS, dist=dist_m)
        afp = ox.projection.project_gdf(af)
        c = afp.geometry.centroid.to_crs(epsg=4326)
        Gp = ox.projection.project_graph(G)
        cp = afp.geometry.centroid
        nn = ox.distance.nearest_nodes(Gp, cp.x.values, cp.y.values)
        aid = 0
        for (idx, r), lon, lat, n in zip(af.iterrows(), c.x.values, c.y.values, nn):
            typ = None
            for tag, vals in ASSET_TAGS.items():
                v = _first(r.get(tag))
                if not _is_nan(v) and v in vals:
                    typ = v
                    break
            if typ is None:
                continue
            name = _first(r.get("name"))
            assets.append({"id": aid, "type": typ, "name": None if _is_nan(name) else str(name),
                           "lon": round(float(lon), 6), "lat": round(float(lat), 6), "node": int(n),
                           "osm": f"{idx[0]}/{idx[1]}"})
            aid += 1
    except Exception as ex:  # noqa: BLE001
        print(f"[build] assets skipped: {ex}")
    print(f"[build] assets: {len(assets)}  types={sorted({a['type'] for a in assets})}")

    # venue node
    Gp = ox.projection.project_graph(G)
    import geopandas as gpd
    from shapely.geometry import Point
    vp = gpd.GeoSeries([Point(vlon, vlat)], crs="EPSG:4326").to_crs(Gp.graph["crs"]).iloc[0]
    vnode = int(ox.distance.nearest_nodes(Gp, vp.x, vp.y))

    town = {
        "meta": {
            "version": "0.1", "center": [round(clon, 6), round(clat, 6)], "dist_m": dist_m,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": seed,
            "synthetic": ["households per footprint", "household size/vehicles/flags", "lanes where untagged",
                          "capacity_vph = lanes*1800", "storage_veh = lanes*len_km*150", "exits = boundary nodes"],
            "counts": {"nodes": len(nodes), "edges": len(edges), "paths": len(paths),
                       "households": len(households), "assets": len(assets), "exits": len(exits), "zones": len(zones)},
        },
        "venue": {"name": "David Rubenstein Treehouse", "source": venue_src, "lon": round(vlon, 6), "lat": round(vlat, 6), "node": vnode},
        "nodes": nodes, "edges": edges, "paths": paths, "households": households,
        "assets": assets, "exits": exits, "zones": zones,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(town, separators=(",", ":")))
    print(f"[build] wrote {out} ({out.stat().st_size/1e6:.1f} MB) in {time.time()-t0:.1f}s")
    return town
