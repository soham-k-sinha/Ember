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

## 2026-10-17 08:40 · confirm / reject + stale replies · branch soham/confirm-reject · commit (this PR)
What: Task 5. "yes"/"no" texts (and POST /assignments/{id}/confirm|reject) → stale check against the answered plan version → confirmed (sticky in the allocator, household shows confirmed, ack text) / rejected (ack, replan, never re-offered). Stale → latest instruction re-sent. Confirmed work that moves later gets an "Update:" text, not a second confirmation request.
Files: residents/residents/{planner,outbound,intake,db,app}.py, residents/tests/{test_confirm,test_api}.py, residents/README.md
Run: cd residents && uv run pytest -q (108 pass)
Interfaces: WS `assignment` with change `status_changed` on offered/confirmed/rejected. D45.
Status: done. Bug found + fixed: a request model defined inside create_app() was invisible to FastAPI (postponed annotations), so the confirm body (plan_version) was silently ignored; regression test checks every JSON endpoint declares its body.
Notes for Aryaman (engine, please):
  - `rejected` isn't understood by carry_over: a declined (resource, household) pair goes back into prev_queues and is usually re-proposed. The backend works around it (no re-offer, keeps it rejected), but the vehicle stays booked. Ask: treat `status == "rejected"` like cancelled history and exclude that pair in construct().
  - Confirming moves the work to the front of the vehicle's queue: judge confirmed at t=0 → van-3 ETA 153 → 21 min on the next replan (carry_over sets free_at = rescue_cycle from now). Intended? It can push earlier-deadline households later.
Next: robustness (Task 8: duplicate reports, two replies in a row, Photon outage) and a live phone run-through.

