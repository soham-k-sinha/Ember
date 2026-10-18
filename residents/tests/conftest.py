import copy
import gzip
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.config import CONTRACTS, REPO_ROOT, Settings
from residents.engine_bridge import EngineBridge
from tests.helpers import SCENARIO, make

FIXTURE = CONTRACTS / "fixtures" / "state.fixture.json"

# Never start real Daytona sandboxes from tests (engine uses them when DAYTONA_API_KEY is set; D48).
os.environ["EMBER_LOCAL_POOL"] = "1"
# Never call OSM Nominatim from tests (residents placed by location use a fake geocoder or intersections).
os.environ["GEOCODE"] = "0"


@pytest.fixture(scope="session")
def fixture_state() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def state(fixture_state) -> dict:
    return copy.deepcopy(fixture_state)


@pytest.fixture(scope="session")
def town() -> dict:
    """The team's shared town (D29), read straight from the committed gzip."""
    return json.loads(gzip.decompress((REPO_ROOT / "engine" / "data" / "town.json.gz").read_bytes()))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Static mode (no engine): the state fixture as-is. Engine tests use `engine_client`."""
    return Settings(db_path=tmp_path / "ember.db", seed_state=FIXTURE, reset_on_start=False,
                    dev_endpoints=True, photon_enabled=False, scenario=None,
                    extract_enabled=False, anthropic_api_key="", retry_every_s=3600.0, geocode_enabled=False,
                    elevenlabs_api_key="")  # never dial: tests that call inject a fake ElevenLabs


@pytest.fixture(scope="session")
def bridge():
    """Small search budget for speed. Demo-beat tests use `full_bridge` (the engine's default search)."""
    return EngineBridge(SCENARIO, moves=10)


@pytest.fixture(scope="session")
def full_bridge():
    return EngineBridge(SCENARIO)


@pytest.fixture(scope="session")
def solo_bridge():
    """Only the drill's people need rescue (no synthetic households): offers come fast and are predictable."""
    return EngineBridge(SCENARIO, moves=10, solo=True)


@pytest.fixture
def drill(settings, solo_bridge):
    """The text-driven drill (helpers.make): real allocator and simulator, a scripted model, the auto clock."""
    with make(settings, solo_bridge) as c:
        yield c


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:  # `with` runs the lifespan (opens + seeds the DB)
        yield c
