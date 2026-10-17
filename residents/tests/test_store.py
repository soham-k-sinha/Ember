"""The DB round trip: seed(fixture) → snapshot() must give the fixture back exactly."""
import pytest

from residents.db import Store, thread_key


def without_source(s: dict) -> dict:
    return {k: v for k, v in s.items() if k != "source"}


def test_roundtrip_is_exact(tmp_path, state):
    store = Store(tmp_path / "a.db")
    assert store.is_empty()
    store.seed(state)
    assert not store.is_empty()
    snap = store.snapshot()
    assert snap["source"] == "backend"
    assert without_source(snap) == without_source(state)
    # order is part of the contract the web relies on (ledger rows, message threads)
    assert [h["household_id"] for h in snap["households"]] == [h["household_id"] for h in state["households"]]
    assert [m["id"] for m in snap["messages"]] == [m["id"] for m in state["messages"]]


def test_plans_and_versions(tmp_path, state):
    store = Store(tmp_path / "a.db")
    store.seed(state)
    assert store.plan_versions() == [state["plan"]["version"]]
    assert store.current_plan() == state["plan"]
    assert store.plan(state["plan"]["version"]) == state["plan"]
    assert store.plan(999) is None


def test_reseed_replaces_instead_of_duplicating(tmp_path, state):
    store = Store(tmp_path / "a.db")
    store.seed(state)
    store.seed(state)
    snap = store.snapshot()
    assert len(snap["households"]) == len(state["households"])
    assert len(snap["messages"]) == len(state["messages"])
    assert len(snap["plan"]["assignments"]) == len(state["plan"]["assignments"])


def test_survives_reopen(tmp_path, state):
    path = tmp_path / "a.db"
    s1 = Store(path)
    s1.seed(state)
    s1.close()
    s2 = Store(path)
    assert not s2.is_empty()
    assert without_source(s2.snapshot()) == without_source(state)


def test_failed_seed_rolls_back(tmp_path, state):
    store = Store(tmp_path / "a.db")
    store.seed(state)
    bad = dict(state, households=state["households"] + [state["households"][0]])  # duplicate primary key
    with pytest.raises(Exception):
        store.seed(bad)
    assert without_source(store.snapshot()) == without_source(state)  # untouched


def test_plan_null_state(tmp_path, state):
    state["plan"] = None
    state["plan_version"] = None
    store = Store(tmp_path / "a.db")
    store.seed(state)
    assert store.current_plan() is None
    assert store.snapshot()["plan"] is None


def test_thread_key():
    assert thread_key({"household_id": 492}) == "household:492"
    assert thread_key({"facility_id": "mt_auburn"}) == "facility:mt_auburn"
    with pytest.raises(ValueError):
        thread_key({})