## 2026-10-17 09:40 · fixes from the first real-phone run-through · branch soham/conversation-fixes · commit (this PR)
What: the live judge conversation exposed (1) a later partial need ("Yes, 2 people") replacing the earlier one and dropping the wheelchair → the non-accessible Generator truck was assigned and confirmed; (2) no reply when the plan couldn't serve the judge yet; (3) generic chatter replies. Fixed: need payloads merge with the household's known needs; every fact gets a reply (instruction or computed status incl. the allocator's blocked_by); chatter → open info_request, else status, else the model's prompt; questions → "passed to the coordinators" + status.
Files: residents/residents/{extract,outbound,intake}.py, residents/tests/test_conversation.py
Run: cd residents && uv run pytest -q (112 pass; the replay test fails on the previous code)
Interfaces: none changed. D46.
Status: done.
Notes: Anshuman — at 50 min the judge's accessible need is unservable ("every eligible vehicle is committed to earlier deadlines"); EMBER now tells the judge that honestly, but for the demo beat the judge needs a reachable accessible vehicle (Aryaman's earlier note).
Next: switch engine_bridge.py to EngineSession (Aryaman's request), then Task 8 robustness + Task 6/7 leftovers.

## 2026-10-17 10:10 · engine_bridge → EngineSession · branch soham/engine-session · commit (this PR)
What: every engine call (initial plan, replan, state_at, compare, optimize) now goes through `ember_engine.api.EngineSession`, as Aryaman asked (D42). The DB stays the source of truth: the session is resumed from the stored plan + reports before each call, so restarts need nothing special. ENGINE_MOVES removed (EngineSession has no moves option).
Files: residents/residents/{engine_bridge,app,config}.py, residents/tests/*, residents/{README.md,.env.example}
Run: cd residents && uv run pytest -q (112 pass, 56 s) ; equivalence check: old direct allocate/simulate path vs EngineSession → identical v1, v2 (judge need), changes and state.
Interfaces: none changed.
Status: done. (residents/ws-events.schema.json was already removed in #16.)
Note for Aryaman: could EngineSession.__init__ take an optional `moves=` passed to allocate()? Our test suite went from 18 s to 56 s without the shortened search.
Next: Task 8 robustness, Task 6 scripted operator prompt, Task 7 POST /simulate.

## 2026-10-17 11:00 · robustness (Task 8) + street resolution aligned to the tuned beat · branch soham/robustness · commit (this PR)
What: intake serialized end to end; double-sent facts don't replan twice; planner failure → stored report + honest text + server stays up; failed sends retried with the same Idempotency-Key; "River St" near the judge now = engine's edges_by_name 150 m (+ reverse twin 951) instead of 12 edges at 500 m. Tuned judge beat (D47) driven from the judge's text passes end to end. EMBER_LOCAL_POOL=1 in tests (Aryaman's D48 request).
Files: residents/residents/{intake,messaging,engine_bridge,photon,db,app,config}.py, residents/tests/{test_robustness,test_conversation,test_extract,conftest,...}.py, residents/{README.md,.env.example}
Run: cd residents && uv run pytest -q (119 pass, ~60 s)
Interfaces: none changed. D51.
Status: done. Found while building it: tests had patched the global asyncio.sleep (to skip Photon backoff), which made the new retry loop spin without yielding and hang the suite; fixed with a photon-local `_backoff` hook.
Notes: Aryaman — closing both directions adds 951 (reverse of 833) to your [523, 833, 952]; I re-ran your beat with it: judge still gets van-3 at 121 min (deadline 165) and the generator still changes. Anshuman — the judge's text in DEMO.md can be "2 of us, my mom's in a wheelchair, River St is blocked" at minute ~5; that exact flow is a residents test now.
Next: Task 6 (operator prompt from the web), Task 7 (POST /simulate), live phone re-run.
Follow-up (same PR): adopted EngineSession's new `moves=` (Aryaman, b9b1613): `ENGINE_MOVES` env (unset = engine default in production); tests run the bridge at moves=10 and the demo-beat test at the default search. 119 tests in 27 s (was 62 s).

## 2026-10-17 11:50 · operator prompts, /simulate, non-blocking /optimize · branch soham/operator-simulate · commit (this PR)
What: Task 6: `POST /ask {role, question?}` (default = the plan's open question for that thread; marks it asked; the reply flows through extraction → facility_status → replan). Task 7: `POST /simulate {planner}`. /optimize no longer holds the planner lock during the fan-out (own EngineSession + World); a replan meanwhile → result discarded as superseded.
Files: residents/residents/{planner,engine_bridge,app,contracts}.py, residents/tests/{test_operator_simulate,test_api}.py, residents/README.md
Run: cd residents && uv run pytest -q (124 pass)
Interfaces: new endpoints POST /ask, POST /simulate. D52.
Status: done. Tasks 1–8 complete; Task 9 (voice) only if green-lit.
Notes for Aryaman (web): during playback the web POSTs /clock every 1.2 s — each broadcasts a full `state` event, so the WS client gets the state twice (event + its own GET /state refetch); either is enough. /ask is there for the operator console ("Ask the hospital").
Found while building it: World's route caches can be cleared by one thread while another reads them (KeyError), so the optimize session loads its own World instead of sharing one across threads.

## 2026-10-17 12:30 · DEMO.md dry run: question on reset + endurance in minutes · branch soham/demo-dry-run · commit (this PR)
What: ran DEMO.md's Replay end to end against a live backend (real LLM, real allocator, Photon off). All beats land: judge text → v2 in 3.7 s, Van 3 → #10296, Gen 1 ETA 14 → 32, judge texted; operator text → v3 in 2.2 s, Gen 1 → mt-auburn, Cottage Farm unresolved, overflow 9,600 m³, operator texted; optimize 100 runs → c03, judge van + hospital generator unchanged. Fixed the two gaps it showed: the judge's question is now sent right after a reset/startup (no manual /replan), and endurance is extracted in minutes (10 min → 600 s, was 612 s).
Files: residents/residents/{planner,app,extract}.py, residents/tests/{test_engine,test_extract,test_operator_simulate,test_conversation}.py, residents/tests/samples.json, residents/scripts/eval_extract.py, residents/README.md
Run: cd residents && uv run pytest -q (125 pass) ; uv run python scripts/eval_extract.py → 21/21 (demo operator line added)
Interfaces: none changed. D53.
Status: done.
Notes for Aryaman (DEMO.md owner): measured today — beat 2 judge pickup 121 min (DEMO says 132) vs deadline 165; beat 4 hospital outage 15 min (DEMO says 16); setup step 6 no longer needs the "POST /replan once" fallback (keep it as a fallback). Every `/dev/reset` re-texts the judge's question to the opted-in phone; that's intended for rehearsals but means the judge phone collects one question per reset.
