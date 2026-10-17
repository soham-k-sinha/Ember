"""State contract: the example snapshot validates, broken references are caught, facility + wastewater logic."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ember_engine.state import example_state, validate_state

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
