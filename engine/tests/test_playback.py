"""Playback (contracts/playback.schema.json): the map replay follows the roads and the simulator."""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

import pytest

from ember_engine.allocator.rolling import run_ember
from ember_engine.playback import _metres, playback
from ember_engine.scenario import load_scenario
from ember_engine.sim import simulate
from ember_engine.world import World

ROOT = Path(__file__).resolve().parents[2]
SCN = ROOT / "scenarios" / "allston_flood_v1" / "scenario.json"
pytestmark = pytest.mark.skipif(not SCN.exists(), reason="allston_flood_v1 not present")


@pytest.fixture(scope="module")
def run():
    world = World.from_dict(json.loads(gzip.decompress((ROOT / "engine" / "data" / "town.json.gz").read_bytes())))
    scn = load_scenario(SCN)
    res = simulate(world, scn, run_ember(world, scn, [])[0])
    return res, playback(res, "ember")


def _at(track: dict, t: float) -> list:
    """Linear interpolation along a track, as the web does."""
    ts, path = track["t"], track["path"]
    if t <= ts[0]:
        return path[0]
    for i in range(1, len(ts)):
        if ts[i] >= t:
            f = 0.0 if ts[i] == ts[i - 1] else (t - ts[i - 1]) / (ts[i] - ts[i - 1])
            return [path[i - 1][0] + f * (path[i][0] - path[i - 1][0]), path[i - 1][1] + f * (path[i][1] - path[i - 1][1])]
    return path[-1]


def test_tracks_hit_every_simulator_sample(run):
    res, pb = run
    for tr in pb["tracks"]:
        assert all(b >= a for a, b in zip(tr["t"], tr["t"][1:])), tr["id"]
        rt = res.timeline["res"][tr["id"]]
        for k, t in enumerate(res.timeline["t_s"]):
            assert _metres(_at(tr, t), (rt["lon"][k], rt["lat"][k])) < 3.0, (tr["id"], t)


def test_tracks_follow_roads_at_the_distance_driven(run):
    res, pb = run
    ts = res.timeline["t_s"]
    for tr in pb["tracks"]:
        rt = res.timeline["res"][tr["id"]]
        for k in range(1, len(ts)):
            drawn = sum(_metres(a, b) for a, b, t in zip(tr["path"], tr["path"][1:], tr["t"][1:]) if ts[k - 1] < t <= ts[k])
            driven = 1000 * (rt["km"][k] - rt["km"][k - 1])
            assert drawn <= 1.4 * driven + 80, (tr["id"], ts[k], drawn, driven)
    assert sum(len(tr["path"]) for tr in pb["tracks"]) > 3 * len(ts), "between-sample road geometry is missing"


def test_playback_carries_what_the_map_needs(run):
    res, pb = run
    hh = {h["household_id"]: h["status"] for h in pb["households"]}
    assert set(hh) == {h["household_id"] for h in res.scenario["households"]}
    assert all(math.isfinite(c[0]) for v in hh.values() for c in v)
    ids = {a["id"] for a in pb["plan"]["assignments"]}
    assert all(a.get("rationale") for a in pb["plan"]["assignments"])
    assert {o["assignment_id"] for o in pb["outcomes"]} <= ids
    assert any(e["kind"] == "pickup" for e in pb["events"])
    assert len(pb["wastewater"]["cottage-farm"]["overflow_m3"]) == len(pb["t_s"])
