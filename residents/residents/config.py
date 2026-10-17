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
    # Engine mode (default): the scenario the backend plans on; plan v1 is computed at startup.
    # SCENARIO= (empty) → static mode: serve SEED_STATE as-is, no planning (web dev without the engine).
    scenario: Path | None = field(default_factory=lambda: (
        Path(v) if (v := os.environ.get("SCENARIO", str(REPO_ROOT / "scenarios" / "allston_flood_v1" / "scenario.json"))) else None))
    start_t_s: float = field(default_factory=lambda: float(os.environ.get("START_T_S", "0")))
    # Static mode only: the snapshot the DB is seeded from.
    seed_state: Path = field(default_factory=lambda: Path(os.environ.get("SEED_STATE", CONTRACTS / "fixtures" / "state.fixture.json")))
    reset_on_start: bool = field(default_factory=lambda: _flag("RESET_ON_START", False))
    dev_endpoints: bool = field(default_factory=lambda: _flag("DEV_ENDPOINTS", True))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:43123,http://127.0.0.1:43123").split(",") if o.strip()))
    photon_enabled: bool = field(default_factory=lambda: _flag("PHOTON_ENABLED", False))
    # The socket listener; off in tests that inject a client and drive inbound by hand.
    photon_listen: bool = field(default_factory=lambda: _flag("PHOTON_LISTEN", True))
    retry_every_s: float = field(default_factory=lambda: float(os.environ.get("RETRY_EVERY_S", "20")))
    photon_api_key: str = field(default_factory=lambda: os.environ.get("PHOTON_API_KEY", ""))
    photon_project_id: str = field(default_factory=lambda: os.environ.get("PHOTON_PROJECT_ID", ""))
    # The one LLM call (text → report). On when engine mode is on and a key is set.
    extract_enabled: bool = field(default_factory=lambda: _flag("EXTRACT_ENABLED", True))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
