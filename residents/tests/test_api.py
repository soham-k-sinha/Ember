"""HTTP + WS API against the state fixture, validated by the engine's own contract checker."""
from fastapi.testclient import TestClient

from ember_engine.scenario import load_scenario
from ember_engine.state import validate_state
from residents.app import create_app
from residents.config import CONTRACTS


def test_get_state_passes_engine_validate_state(client, town):
    r = client.get("/state")
    assert r.status_code == 200
    st = r.json()
    scn = load_scenario(CONTRACTS / "fixtures" / "scenario.fixture.json")
    assert validate_state(st, scn, town) == []
    assert st["source"] == "backend"


def test_get_state_matches_fixture(client, fixture_state):
    st = client.get("/state").json()
    assert {k: v for k, v in st.items() if k != "source"} == {k: v for k, v in fixture_state.items() if k != "source"}


def test_plan_endpoints(client, fixture_state):
    v = fixture_state["plan"]["version"]
    assert client.get("/plan/current").json() == fixture_state["plan"]
    assert client.get(f"/plan/{v}").json() == fixture_state["plan"]
    r = client.get(f"/plan/{v + 1}")  # a version that was never stored
    assert r.status_code == 404 and str(v) in r.json()["detail"]
    assert client.get("/plan/abc").status_code == 422


def test_health(client, fixture_state):
    h = client.get("/health").json()
    assert h == {"ok": True, "scenario_id": fixture_state["scenario_id"], "plan_version": fixture_state["plan_version"],
                 "t_s": fixture_state["t_s"], "photon": "disabled"}


def test_cors_allows_vite_dev_server(client):
    r = client.get("/state", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = client.get("/state", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_ws_sends_state_on_connect(client, fixture_state):
    with client.websocket_connect("/ws") as ws:
        ev = ws.receive_json()
    assert ev["type"] == "state" and ev["seq"] == 0 and ev["t_s"] == fixture_state["t_s"]
    assert ev["data"] == client.get("/state").json()


def test_dev_reset_restores_seed_and_broadcasts(client, settings, fixture_state):
    # dirty the DB, then reset
    client.app.state.store._db.execute("UPDATE households SET status = 'safe'")
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        assert a.receive_json()["seq"] == 0 and b.receive_json()["seq"] == 0
        assert client.post("/dev/reset").json() == {"ok": True, "plan_version": fixture_state["plan_version"]}
        for ws in (a, b):
            ev = ws.receive_json()
            assert ev["type"] == "state" and ev["seq"] == 1
            assert ev["data"]["households"] == fixture_state["households"]
    # a client that connects later starts at the current seq
    with client.websocket_connect("/ws") as c:
        assert c.receive_json()["seq"] == 1


def test_disconnected_ws_client_is_forgotten(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert len(client.app.state.hub.clients) == 1
    client.post("/dev/reset")  # broadcast after the disconnect must not fail
    assert len(client.app.state.hub.clients) == 0


def test_existing_db_is_kept_across_restart(settings):
    with TestClient(create_app(settings)) as c:
        c.app.state.store._db.execute("UPDATE meta SET value = '7' WHERE key = 'plan_version'")
    with TestClient(create_app(settings)) as c:  # restart without RESET_ON_START
        assert c.get("/health").json()["plan_version"] == 7


def test_reset_on_start_reseeds(settings, fixture_state):
    with TestClient(create_app(settings)) as c:
        c.app.state.store._db.execute("UPDATE meta SET value = '7' WHERE key = 'plan_version'")
    from dataclasses import replace
    with TestClient(create_app(replace(settings, reset_on_start=True))) as c:
        assert c.get("/health").json()["plan_version"] == fixture_state["plan_version"]


def test_dev_endpoints_can_be_disabled(settings):
    from dataclasses import replace
    with TestClient(create_app(replace(settings, dev_endpoints=False))) as c:
        assert c.post("/dev/reset").status_code == 404


def test_seed_version_follows_the_contract(tmp_path, state):
    import json
    import pytest
    from residents.app import load_seed, state_contract_version
    assert state["version"] == state_contract_version()  # the fixture and the schema agree
    stale = tmp_path / "old.json"
    stale.write_text(json.dumps(dict(state, version="0.0")))
    with pytest.raises(RuntimeError, match="state version"):
        load_seed(stale)
