"""The draft WS event contract resolves against contracts/ and accepts/rejects the right events."""
import copy
import json

import jsonschema
import pytest
from referencing import Registry, Resource

from residents.config import CONTRACTS, PKG_ROOT


@pytest.fixture(scope="module")
def validator():
    reg = Registry()
    for p in CONTRACTS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        reg = reg.with_resource(s["$id"], Resource.from_contents(s))
    schema = json.loads((PKG_ROOT / "ws-events.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, registry=reg)


def ok(v, ev):
    errs = list(v.iter_errors(ev))
    assert not errs, [e.message[:200] for e in errs]


def bad(v, ev):
    assert list(v.iter_errors(ev)), f"should be rejected: {str(ev)[:200]}"


def test_each_event_type(validator, fixture_state):
    st = fixture_state
    a = st["plan"]["assignments"][0]
    ok(validator, {"type": "state", "seq": 0, "t_s": st["t_s"], "data": st})
    ok(validator, {"type": "plan", "seq": 1, "t_s": 1, "data": st["plan"]})
    ok(validator, {"type": "report", "seq": 2, "t_s": 1, "data": st["reports"][0]})
    ok(validator, {"type": "message", "seq": 3, "t_s": 1, "data": st["messages"][0]})
    ok(validator, {"type": "metrics", "seq": 4, "t_s": 1, "data": st["metrics"]})
    ok(validator, {"type": "assignment", "seq": 5, "t_s": 1,
                   "data": {"plan_version": 2, "change": "added", "assignment_id": a["id"], "assignment": a}})
    ok(validator, {"type": "assignment", "seq": 6, "t_s": 1,
                   "data": {"plan_version": 3, "change": "removed", "assignment_id": a["id"], "assignment": None}})
    ok(validator, {"type": "scatter_point", "seq": 7, "t_s": 1,
                   "data": {"run_id": "r1", "candidate": "baseline", "perturbation": {"travel_x": 1.2}, "metrics": st["metrics"]}})


def test_rejects_malformed(validator, fixture_state):
    st = fixture_state
    bad(validator, {"type": "nope", "seq": 0, "t_s": 0, "data": {}})
    bad(validator, {"type": "state", "seq": 0, "t_s": 0})                              # no data
    bad(validator, {"type": "state", "seq": 0, "t_s": 0, "data": {"version": "0.1"}})  # not a state
    msg = copy.deepcopy(st["messages"][0]); del msg["text"]
    bad(validator, {"type": "message", "seq": 1, "t_s": 0, "data": msg})
    bad(validator, {"type": "plan", "seq": 1, "t_s": 0, "data": None})                 # plan events carry a plan
    bad(validator, {"type": "report", "seq": 1, "t_s": 0, "data": {"id": "r", "source": "resident", "kind": "need", "observed_at_t_s": 0}})  # need w/o household
    bad(validator, {"type": "assignment", "seq": 1, "t_s": 0, "data": {"plan_version": 2, "change": "added", "assignment_id": "x"}})


def test_hub_envelope_matches_schema(validator, fixture_state):
    from residents.bus import Hub
    ok(validator, Hub.envelope("state", fixture_state, fixture_state["t_s"], 0))
    with pytest.raises(ValueError):
        Hub.envelope("nope", {}, 0, 0)
