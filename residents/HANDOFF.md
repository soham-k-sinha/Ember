# residents/ HANDOFF: the backend in one page for the next agent

Last updated: Sat 2026-10-17, late night (integration of D74–D84). Team-wide status, run commands and measured numbers:
`docs/HANDOFF.md`. API, drill, calls and Photon setup: `residents/README.md`. Decisions: `docs/DECISIONS.md`.
Aryaman is the sole owner of the repo (D77).

## What the backend is
FastAPI + SQLite. The DB is the source of truth; the engine session is resumed from it on every call (D41/D42).
People take part by text (Photon 2.0) and by phone call (ElevenLabs on the Photon SMS number, EMBER as its Custom
LLM, D74). One LLM call turns a message into structured facts; the deterministic planner replans; each person gets
one reply per turn, worded by a second model from the computed messages and checked by a guard (D76). When the model
is unavailable a keyword parser returns the same `Extraction` (D75). Strangers join by texting "JOIN EMBER" to the SMS
number (D78).

```
scenarios/allston_flood_v1  +  engine/data/town.json.gz
        │
engine/ember_engine  api.EngineSession  ← the only entry point (via residents/engine_bridge.py)
        ▼
residents/  Photon ⇄ phones · ElevenLabs ⇄ calls · HTTP + WS /ws ⇄ web/ · Daytona pool (warm, D82)
            ember-drill = the same app + phone registration + a console, in one process
```

## Rules enforced here (beyond CLAUDE.md)
- Every outbound text starts with **`[EMBER drill]`** and carries its `plan_version`. Offers stay provisional until YES.
- Replies are worded by the model but decided by the planner: the guard in `reply.py` rejects any number, vehicle,
  facility or street not in the computed messages and falls back to the computed text.
- Secrets live only in `residents/.env` (gitignored). Never commit keys or real phone numbers (tests use 555 numbers).
- Never send surprise texts or calls to real phones: automated runs use `PHOTON_ENABLED=0`, `EXTRACT_ENABLED=0` and
  empty `ELEVENLABS_*` / `ANTHROPIC_API_KEY` (empty variables beat `.env`). `tests/conftest.py` blanks the ElevenLabs key.
- Per-run memory lives in `kv` with a prefix; every new prefix must be added to `Store.clear_scenario()`.
  `player:<handle>` is kept across resets on purpose (D78).

## Files
| File | Role |
|---|---|
| `app.py` | `create_app(settings, photon_client=, bridge=, llm=)`; wires store → hub → bridge → planner → messenger → outbound → guide → intake → locator → voice, then bootstrap, the Photon listener, the retry loop and the warm Daytona pool. All endpoints; request models at module level. |
| `config.py` | `Settings` from env / `residents/.env` (mirrored in `.env.example`). |
| `db.py` | stdlib sqlite3 `Store`: state tables, messages, phones, kv, inbound_seen. `snapshot()` returns the state contract. |
| `bus.py` | WS hub; envelopes `{type, seq, t_s, data}`. |
| `engine_bridge.py` | The only file importing `ember_engine`. Optimize runs on its own session and World with the warm pool (D82); flood buildings cached for joins and `flood_corners`; `playback(which)` (D79). |
| `planner.py` | Replan loop: bootstrap, reports, replan, publish (WS + plan hooks), clock (+ clock hooks), confirm/reject, optimize, simulate, comparison, playback cache. One asyncio lock; engine work in a threadpool. |
| `messaging.py` | Inbound (dedupe, run boundary, opt-in learned) → stored message → WS → hooks; lobby for unplaced phones; joins (D78); one reply per turn (D76); `phone_inbound` for the console and calls. |
| `extract.py` / `fallback.py` | The one understanding call (Claude Sonnet 5.5, structured outputs; optional Chalk router, D83) and its keyword fallback (D75). `to_outcome()` is deterministic. |
| `reply.py` | The reply writer (Claude Haiku 5.5) and its guard (D76). |
| `intake.py` | Inbound hook, serialized: extract → reports → one replan per text → reply; YES/NO → confirm/reject (D57). |
| `outbound.py` | Plan hook: texts a phone only when its instruction materially changed (D44); records changes for pickup-changed calls. |
| `locate.py` / `places.py` | The lobby: where are you → a building → a household of the run (D56); players are placed on a flood-zone building (D78). |
| `guide.py` / `briefing.py` | Steps after YES with DONE (D56); every question answered from the plan (D57/D60). |
| `voice.py` / `speech.py` | Calls (D74): Custom-LLM endpoint, call manager that calls the most at-risk first (D80), `GET /calls {live, recent}`; text → speakable words. |
| `photon.py` / `threads.py` | Photon transport (REST, Socket.IO, polling fallback) and phone ↔ household/facility bindings. |
| `drill.py` | `uv run ember-drill` (README "The drill"). |
| `scripts/` | `sim_calls.py` (six calls end to end, no ElevenLabs or LLM), `eval_sim.py` (simulator-graded text → fact eval, D83), `eval_extract.py` (live accuracy, paid). |
| `tests/` | 279 tests, ~2 min. No network, no paid API: fake Photon (`fake_photon.py`), `FakeLLM` keyed on exact text, `EMBER_LOCAL_POOL=1`, `GEOCODE=0`, engine at `moves=10`. |

