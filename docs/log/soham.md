# Soham — backend log (`residents/`)

(no entries yet — first entry should be the FastAPI skeleton with `/state` serving the state fixture and one Photon inbound event logged)

## 2026-10-16 23:35 · backend skeleton + DB + WS · branch soham/backend-skeleton · commit (this PR)
What: FastAPI app with a SQLite shared-state store (TECHNICAL §2 tables + phones), seeded from the state fixture; `GET /state` reassembles the state contract from the DB; WS `/ws` sends a `state` event on connect and broadcasts envelopes `{type, seq, t_s, data}`; `POST /dev/reset` reseeds + broadcasts. Draft WS event contract.
Files: residents/{pyproject.toml,uv.lock,README.md,.env.example,.gitignore,ws-events.schema.json}, residents/residents/{app,bus,config,db}.py, residents/tests/*
Run: cd residents && uv sync && uv run uvicorn residents.app:app --reload ; uv run pytest -q (21 pass) ; curl -s localhost:8000/state > /tmp/s.json && uv run --project ../engine ember validate-state /tmp/s.json --scenario ../contracts/fixtures/scenario.fixture.json → OK
Interfaces: consumes state v0.1 (+ assignment/report v0.1). Produces GET /health, /state, /plan/current, /plan/{v}, WS /ws (D36, D37). Draft `residents/ws-events.schema.json`: Aryaman, please move it to contracts/; Arnav, build the WS client against it (on a seq gap, re-fetch /state). CORS allows localhost:5173.
Status: done. Seed is the example-scenario fixture (judge #492); switch SEED_STATE to the engine's allston_flood_v1 snapshot when it exists.
Next: Photon plumbing (assignments for 2 phones, Socket.IO inbound, send_message with plan_version + Idempotency-Key, polling fallback, /dev/inbound).

## 2026-10-17 04:40 · Photon plumbing · branch soham/photon-plumbing · commit (this PR)
What: Photon 2.0 Beta threads, verified live: 2 shared-line assignments (resident/judge + operator), Socket.IO listener (subscribed, cursor persisted), inbound texts stored as thread messages + WS `message`, outbound `send_message` (drill prefix, plan_version, Idempotency-Key, retries, opt-in enforced), polling fallback, `/phones`, `/messages`, `/dev/inbound`. CORS adds :43123.
Files: residents/residents/{photon,messaging,threads,db,app,config}.py, residents/tests/{fake_photon,test_photon_client,test_messaging,test_listener}.py, residents/{README.md,.env.example,pyproject.toml,uv.lock}
Run: cd residents && uv run pytest -q (53 pass) ; PHOTON_ENABLED=1 uv run uvicorn residents.app:app → GET /health shows photon_listener.socket = subscribed
Interfaces: produces WS `message` events (state.messages[] shape) for every inbound/outbound text; `POST /messages` for the web's operator console; `POST /dev/inbound {role, text}` as the no-phone fallback. Arnav: CORS allows localhost:43123 and :5173. D40.
Status: done. Live: both phones' "hi" arrived via the socket (opted in), test replies accepted by Photon (202). Inbound hooks are in place for extraction (Task 3).
Next: engine bridge (seed from allston_flood_v1, POST /reports → allocate → plan + assignment events, /disruption, /comparison, /optimize), then LLM extraction.
