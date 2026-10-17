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
| `POST /reports` | a structured fact (`report.schema.json`; `id`/`observed_at_t_s` default to new/the clock). `need` / `closure_report` / `facility_status` → replan → WS `report`, `plan`, one `assignment` per change, `metrics` |
| `POST /disruption` | judge's map controls: `{"close_edges": [edge ids]}` (reverse direction closed too) or `{"facility_id", "set": {...}}` → report → replan |
| `POST /replan` | replan now (no new fact) |
| `POST /clock {t_s}` | move the sim clock (play / scrub); broadcasts `state` |
| `GET /comparison?seeds=5` | baseline vs EMBER on paired perturbations (`comparison.schema.json`), cached per plan version (~3 s first call) |
| `GET /phones`, `POST /phones {role, handle}` | tester phones by role (`resident` → the judge's household, `operator` → the critical hospital); POST creates the Photon shared-line assignment and returns `assigned_number` |
| `POST /messages {thread, text, plan_version?, assignment_id?}` | send on a thread (gets the `[EMBER drill]` prefix); returns `delivery`: `sent` / `failed` / `not_opted_in` / `no_phone` / `dev` |
| `POST /dev/reset` | reseed from `SEED_STATE` and broadcast `state` (rehearsals; `DEV_ENDPOINTS=0` hides it) |
| `POST /dev/inbound {role, text}` | pretend a tester texted (same path as a real Photon message); stage fallback |

## Photon (2.0 Beta)
1. `.env`: `PHOTON_ENABLED=1`, `PHOTON_API_KEY`, `PHOTON_PROJECT_ID` (key needs project:read/write, platforms:read/write).
2. `curl -X POST localhost:8000/phones -H 'content-type: application/json' -d '{"role":"resident","handle":"4135550100"}'` (and `operator`).
3. Each tester texts anything to their `assigned_number` (Photon's opt-in rule: a shared line can't text first). `GET /phones` then shows `opted_in: true`.
4. `GET /health` → `photon_listener.socket` should be `subscribed`; if the socket is down for 5 s, the backend polls `GET /messages` every 2 s instead.

Inbound texts are deduped by Photon message id; the event cursor is saved after each handled event and survives restarts and `/dev/reset`.

**Engine mode (default):** `SCENARIO` (default `scenarios/allston_flood_v1/scenario.json`) → plan v1 by the
allocator at startup (~2 s), state = `simulate(plan, reports).state_at(clock)`. The DB is kept across
restarts (a crash mid-demo keeps plans, reports, messages); it re-plans from scratch when `SCENARIO`
changes, on `RESET_ON_START=1`, or `POST /dev/reset`. All engine calls go through `residents/engine_bridge.py`.
**Static mode:** `SCENARIO=` (empty) serves `SEED_STATE` (the state fixture) as-is; engine endpoints return 503.

Check the live output against the contract:
```bash
curl -s localhost:8000/state > /tmp/state.json
uv run --project ../engine ember validate-state /tmp/state.json --scenario ../contracts/fixtures/scenario.fixture.json
```

## WS events (draft, `ws-events.schema.json`)
`state` (full snapshot) · `plan` (a new plan version) · `assignment` (`{plan_version, change, assignment_id, assignment}`, one per changed assignment) · `message` · `report` · `metrics` · `scatter_point`.
`seq` goes up by 1 per broadcast; on a gap, re-fetch `GET /state`.