## Running it
```bash
cd residents && uv sync && uv run pytest -q
uv run ember-drill --dry                       # a whole drill, nothing sent; type texts as @r1 …
RESET_ON_START=1 PHOTON_ENABLED=1 uv run uvicorn residents.app:app --port 8000   # demo backend (docs/HANDOFF.md has the full command)
```
Settings worth knowing: `SCENARIO` (empty = static fixture mode), `START_T_S`, `ENGINE_MOVES`, `DB_PATH`,
`RESET_ON_START`, `PHOTON_ENABLED`, `EXTRACT_ENABLED`, `REPLY_ENABLED`, `JOIN_NUMBER` (default `PHOTON_VOICE_NUMBER`),
`MAX_PLAYERS` (30), `VOICE_MAX_CONCURRENT` (2; 0 = never call first), `VOICE_PORT`, `CHALK_ROUTER_KEY` + `CHALK_ENV_ID`.

## Key data (allston_flood_v1)
- Fleet, all at EMS 14: `van-1`, `van-2`, `van-3` (**the only wheelchair-accessible vehicle**), `truck-1`, `crew-1`,
  `gen-1` (500 kW camlock), `gen-2` (150 kW twist-lock). Reserve: 1 van, 1 generator.
- Facilities: `mt-auburn` (critical hospital), `cottage-farm` (pumping station, drives overflow m³), `putnam-ave-sub`,
  `outfall-mwr201`, `ems14` (response base), `treehouse-shelter` (the nearest drop-off since D58).
- 4 h horizon (`t_end_s` 14400), 60 s ticks, 40 synthetic households, judge **#10296** (needs unknown). Players and
  texted-in residents become town buildings (17,810).
- The flood zone is the Cambridgeport/Riverside side (Putnam Ave, Banks St, Memorial Dr × River St); Western Ave near
  Stadium Rd is outside it.

## Gotchas
- Run `uv sync` after pulling; if tests can't import `residents`: `uv sync --reinstall-package ember-residents`.
- Never patch the global `asyncio.sleep` in tests; patch `residents.photon._backoff`.
- Fake Photon timestamps default to now (texts from before the last reset are ignored by design).
- `FakeLLM` is keyed on exact text: a test that sends something new must script it.
- The view's assignment status is simulated progress (`en_route` at t=0); the raw plan (`store.current_plan()`) has
  the backend statuses.
- Two EMBER backends with Photon on would both answer every text; the drill's preflight blocks that.
- Worker-process code (the local optimize pool) must run from a file, not stdin (macOS spawn).
