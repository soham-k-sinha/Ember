"""contracts/fixtures/*.json must validate against contracts/*.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
from referencing import Registry, Resource  # noqa: E402

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
PAIRS = ["town", "plan", "job", "metrics", "trajectories", "scenario", "state", "comparison", "playback"]


def _registry() -> Registry:
    res = []
    for p in CONTRACTS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        r = Resource.from_contents(s)
        res += [(s["$id"], r), (p.name, r)]
    return Registry().with_resources(res)


@pytest.mark.parametrize("name", PAIRS)
def test_fixture_matches_schema(name):
    fx = CONTRACTS / "fixtures" / f"{name}.fixture.json"
    if not fx.exists():
        pytest.skip(f"{fx.name} not generated yet (run `uv run ember fixtures`)")
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text())
    v = jsonschema.Draft202012Validator(schema, registry=_registry())
    errors = sorted(v.iter_errors(json.loads(fx.read_text())), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)[:6]}: {e.message[:200]}" for e in errors[:10])


def test_ws_event_examples_validate():
    """Every example envelope validates; every event type is covered."""
    fx = CONTRACTS / "fixtures" / "ws-events.fixture.json"
    if not fx.exists():
        pytest.skip("ws-events.fixture.json not generated yet (run `uv run ember fixtures`)")
    schema = json.loads((CONTRACTS / "ws-events.schema.json").read_text())
    v = jsonschema.Draft202012Validator(schema, registry=_registry())
    events = json.loads(fx.read_text())
    for e in events:
        errs = list(v.iter_errors(e))
        assert not errs, f"{e['type']}: {errs[0].message[:300]}"
    assert {e["type"] for e in events} == set(schema["properties"]["type"]["enum"])
    assert [e["seq"] for e in events] == list(range(len(events)))
