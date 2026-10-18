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


def _csv(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.environ.get(name, "").split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("DB_PATH", PKG_ROOT / "ember.db")))
    # Engine mode (default): the scenario the backend plans on; plan v1 is computed at startup.
    # SCENARIO= (empty) → static mode: serve SEED_STATE as-is, no planning (web dev without the engine).
    scenario: Path | None = field(default_factory=lambda: (
        Path(v) if (v := os.environ.get("SCENARIO", str(REPO_ROOT / "scenarios" / "allston_flood_v1" / "scenario.json"))) else None))
    start_t_s: float = field(default_factory=lambda: float(os.environ.get("START_T_S", "0")))
    # allocator search budget per (re)plan; unset = engine's default. Tests use a small one for speed.
    engine_moves: int | None = field(default_factory=lambda: int(v) if (v := os.environ.get("ENGINE_MOVES")) else None)
    # Static mode only: the snapshot the DB is seeded from.
    seed_state: Path = field(default_factory=lambda: Path(os.environ.get("SEED_STATE", CONTRACTS / "fixtures" / "state.fixture.json")))
    reset_on_start: bool = field(default_factory=lambda: _flag("RESET_ON_START", False))
    dev_endpoints: bool = field(default_factory=lambda: _flag("DEV_ENDPOINTS", True))
    # the web on any port of this machine or the LAN (a second laptop at the table)
    cors_origin_regex: str = field(default_factory=lambda: os.environ.get(
        "CORS_ORIGIN_REGEX", r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?"))
    photon_enabled: bool = field(default_factory=lambda: _flag("PHOTON_ENABLED", False))
    # The socket listener; off in tests that inject a client and drive inbound by hand.
    photon_listen: bool = field(default_factory=lambda: _flag("PHOTON_LISTEN", True))
    retry_every_s: float = field(default_factory=lambda: float(os.environ.get("RETRY_EVERY_S", "20")))
    photon_api_key: str = field(default_factory=lambda: os.environ.get("PHOTON_API_KEY", ""))
    photon_project_id: str = field(default_factory=lambda: os.environ.get("PHOTON_PROJECT_ID", ""))
    # an operator phone registered by role alone; empty = the critical hospital in the current state
    operator_facility_id: str = field(default_factory=lambda: os.environ.get("OPERATOR_FACILITY_ID", ""))
    # The one LLM call (text → report). On when engine mode is on and a key is set.
    extract_enabled: bool = field(default_factory=lambda: _flag("EXTRACT_ENABLED", True))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    # Sonnet 5.5: 44/45 on samples.json at 1.4 s median (Opus 5.5 45/45 at 2.2 s is too slow for a phone call; Haiku 5.5
    # 41/45 missed "we're at the corner now" and "we're fine to walk": a misread here can decline someone's van). D76.
    extract_model: str = field(default_factory=lambda: os.environ.get("EXTRACT_MODEL", "claude-sonnet-5-5"))
    extract_effort: str = field(default_factory=lambda: os.environ.get("EXTRACT_EFFORT", "low"))
    # Both model calls go through Chalk's AI Router when both are set (D83), else straight to Anthropic.
    chalk_router_key: str = field(default_factory=lambda: os.environ.get("CHALK_ROUTER_KEY", ""))
    chalk_env_id: str = field(default_factory=lambda: os.environ.get("CHALK_ENV_ID", ""))
    # Residents who text their location (D56): address lookups through OSM Nominatim (off in tests).
    geocode_enabled: bool = field(default_factory=lambda: _flag("GEOCODE", True))
    # The drill: no synthetic scenario households (only the people who text in), and a DONE from the last
    # person anyone waited on moves the sim clock to the next step.
    drill_residents: tuple[str, ...] = field(default_factory=lambda: _csv("DRILL_RESIDENTS"))  # ember-drill's phones
    drill_operators: tuple[str, ...] = field(default_factory=lambda: _csv("DRILL_OPERATORS"))  # PHONE@FACILITY
    drill_solo: bool = field(default_factory=lambda: _flag("DRILL_SOLO", False))
    auto_clock: bool = field(default_factory=lambda: _flag("AUTO_CLOCK", False))
    # Phone calls (D74): ElevenLabs runs the call on the Photon SMS number; our backend is its Custom LLM.
    photon_voice_number: str = field(default_factory=lambda: os.environ.get("PHOTON_VOICE_NUMBER", ""))
    elevenlabs_api_key: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_API_KEY", ""))
    elevenlabs_agent_id: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_AGENT_ID", ""))
    elevenlabs_phone_number_id: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_PHONE_NUMBER_ID", ""))
    voice_port: int = field(default_factory=lambda: int(os.environ.get("VOICE_PORT", "8100")))
    # someone who calls the number but isn't registered becomes a resident to be located (judges can call in)
    voice_admit_callers: bool = field(default_factory=lambda: _flag("VOICE_ADMIT_CALLERS", True))
    # Multiplayer (D89): POST /join registers a phone on the shared iMessage line, then its first text to that line places
    # it as Player N. Seats: every Photon assignment, team phones too (the free plan has 25, D92)
    max_players: int = field(default_factory=lambda: int(os.environ.get("MAX_PLAYERS", "25")))
    # D80: EMBER calls the most at-risk residents itself, at most this many calls at once (0: never calls first)
    voice_max_concurrent: int = field(default_factory=lambda: int(os.environ.get("VOICE_MAX_CONCURRENT", "2")))
    # D76: one natural reply per turn, written by Claude Haiku from the computed messages and checked by a guard
    reply_enabled: bool = field(default_factory=lambda: _flag("REPLY_ENABLED", True))
    reply_model: str = field(default_factory=lambda: os.environ.get("REPLY_MODEL", "claude-haiku-5-5"))
