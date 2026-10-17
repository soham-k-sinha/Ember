import copy
import gzip
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.config import CONTRACTS, REPO_ROOT, Settings

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
                    join_number="")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:  # `with` runs the lifespan (opens + seeds the DB)
        yield c
