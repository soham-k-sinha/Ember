"""validate-scenario: the example passes; broken references are caught; flood keyframes close roads."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from ember_engine.hazards import hazard_from_scenario
from ember_engine.scenario import deadlines, load_scenario, validate
from ember_engine.world import World

FX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


@pytest.fixture(scope="module")
def town() -> dict:
    return json.loads((FX / "town.fixture.json").read_text())


@pytest.fixture(scope="module")
def scn() -> dict:
    return json.loads((FX / "scenario.fixture.json").read_text())


def errors_after(town, scn, mutate) -> list[str]:
    s = copy.deepcopy(scn)
    mutate(s)
    return validate(s, town).errors


def test_example_is_valid(town, scn):
    r = validate(scn, town)
    assert r.ok, r.errors
    assert r.summary.startswith("OK ")
    assert sum(d is not None for d in r.deadlines["households"].values()) > 0


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: s["households"].append({"household_id": 10**9, "needs": {"people": 1}}), "not in town.json"),
    (lambda s: s["households"].append(dict(s["households"][0])), "duplicate household_id"),
    (lambda s: s["facilities"][1].update(depends_on=["nope"]), "is not a facility id"),
    (lambda s: [h.update(needs={"people": 2}) for h in s["households"] if h.get("judge")], "must start with needs 'unknown'"),
    (lambda s: [h.pop("judge", None) for h in s["households"]], "exactly one judge"),
    (lambda s: s["resources"].append({"id": "gen-x", "kind": "generator", "name": "x", "at_facility": "ems14"}), "needs kw and connector"),
    (lambda s: s["resources"][0].update(at_facility="nowhere"), "is not a facility id"),
    (lambda s: s["hazard"]["keyframes"].reverse(), "sorted by t_s"),
    (lambda s: s["facilities"].append({"id": "loop_a", "type": "substation", "name": "a", "asset_id": 6, "depends_on": ["loop_b"]})
     or s["facilities"].append({"id": "loop_b", "type": "substation", "name": "b", "asset_id": 6, "depends_on": ["loop_a"]}), "dependency cycle"),
    (lambda s: s["facilities"][0].update(asset_id=999), "not in town.json assets"),
    (lambda s: s.update(reserve={"vans": 9}), "reserve: vans=9"),
    (lambda s: s["resources"][0].pop("capacity_people"), "needs capacity_people"),
    (lambda s: s.pop("district"), "schema"),
])
def test_broken_references_are_errors(town, scn, mutate, needle):
    errs = errors_after(town, scn, mutate)
    assert any(needle in e for e in errs), errs


def test_keyframes_file_is_inlined(tmp_path, scn):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"t_s": k["t_s"], "label": k.get("label", "")}, "geometry": k["geometry"]}
        for k in scn["hazard"]["keyframes"]]}
    s = copy.deepcopy(scn)
    s["hazard"] = {"type": "flood_keyframes", "keyframes_file": "keyframes.geojson"}
    (tmp_path / "keyframes.geojson").write_text(json.dumps(fc))
    (tmp_path / "scenario.json").write_text(json.dumps(s))
    loaded = load_scenario(tmp_path / "scenario.json")
    assert [k["t_s"] for k in loaded["hazard"]["keyframes"]] == [k["t_s"] for k in scn["hazard"]["keyframes"]]


def test_keyframes_file_scenario_validates(tmp_path, scn, town):
    """Regression (reported by Anshuman): the loaded scenario kept keyframes_file next to keyframes → oneOf failed."""
    test_keyframes_file_is_inlined(tmp_path, scn)
    r = validate(load_scenario(tmp_path / "scenario.json"), town)
    assert r.ok, r.errors


def test_flood_closes_more_roads_over_time(town, scn):
    w = World.from_dict(town)
    hz = hazard_from_scenario(w, scn)
    counts = [int(hz.closed_mask_at(t, w).sum()) for t in (0.0, 3600.0, 5400.0, 10800.0)]
    assert counts[0] == 0 and counts[1] > 0 and counts == sorted(counts)


def test_deadline_is_flood_time_minus_margin(town, scn):
    w = World.from_dict(town)
    d = deadlines(scn, w)["households"]
    times = {k["t_s"] for k in scn["hazard"]["keyframes"]}
    m = scn["deadline_margin_s"]
    assert all(v is None or v + m in times for v in d.values())
