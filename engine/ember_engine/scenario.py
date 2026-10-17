"""Scenario: load, validate against contracts/scenario.schema.json + town.json, derive deadlines.

    uv run --project engine ember validate-scenario scenarios/allston_flood_v1/scenario.json

Pure functions; the only I/O is load_scenario (reads the file and an optional keyframes_file).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VEHICLE_KINDS = {"van", "accessible_van", "truck"}


# ---------- loading ----------
def load_scenario(path: str | Path) -> dict:
    """Read scenario.json; inline `hazard.keyframes_file` (GeoJSON FeatureCollection, properties.t_s)."""
    path = Path(path)
    scn = json.loads(path.read_text())
    hz = scn.get("hazard", {})
    if "keyframes_file" in hz:
        fc = json.loads((path.parent / hz["keyframes_file"]).read_text())
        hz["keyframes"] = [{"t_s": float(f["properties"]["t_s"]), "label": f["properties"].get("label", ""),
                            "geometry": f["geometry"]} for f in fc["features"]]
    return scn


def schema_errors(scn: dict) -> list[str]:
    import jsonschema
    from referencing import Registry, Resource

    schema = json.loads((CONTRACTS / "scenario.schema.json").read_text())
    reg = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    v = jsonschema.Draft202012Validator(schema, registry=reg)
    out = []
    for e in sorted(v.iter_errors(scn), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"schema: {where}: {e.message[:300]}")
    return out


# ---------- geometry ----------
def area_to_local(geometry: dict, world):
    """GeoJSON Polygon/MultiPolygon in lon/lat → shapely geometry in the world's local meters."""
    import shapely
    from shapely.geometry import shape

    from .geo import local_projector

    to_xy, _ = local_projector(*world.center)
    g = shape(geometry)
    g = shapely.transform(g, lambda c: np.c_[to_xy(c[:, 0], c[:, 1])])
    return g if g.is_valid else shapely.make_valid(g)


def flood_keyframes(scn: dict, world) -> list[tuple[float, object]]:
    return sorted(((float(k["t_s"]), area_to_local(k["geometry"], world)) for k in scn["hazard"].get("keyframes", [])),
                  key=lambda k: k[0])


