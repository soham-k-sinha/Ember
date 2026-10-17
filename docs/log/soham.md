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

## 2026-10-17 05:30 · engine bridge: reports → replan, disruption, clock, comparison · branch soham/engine-bridge · commit (this PR)
What: backend plans on allston_flood_v1 by default (plan v1 at startup). `POST /reports` → allocate(prev, prev_reports) → new plan version → state → WS `report`, `plan`, one `assignment` per `plan.changes` entry, `metrics`. `POST /disruption` (close road both directions / set facility field), `POST /replan`, `POST /clock`, `GET /comparison` (cached per version).
Files: residents/residents/{engine_bridge,planner,contracts,db,app,config}.py, residents/tests/test_engine.py (+ test_api), residents/{README.md,.env.example}
Run: cd residents && uv run pytest -q (74 pass, real allocator on allston) ; uv run uvicorn residents.app:app ; curl -X POST localhost:8000/reports -d '{"source":"judge","kind":"need","household_id":10296,"payload":{"people":2,"mobility":true,"accessible_vehicle":true}}' -H 'content-type: application/json'
Interfaces: consumes ember_engine.allocator.allocate, sim.simulate(...).state_at, compare.compare (through engine_bridge.py only). Produces the HTTP API above + WS events per ws-events (D37/D38). Arnav: the plan event carries routes; `assignment` events are in `plan.changes` order; scrub with POST /clock. Anshuman: live judge beat at 75 min gives Accessible Van 3 → #10296. D41.
Status: done. `POST /optimize` (robust fan-out) waits on engine PR #12; outbound changed-instruction texts are Task 4 (plan hook in place).
Next: LLM extraction (text → report), then changed-instruction messages.

## 2026-10-17 06:30 · LLM extraction (text → report) · branch soham/llm-extraction · commit (this PR)
What: the one LLM call. Inbound texts (Photon or /dev/inbound) → Claude Opus 5.5 structured output (facts + confidence + clarifying question) → deterministic reports (need / closure_report with resolved edge ids / facility_status / confirm / reject / question) → one replan → the inbound message gets its report_id; missing info → one clarifying question back on the thread.
Files: residents/residents/{extract,intake,engine_bridge,db,app,config}.py, residents/tests/{test_extract.py,samples.json}, residents/scripts/eval_extract.py
Run: cd residents && uv run pytest -q (92 pass, no API calls) ; uv run python scripts/eval_extract.py → 20/20, median 1.9 s ; live: POST /dev/inbound {"role":"resident","text":"..."} with ANTHROPIC_API_KEY set
Interfaces: produces reports per report.schema (closure payload carries edge_ids + road_hint/cross_street), WS `message` re-sent with report_id after extraction (clients upsert by id). D43.
Status: done. Live chain verified: judge demo line → one combined clarifying question; "2 of us. River St near Memorial Dr is flooded" → need + closure → plan v2; operator "90 minutes of fuel" → backup_endurance_s 5400 → v3.
Notes for the team:
  - Anshuman/Aryaman: the judge (#10296) is AT River St × Memorial Dr. A judge text that closes River St there leaves no open route to the household → van-3 "no open route", judge unreached. The demo line should name a street on the van's way, not the judge's own access street (or engine could allow an alternate pickup node).
  - Operator "90 min of fuel" at 75 min: allocator keeps gen-1 at Cottage Farm and lists mt-auburn as unresolved ("the only compatible generator is protecting cottage-farm"), hospital outage 75 min. Good trade-off for the beat; a shorter endurance moves the generator (Aryaman's test: 10 min at 50 min).
  - Questions from residents ("is the bridge open?") are stored as `question` reports; nothing answers them automatically yet.
Next: Task 4 outbound: text only changed instructions (with plan_version) after each replan; then confirm/reject + stale replies.

## 2026-10-17 07:40 · outbound instructions + POST /optimize · branch soham/optimize-outbound · commit (this PR)
What: Task 4 outbound: after each plan version, every opted-in phone gets a text only when its own instruction materially changed (new/replaced vehicle, cancelled, ETA ±10 min); assignment → `offered` (and kept offered across replans); plan info_requests asked once (e.g. after the judge's first "hi"). `POST /optimize` (202) runs the robust fan-out via EngineSession.optimize, streaming `scatter_point` then `plan`; `GET /optimize` status. Dropped residents/ws-events.schema.json; tests use contracts/ws-events.schema.json and validate engine's example events.
Files: residents/residents/{outbound,planner,engine_bridge,intake,db,app,bus}.py, residents/tests/{test_outbound,test_ws_schema,test_engine}.py, residents/README.md
Run: cd residents && uv run pytest -q (101 pass) ; curl -X POST 'localhost:8000/optimize?seeds=20&k=4' and watch WS
Interfaces: WS `assignment` with change `status_changed` when an instruction is texted; `scatter_point` per ws-events (D38) with n_total for progress. D44.
Status: done. Local optimize on Allston (k=2, seeds=3): 9 points in 2.7 s, plan v2 with search.robust.
Notes: Aryaman — at t=0 `EngineSession.optimize` tags points `batch_id`/`plan_version` = v1 but returns plan v2 (version bumped after the fan-out); the web clears the scatter per batch, so fine, but the tag says v1. Arnav — upsert messages by id (a message is re-broadcast when its report_id is set).
Next: Task 5 confirm/reject (+ stale plan_version replies), then a live phone run-through.
