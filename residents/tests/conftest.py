import copy
import gzip
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from residents.app import create_app
from residents.config import CONTRACTS, REPO_ROOT, Settings

FIXTURE = CONTRACTS / "fixtures" / "state.fixture.json"


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
                    extract_enabled=False, anthropic_api_key="")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:  # `with` runs the lifespan (opens + seeds the DB)
        yield c