def first_flooded_at(frames, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Per point: the first keyframe time whose extent contains it (nan if never)."""
    import shapely

    out = np.full(len(x), np.nan)
    for t, g in frames:
        hit = np.isnan(out) & shapely.contains_xy(g, x, y)
        out[hit] = t
    return out


def deadlines(scn: dict, world, frames=None) -> dict:
    """{'households': {hh_id: deadline_s|None}, 'facilities': {fac_id: threatened_at_s|None}} (TECHNICAL §3.2)."""
    frames = frames if frames is not None else flood_keyframes(scn, world)
    margin = float(scn.get("deadline_margin_s", 900))
    nidx = {int(n): i for i, n in enumerate(world.node_id)}
    hh_row = {int(h): i for i, h in enumerate(world.hh_id)}

    hh_ids = [h["household_id"] for h in scn["households"] if h["household_id"] in hh_row]
    nodes = np.array([world.hh_node[hh_row[h]] for h in hh_ids], dtype=np.int64)
    t = first_flooded_at(frames, world.node_x[nodes], world.node_y[nodes]) if len(nodes) else np.zeros(0)
    hh = {h: (None if np.isnan(v) else max(0.0, float(v) - margin)) for h, v in zip(hh_ids, t)}

    fac = {}
    assets = {a["id"]: a for a in world.assets}
    for f in scn["facilities"]:
        node = f.get("node", assets.get(f.get("asset_id"), {}).get("node"))
        if node in nidx:
            v = first_flooded_at(frames, world.node_x[[nidx[node]]], world.node_y[[nidx[node]]])[0]
            fac[f["id"]] = None if np.isnan(v) else float(v)
    return {"households": hh, "facilities": fac}


# ---------- validation ----------
@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str = ""
    deadlines: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(scn: dict, town: dict) -> Report:
    """Schema + referential integrity against town.json. Errors block; warnings are judgment calls."""
    from .world import World

    r = Report(errors=schema_errors(scn))
    if r.errors:   # referential checks assume the shape is right
        r.summary = f"FAIL {scn.get('scenario_id', '?')}: {len(r.errors)} schema error(s)"
        return r
    E, W = r.errors.append, r.warnings.append
    world = World.from_dict(town)
    node_ids = {n["id"] for n in town["nodes"]}
    hh_by_id = {h["id"]: h for h in town["households"]}
    assets = {a["id"]: a for a in town["assets"]}
    import shapely

    from .geo import local_projector
    to_xy, _ = local_projector(*world.center)
    box = float(town["meta"]["dist_m"])

    def inside_box(g) -> bool:
        x0, y0, x1, y1 = g.bounds
        return max(abs(x0), abs(y0), abs(x1), abs(y1)) <= box * 1.001

    # district
    district = area_to_local(scn["district"]["geometry"], world)
    if not inside_box(district):
        E(f"district: extends outside the town box (±{box:.0f} m around {town['meta']['center']})")
    vx, vy = to_xy(town["venue"]["lon"], town["venue"]["lat"])
    if not shapely.contains_xy(district, float(vx), float(vy)):
        W("district: does not contain the venue")

    # hazard
    kfs = scn["hazard"].get("keyframes", [])
    if not kfs:
        E("hazard: no keyframes (inline list empty or keyframes_file has no features)")
    ts = [float(k["t_s"]) for k in kfs]
    if ts != sorted(ts):
        E("hazard: keyframes must be sorted by t_s")
    if len(set(ts)) != len(ts):
        E("hazard: duplicate keyframe t_s")
    if ts and max(ts) > scn["t_end_s"]:
        W(f"hazard: keyframe at t={max(ts):.0f}s is after t_end_s={scn['t_end_s']:.0f}s")
    frames = flood_keyframes(scn, world)
    for (t, g), k in zip(frames, sorted(kfs, key=lambda k: k["t_s"])):
        if g.is_empty:
            W(f"hazard: keyframe t={t:.0f}s is empty")
        elif not inside_box(g):
            W(f"hazard: keyframe t={t:.0f}s extends outside the town box (clipped by the map)")
    for (t0, g0), (t1, g1) in zip(frames, frames[1:]):
        if not g0.is_empty and g0.difference(g1).area > 0.05 * g0.area:
            W(f"hazard: keyframe t={t1:.0f}s is smaller than t={t0:.0f}s (water receding?)")

    # facilities
    fac_ids = [f["id"] for f in scn["facilities"]]
    dup = {i for i in fac_ids if fac_ids.count(i) > 1}
    if dup:
        E(f"facilities: duplicate ids {sorted(dup)}")
    fac = {f["id"]: f for f in scn["facilities"]}
    for f in scn["facilities"]:
        fid = f["id"]
        if "asset_id" in f:
            a = assets.get(f["asset_id"])
            if a is None:
                E(f"facility {fid}: asset_id {f['asset_id']} not in town.json assets (0..{len(assets)-1})")
            elif f["type"] in ("hospital", "clinic", "pumping_station", "substation") and a["type"] not in (f["type"], "clinic" if f["type"] == "hospital" else f["type"]):
                W(f"facility {fid}: type {f['type']} but town asset {f['asset_id']} is a {a['type']}")
        if "node" in f:
            if f["node"] not in node_ids:
                E(f"facility {fid}: node {f['node']} not in town.json nodes")
            if not f.get("synthetic"):
                W(f"facility {fid}: placed by node, not a town asset; set synthetic: true and justify it in assumptions.md")
        for d in f.get("depends_on", []):
            if d not in fac:
                E(f"facility {fid}: depends_on '{d}' is not a facility id")
            elif d == fid:
                E(f"facility {fid}: depends on itself")
        ww = f.get("wastewater")
        if ww and f["type"] != "pumping_station":
            E(f"facility {fid}: wastewater params only apply to pumping_station")
        if f["type"] == "pumping_station" and not ww:
            E(f"facility {fid}: pumping_station needs wastewater params (storage_m3, storage_max_m3, inflow_m3ph, pump_m3ph)")
        if ww:
            if ww["storage_m3"] > ww["storage_max_m3"]:
                E(f"facility {fid}: storage_m3 > storage_max_m3")
            infl = ww["inflow_m3ph"]
            if isinstance(infl, list) and [p[0] for p in infl] != sorted(p[0] for p in infl):
                E(f"facility {fid}: inflow_m3ph steps must be sorted by t_s")
        if f["type"] in ("pumping_station", "hospital") and ("power_kw_required" not in f or "connector" not in f):
            W(f"facility {fid}: no power_kw_required/connector, so no generator can ever restore it")
        if f["type"] in ("response_base", "shelter") and not f.get("capacity_people"):
            W(f"facility {fid}: {f['type']} without capacity_people")
        ev = [e["t_s"] for e in f.get("events", [])]
        if ev != sorted(ev):
            E(f"facility {fid}: events must be sorted by t_s")
    # dependency cycles
    state = {}

    def visit(u, stack):
        state[u] = 1
        for v in fac.get(u, {}).get("depends_on", []):
            if v in fac and state.get(v) == 1:
                E(f"facilities: dependency cycle {' → '.join(stack + [u, v])}")
            elif v in fac and v not in state:
                visit(v, stack + [u])
        state[u] = 2
    for u in fac:
        if u not in state:
            visit(u, [])
    if not any(f["type"] in ("response_base", "shelter") for f in scn["facilities"]):
        E("facilities: need at least one response_base or shelter (where people are taken)")

    # resources
    res_ids = [x["id"] for x in scn["resources"]]
    dup = {i for i in res_ids if res_ids.count(i) > 1}
    if dup:
        E(f"resources: duplicate ids {sorted(dup)}")
    if set(res_ids) & set(fac):
        E(f"resources and facilities share ids {sorted(set(res_ids) & set(fac))}")
    for x in scn["resources"]:
        rid, k = x["id"], x["kind"]
        if "node" in x and x["node"] not in node_ids:
            E(f"resource {rid}: node {x['node']} not in town.json nodes")
        if "at_facility" in x and x["at_facility"] not in fac:
            E(f"resource {rid}: at_facility '{x['at_facility']}' is not a facility id")
        if k in VEHICLE_KINDS and not x.get("capacity_people"):
            E(f"resource {rid}: {k} needs capacity_people > 0")
        if k == "accessible_van" and not x.get("accessible"):
            E(f"resource {rid}: accessible_van must have accessible: true")
        if k == "generator":
            if not x.get("kw") or not x.get("connector"):
                E(f"resource {rid}: generator needs kw and connector")
            if x.get("capacity_people"):
                W(f"resource {rid}: generator with capacity_people (ignored)")
        elif x.get("kw") or x.get("connector"):
            W(f"resource {rid}: kw/connector only matter for generators")
    gens = [x for x in scn["resources"] if x["kind"] == "generator"]
    vans = [x for x in scn["resources"] if x["kind"] in VEHICLE_KINDS]
    for f in scn["facilities"]:
        if "connector" in f and "power_kw_required" in f and gens:
            if not any(g.get("connector") == f["connector"] and g.get("kw", 0) >= f["power_kw_required"] for g in gens):
                W(f"facility {f['id']}: no generator matches connector '{f['connector']}' with kw ≥ {f['power_kw_required']}")
    rsv = scn["reserve"]
    if rsv.get("vans", 0) > len(vans):
        E(f"reserve: vans={rsv['vans']} but only {len(vans)} vehicles")
    if rsv.get("generators", 0) > len(gens):
        E(f"reserve: generators={rsv['generators']} but only {len(gens)} generators")

    # households
    hh_ids = [h["household_id"] for h in scn["households"]]
    dup = {i for i in hh_ids if hh_ids.count(i) > 1}
    if dup:
        E(f"households: duplicate household_id {sorted(dup)}")
    missing = [i for i in hh_ids if i not in hh_by_id]
    if missing:
        E(f"households: {len(missing)} household_id(s) not in town.json: {missing[:10]}"
          + (" (validating against the town fixture? it holds only every 12th household)" if town["meta"].get("fixture") else ""))
    judges = [h for h in scn["households"] if h.get("judge")]
    if len(judges) != 1:
        E(f"households: exactly one judge: true required (found {len(judges)})")
    for j in judges:
        if j["needs"] != "unknown":
            E(f"households: the judge's household {j['household_id']} must start with needs 'unknown'")
    hx = np.array([hh_by_id[i]["lon"] for i in hh_ids if i in hh_by_id])
    hy = np.array([hh_by_id[i]["lat"] for i in hh_ids if i in hh_by_id])
    if len(hx):
        x, y = to_xy(hx, hy)
        outside = int((~shapely.contains_xy(district, x, y)).sum())
        if outside:
            W(f"households: {outside} assisted household(s) outside the district polygon")
    needs = [h["needs"] for h in scn["households"] if h["needs"] != "unknown"]
    n_mob = sum(1 for n in needs if n.get("mobility") or n.get("accessible_vehicle"))
    if n_mob and not any(x.get("accessible") for x in vans):
        W(f"households: {n_mob} need an accessible vehicle but no resource is accessible")
    biggest = max([n["people"] for n in needs], default=0)
    if vans and biggest > max(x.get("capacity_people", 0) for x in vans):
        W(f"households: a household of {biggest} exceeds every vehicle's capacity (needs a split pickup)")

    # scripted reports
    for i, rep in enumerate(scn.get("scripted_reports", [])):
        where = f"scripted_reports[{i}]"
        if "household_id" in rep and rep["household_id"] not in hh_ids:
            E(f"{where}: household_id {rep['household_id']} is not an assisted household")
        if "facility_id" in rep and rep["facility_id"] not in fac:
            E(f"{where}: facility_id '{rep['facility_id']}' is not a facility id")
        if rep["kind"] == "closure_report":
            bad = [e for e in rep.get("edge_ids", []) if not 0 <= e < len(town["edges"])]
            if not rep.get("edge_ids"):
                E(f"{where}: closure_report needs edge_ids")
            elif bad:
                E(f"{where}: edge ids not in town.json: {bad}")
        if rep["kind"] == "need" and "household_id" not in rep:
            E(f"{where}: need report needs household_id")
        if rep["kind"] == "facility_status" and "facility_id" not in rep:
            E(f"{where}: facility_status needs facility_id")
        if rep["t_s"] > scn["t_end_s"]:
            W(f"{where}: t_s after t_end_s")
        if any(rep.get("household_id") == j["household_id"] for j in judges):
            W(f"{where}: scripts the judge's household; the judge should supply that live")

    # derived numbers for the summary
    if not r.errors:
        r.deadlines = deadlines(scn, world, frames)
        n_dead = sum(v is not None for v in r.deadlines["households"].values())
        crest_t, crest = frames[-1]
        flooded = int(shapely.intersects(crest, world.edge_lines()).sum()) if not crest.is_empty else 0
        people = sum(n["people"] for n in needs)
        n_unknown = len(hh_ids) - len(needs)
        judge = judges[0]["household_id"] if judges else None
        kinds = {}
        for x in scn["resources"]:
            kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
        threatened = [k for k, v in r.deadlines["facilities"].items() if v is not None]
        r.summary = (
            f"OK {scn['scenario_id']}: {len(hh_ids)} assisted households ({people} people known, {n_mob} mobility, "
            f"{n_unknown} unknown, judge=#{judge}); {n_dead}/{len(hh_ids)} get a flood deadline; "
            f"{len(fac)} facilities ({len(threatened)} flooded by crest); resources "
            + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
            + f"; {len(frames)} keyframes {frames[0][0]/60:.0f}–{crest_t/60:.0f} min, {flooded}/{world.n_edges} edges under water at crest"
        )
    else:
        r.summary = f"FAIL {scn['scenario_id']}: {len(r.errors)} error(s)"
    return r


# ---------- example (contracts/fixtures/scenario.fixture.json) ----------
def example_scenario(town: dict) -> dict:
    """A complete, valid scenario built from real town ids. Placeholder numbers (labeled synthetic);
    scenarios/allston_flood_v1/scenario.json (Anshuman) is the real one. Households are drawn from
    every 12th town household so the example also validates against town.fixture.json."""
    import shapely
    from shapely.geometry import mapping

    from .geo import local_projector
    from .world import World

    world = World.from_dict(town)
    _, to_ll = local_projector(*world.center)

    def to_geojson(g) -> dict:
        g = shapely.transform(g.simplify(4.0), lambda c: np.c_[to_ll(c[:, 0], c[:, 1])])
        return json.loads(json.dumps(mapping(shapely.set_precision(g, 1e-6))))   # tuples → lists

    # flood: growing buffers around the riverfront roads (synthetic stand-in for traced FEMA/Climate Ready layers)
    river = [e for e in range(world.n_edges)
             if (world.edge_name[e] or "") in ("Soldiers Field Road", "Memorial Drive")]
    lines = shapely.union_all(world.edge_lines()[river])
    stages = [(3600, 25, "river-edge paths"), (5400, 60, "Soldiers Field Rd / Memorial Dr"),
              (9000, 120, "low streets, bridge approaches"), (10800, 180, "crest")]
    box = shapely.box(*(np.array([-1, -1, 1, 1]) * float(town["meta"]["dist_m"])))
    keyframes = [{"t_s": float(t), "label": lab, "geometry": to_geojson(lines.buffer(b, quad_segs=4).intersection(box))}
                 for t, b, lab in stages]

    half = 0.75 * float(town["meta"]["dist_m"])
    district = shapely.box(-half, -half, half, half)
    assets = {a["name"]: a for a in town["assets"] if a["name"]}
    a_id = lambda name: assets[name]["id"]  # noqa: E731

    # households: every 12th town household inside the district, mostly ones the crest reaches
    frames = [(float(k["t_s"]), area_to_local(k["geometry"], world)) for k in keyframes]
    sample = town["households"][::12]
    rows = {int(h): i for i, h in enumerate(world.hh_id)}
    hx = np.array([world.node_x[world.hh_node[rows[h["id"]]]] for h in sample])
    hy = np.array([world.node_y[world.hh_node[rows[h["id"]]]] for h in sample])
    inside = shapely.contains_xy(district, hx, hy)
    t_flood = first_flooded_at(frames, hx, hy)
    wet = [h for h, i, t in zip(sample, inside, t_flood) if i and not np.isnan(t)]
    dry = [h for h, i, t in zip(sample, inside, t_flood) if i and np.isnan(t)]
    picked = wet[:: max(1, len(wet) // 32)][:32] + dry[:: max(1, len(dry) // 8)][:8]
    t_of = {h["id"]: t for h, t in zip(sample, t_flood)}
    # judge: a household whose street floods late (deadline ≈ 135 min), so the demo beat lands before it
    mid = [h for h in picked if (t_of.get(h["id"]) or 0) == 9000]
    judge = (mid or picked)[0]["id"]
    others = [h["id"] for h in picked if h["id"] != judge]
    unknown = {judge, *others[3:6]}   # 4 unknown incl. the judge
    households = []
    n_mob = 0
    for i, h in enumerate(picked):
        entry = {"household_id": h["id"], "label": f"household #{h['id']} ({h['building']})"}
        if h["id"] in unknown:
            entry["needs"] = "unknown"
        else:
            mob = i % 6 == 1 and n_mob < 6   # 6 of 40 with mobility needs (synthetic)
            n_mob += mob
            entry["needs"] = {"people": int(h["size"]), "mobility": mob, "accessible_vehicle": mob}
        if h["id"] == judge:
            entry |= {"judge": True, "phone_role": "resident", "label": "the judge's household"}
        households.append(entry)
    unknown_others = [h for h in unknown if h != judge]

    return {
        "version": "0.1",
        "scenario_id": "example_flood",
        "name": "Example flood around the Treehouse (contract fixture)",
        "description": "Engine-generated example for the scenario contract. All numbers are placeholders; the real scenario is scenarios/allston_flood_v1.",
        "synthetic": ["flood extents = buffers around riverfront roads", "facility parameters", "resource fleet",
                      "household needs", "event and report timing", "outfall placement"],
        "t_end_s": 10800, "tick_s": 60, "deadline_margin_s": 900,
        "district": {"name": "Treehouse district (example)", "geometry": to_geojson(district)},
        "hazard": {"type": "flood_keyframes", "source": "synthetic: riverfront road buffers 25→180 m over 3 h", "keyframes": keyframes},
        "facilities": [
            {"id": "ems14", "type": "response_base", "name": "Boston EMS Station 14", "asset_id": a_id("Boston EMS Station 14"),
             "capacity_people": 200, "consequence": "Staging base and drop-off point."},
            {"id": "mt_auburn", "type": "hospital", "name": "Mount Auburn Hospital", "asset_id": a_id("Mount Auburn Hospital"),
             "critical": True, "power_kw_required": 350, "connector": "camlock-400a", "backup_endurance_s": 32400,
             "depends_on": ["sub_putnam_ave"], "consequence": "Loses power to wards when backup runs out."},
            {"id": "sub_putnam_ave", "type": "substation", "name": "Putnam Avenue Substation", "asset_id": a_id("Putnam Avenue Substation"),
             "events": [{"t_s": 4500, "state": "down", "note": "flooded switchgear (synthetic timing)"}],
             "consequence": "Feeds the hospital."},
            {"id": "sub_putnam", "type": "substation", "name": "Putnam Substation", "asset_id": a_id("Putnam Substation"),
             "events": [{"t_s": 5400, "state": "down", "note": "flooded switchgear (synthetic timing)"}],
             "consequence": "Feeds the Cottage Farm pumps."},
            {"id": "cottage_farm", "type": "pumping_station", "name": "Cottage Farm CSO Facility",
             "asset_id": a_id("Cottage Farm Combined Sewer Overflow Facility"), "critical": False,
             "power_kw_required": 350, "connector": "camlock-400a", "connect_s": 900, "backup_endurance_s": 0,
             "depends_on": ["sub_putnam", "outfall_charles"],
             "wastewater": {"storage_m3": 500, "storage_max_m3": 4000, "pump_m3ph": 6000,
                            "inflow_m3ph": [[0, 1500], [3600, 3000], [7200, 4500]], "downstream_ok": True},
             "consequence": "Without power, storage fills and untreated wastewater overflows to the Charles."},
            {"id": "outfall_charles", "type": "outfall", "name": "Charles River outfall near Cottage Farm",
             "node": town["assets"][a_id("Cottage Farm Combined Sewer Overflow Facility")]["node"], "synthetic": True,
             "consequence": "Discharge point; overflow volume is counted here."},
        ],
        "resources": [
            {"id": "van-1", "kind": "van", "name": "Van 1", "at_facility": "ems14", "capacity_people": 6, "fuel_l": 60, "fuel_l_per_km": 0.15, "service_s": 300},
            {"id": "van-2", "kind": "van", "name": "Van 2", "at_facility": "ems14", "capacity_people": 6, "fuel_l": 60, "fuel_l_per_km": 0.15, "service_s": 300},
            {"id": "avan-1", "kind": "accessible_van", "name": "Accessible van", "at_facility": "ems14", "capacity_people": 4, "accessible": True,
             "fuel_l": 60, "fuel_l_per_km": 0.18, "service_s": 600},
            {"id": "truck-1", "kind": "truck", "name": "High-clearance truck", "at_facility": "ems14", "capacity_people": 10, "fuel_l": 120,
             "fuel_l_per_km": 0.3, "service_s": 300},
            {"id": "crew-1", "kind": "crew", "name": "Road crew", "at_facility": "ems14", "fuel_l": 40, "fuel_l_per_km": 0.15, "service_s": 1200},
            {"id": "gen-1", "kind": "generator", "name": "Generator 400 kW (camlock)", "at_facility": "ems14", "kw": 400, "connector": "camlock-400a",
             "fuel_l": 300, "fuel_l_per_km": 0.4, "speed_factor": 0.7, "service_s": 0},
            {"id": "gen-2", "kind": "generator", "name": "Generator 60 kW (L14-30)", "at_facility": "ems14", "kw": 60, "connector": "l14-30",
             "fuel_l": 80, "fuel_l_per_km": 0.2, "service_s": 0},
        ],
        "households": households,
        "reserve": {"vans": 1, "generators": 1},
        "scripted_reports": [
            {"t_s": 1800, "kind": "need", "household_id": unknown_others[0], "needs": {"people": 3, "mobility": False},
             "note": "neighbour reports a family of three"},
            {"t_s": 2700, "kind": "need", "household_id": unknown_others[1], "needs": {"people": 1, "mobility": True, "accessible_vehicle": True},
             "note": "wheelchair user, alone"},
            {"t_s": 6000, "kind": "facility_status", "facility_id": "mt_auburn", "set": {"backup_endurance_s": 7200},
             "note": "operator: backup fuel lower than planned"},
        ],
    }
