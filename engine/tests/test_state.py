"""State contract: the example snapshot validates, broken references are caught, facility + wastewater logic."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ember_engine.state import example_state, facility_timeline, validate_state, wastewater_at

FX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


@pytest.fixture(scope="module")
def town() -> dict:
    return json.loads((FX / "town.fixture.json").read_text())


@pytest.fixture(scope="module")
def scn() -> dict:
    return json.loads((FX / "scenario.fixture.json").read_text())


@pytest.fixture(scope="module")
def state() -> dict:
    return json.loads((FX / "state.fixture.json").read_text())


def test_fixture_is_valid(state, scn, town):
    assert validate_state(state, scn, town) == []


def test_example_state_is_deterministic_and_valid_on_the_town_fixture(scn, town):
    a, b = example_state(town, scn), example_state(town, scn)
    assert a == b
    assert validate_state(a, scn, town) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: s["closures"].append({"edge_id": 10**6, "closed_from_t_s": 0, "source": "hazard"}), "not in town.json"),
    (lambda s: s["resources"][0].update(assignment_id="nope"), "unknown assignment"),
    (lambda s: s["plan"]["assignments"][0].update(resource_id="ghost"), "resource ghost unknown"),
    (lambda s: s["households"].pop(), "mismatch"),
    (lambda s: s["households"][0].update(status="lost"), "schema"),
])
def test_broken_state_is_caught(state, scn, town, mutate, needle):
    s = copy.deepcopy(state)
    mutate(s)
    errs = validate_state(s, scn, town)
    assert any(needle in e for e in errs), errs


def test_substation_event_puts_hospital_on_backup(scn):
    tl = facility_timeline(scn, 6000)
    at = {k: {t: (st, left) for t, st, left, _ in v} for k, v in tl.items()}
    assert at["sub_putnam_ave"][4440][0] == "ok" and at["sub_putnam_ave"][4500][0] == "down"
    st, left = at["mt_auburn"][4800]
    assert st == "backup" and left == pytest.approx(32400 - 360)


def _overflow_start(scn, gen_at):
    tl = facility_timeline(scn, scn["t_end_s"], gen_at)
    f = next(f for f in scn["facilities"] if f["id"] == "cottage_farm")
    ser = wastewater_at(f, tl["cottage_farm"], scn["t_end_s"])["series"]
    return next((t for t, o in zip(ser["t_s"], ser["overflow_m3"]) if o > 0), None), ser["overflow_m3"][-1]


def test_unpowered_pumping_station_overflows_at_the_predicted_minute(scn):
    # down at 5400 (Putnam Substation, no backup); storage 0 → 4000 m³ at 3000 m³/h until 7200, then 4500 m³/h:
    # 1500 m³ by 7200, the remaining 2500 m³ take 2000 s → first overflow just after 9200 s
    start, total = _overflow_start(scn, {})
    assert 9200 <= start <= 9600 and total > 0


def test_compatible_generator_prevents_overflow(scn):
    start, total = _overflow_start(scn, {"cottage_farm": 1200.0})
    assert start is None and total == 0
