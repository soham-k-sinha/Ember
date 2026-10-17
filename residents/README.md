# residents/ — Ember backend (Soham)

FastAPI + SQLite shared state, the HTTP/WS API the web uses, Photon 2.0 threads, the one LLM
extraction call, and the replan loop. Spec: `docs/TECHNICAL.md` §2 and §4; brief: `docs/team/soham.md`.

```bash
cd residents
uv sync
cp .env.example .env                       # fill in keys; PHOTON_ENABLED=0 works without any
uv run uvicorn residents.app:app --reload  # http://localhost:8000
uv run pytest -q
```

## API (so far)
| | |
|---|---|
| `GET /health` | `{ok, scenario_id, plan_version, t_s, photon}` |
| `GET /state` | the shared state, `contracts/state.schema.json` v0.1 (`source: "backend"`) |
| `GET /plan/current`, `GET /plan/{version}` | a plan with its assignments (404 if none) |
| `WS /ws` | events `{type, seq, t_s, data}`; a `state` event on connect, then broadcasts. Draft contract: `ws-events.schema.json` |
| `POST /dev/reset` | reseed from `SEED_STATE` and broadcast `state` (rehearsals; `DEV_ENDPOINTS=0` hides it) |

The DB is seeded from `SEED_STATE` (default: the state fixture) the first time, then kept across
restarts so a crash mid-demo doesn't lose messages. `RESET_ON_START=1` or `POST /dev/reset` reseeds.

Check the live output against the contract:
```bash
curl -s localhost:8000/state > /tmp/state.json
uv run --project ../engine ember validate-state /tmp/state.json --scenario ../contracts/fixtures/scenario.fixture.json
```

## WS events (draft, `ws-events.schema.json`)
`state` (full snapshot) · `plan` (a new plan version) · `assignment` (`{plan_version, change, assignment_id, assignment}`, one per changed assignment) · `message` · `report` · `metrics` · `scatter_point`.
`seq` goes up by 1 per broadcast; on a gap, re-fetch `GET /state`.
