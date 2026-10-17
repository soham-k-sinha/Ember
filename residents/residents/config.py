"""Settings from the environment (and residents/.env, which is gitignored)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PKG_ROOT = Path(__file__).resolve().parents[1]  # residents/
REPO_ROOT = PKG_ROOT.parent
CONTRACTS = REPO_ROOT / "contracts"

load_dotenv(PKG_ROOT / ".env")


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("DB_PATH", PKG_ROOT / "ember.db")))
    # The snapshot the DB is seeded from. Swap for the engine's allston_flood_v1 snapshot when it lands.
    seed_state: Path = field(default_factory=lambda: Path(os.environ.get("SEED_STATE", CONTRACTS / "fixtures" / "state.fixture.json")))
    reset_on_start: bool = field(default_factory=lambda: _flag("RESET_ON_START", False))
    dev_endpoints: bool = field(default_factory=lambda: _flag("DEV_ENDPOINTS", True))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()))
    photon_enabled: bool = field(default_factory=lambda: _flag("PHOTON_ENABLED", False))
    photon_api_key: str = field(default_factory=lambda: os.environ.get("PHOTON_API_KEY", ""))
    photon_project_id: str = field(default_factory=lambda: os.environ.get("PHOTON_PROJECT_ID", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
