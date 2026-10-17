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

## 2026-10-17 13:20 · INCIDENT + fix: old texts re-answered after a reset · branch soham/replay-guard · commit (this PR)
What happened: restarting the live server with RESET_ON_START=1 while Photon was slow → the socket's first connect timed out and the listener gave up on the socket (polling only). The poll window marker had never advanced (it only moved while polling) and the reset had emptied the messages table used for dedupe, so the poller re-fetched the judge phone's earlier texts and EMBER answered 6 of them again on the real (team) phone, drill-prefixed. I stopped the server within ~1 min.
Fix: run boundary (texts sent before the last reset are ignored), `inbound_seen` table that survives resets, poll window kept fresh + capped at 10 min, socket reconnects forever with backoff. Regression tests for each guard (each verified by mutation; one test was initially hollow and was fixed). Test fakes no longer use a fixed timestamp (would have broken after 12:00 UTC with the run boundary).
Files: residents/residents/{photon,messaging,planner,db}.py, residents/tests/{test_replay_guard,test_listener,fake_photon}.py
Run: cd residents && uv run pytest -q (129 pass)
Verified live: restart without reset → socket subscribed, redelivered the 7 old events from the saved cursor → all deduped, 0 texts sent.
Interfaces: none changed. D54.
Status: done.

## 2026-10-17 14:00 · residents/HANDOFF.md · branch soham/handoff-doc · commit (this PR)
What: a full-context handoff for the next agent in this lane: project, hard rules, team/lanes, git protocol, architecture + every residents file, API, running it, task status, every PR and the bugs each fixed, demo numbers, open items, gotchas.
Files: residents/HANDOFF.md
Run: read it first in a fresh session (then CLAUDE.md, docs/HANDOFF.md, DECISIONS, logs)
Interfaces: none.
Status: done. 129 tests pass on main c0c65ba.
Next: re-measure the demo beats after Aryaman's #36; Task 9 only if green-lit.

## 2026-10-17 · multiple household phone conversations + opt-in feedback · branch soham/multi-household-phones
What: replaced one-phone-per-role registration with one phone per household/facility, scoped to the current scenario. `/phones` accepts household_id/facility_id; occupied targets and attempts to bind a phone elsewhere return 409 without removing any registration. Migrated legacy SQLite rows transactionally, preserving chat IDs and opt-in. `/ask` and `/dev/inbound` accept explicit targets and reject ambiguous role-only selection. Inbound facts, pending questions, instructions, YES/NO responses and failed-send retries use the correct household's conversation. Blocked prompts/offers no longer count as sent; new opt-ins get current questions/offers, including assignment IDs for confirmation. `/phones`, `/ask` and `/messages` return actionable opt-in/delivery guidance. Added tested bash/zsh request helpers and a two-person runbook.
Files: residents/residents/{app,db,threads,messaging,intake,outbound}.py, residents/tests/{test_multi_household,test_messaging}.py, residents/scripts/requests.sh, residents/README.md, docs/DECISIONS.md, docs/log/soham.md
Run: cd residents && .venv/bin/python -m pytest -q → 149 passed in 82.51 s. 20 new cases include migration/restart/reset, conflict and invalid targets, simultaneous resident texts, isolated pending needs, targeted prompts, confirm/reject, first-contact opt-in, unsent offers, line changes, scenario isolation, retry destinations and legacy instruction markers. Initial regression run failed on the old implementation. requests.sh syntax + JSON bodies checked in bash and zsh; git diff --check clean.
Interfaces: D55. New optional household_id/facility_id on POST /phones, /ask, /dev/inbound; delivery responses include action_needed and assigned_number. Shared contract objects unchanged. Photon opt-in remains real first-contact evidence, not a writable flag.
Status: implemented and tested locally on Soham's branch. Automated tests use the real allocator with fake Photon HTTP and fake extraction; no real messages or paid API calls sent. Read-only live check confirmed the current resident's missing opt-in/chat IDs. Running server was left untouched and must be restarted to load code and migrate its DB; RESET_ON_START=0 preserves the run. Previously deleted registrations cannot be recovered automatically.
Next: restart backend, register each additional tester against an unused ID from /state, have each text HI to its returned assigned_number, then follow residents/README.md's multi-resident rehearsal.

## 2026-10-17 · the text-driven drill: location → questions → offer → step-by-step directions · branch soham/drill
What: residents register with `locate` and text where they are (address / intersection / landmark / coordinates); places.py turns it into a point (coords → town.json intersection → Nominatim bounded to the town), the nearest free building becomes a household of this run (engine gets it via `EngineBridge.set_extra_households`), the phone is bound and the plan asks its question. After YES, guide.py texts one step at a time from the simulator's arrive / pickup / drop-off times (walk to the corner with distance/direction, or wait inside for a door pickup; board; ride; checked in; operators: meet the crew, connecting, powered) and takes DONE replies; with AUTO_CLOCK the clock jumps to the next event once nobody is pending. `uv run ember-drill` runs backend + phones + console in one process. Also: offers name the pickup corner and how long until the water; unthreatened households are told to shelter in place (the plan sends them nothing; the old text blamed busy vehicles); statuses after pickup / when powered; no false "no longer coming" after a drop-off; preflight refuses to run next to another Photon EMBER. Removed the tester phone numbers from tests (555 placeholders).
Files: residents/residents/{places,locate,guide,drill}.py (new), {app,config,db,engine_bridge,extract,intake,messaging,outbound,planner,threads}.py, residents/tests/test_drill.py (new, 24 tests) + number scrub in tests, samples.json (+6), scripts/eval_extract.py, pyproject (ember-drill script), README, HANDOFF, docs/DECISIONS.md (D56).
Run: cd residents && uv run pytest -q → 173 passed. 10 mutations of the new guards all caught. Live LLM eval 27/27 (median 2.2 s). Dry drills with the real LLM + Nominatim: 125 Western Ave → placed, offer, YES, 4 steps, clock 0 → 55 → 61 → 64 min; wheelchair door pickup + Mount Auburn operator generator steps. Live Photon registration of a locate phone OK (no texts sent).
Interfaces: D56. POST /phones gains `locate`; POST /dev/inbound gains `handle`; Planner.clock_hooks; Settings GEOCODE / DRILL_SOLO / AUTO_CLOCK. Contracts unchanged (added households are ordinary scenario/state rows).
Status: on soham/drill, stacked on #38. Not run end to end on real phones yet: an older backend (pre-#38 code, Photon on) is still running on :8000 and must be stopped first.
Next: Soham runs `uv run ember-drill --resident <phone>` from a flood-zone corner. Aryaman: unthreatened households get no vehicle in solo but do in the full scenario (see HANDOFF §10).

## 2026-10-17 · fix: ember-drill crashed when a phone changed part between runs · branch soham/drill
What: live, `ember-drill --resident A --resident B` crashed with PhoneConflict because B had been the hospital operator in the previous run (drill.db keeps phones). A fresh run now takes the command line as the truth: listed phones are re-bound to their new part (Photon line + opt-in kept), phones not listed are dropped; a phone listed twice or two phones for one facility → one-line error (SetupError), and a failed start shuts the server down cleanly instead of a traceback.
Run: 175 passed (2 new regression tests); the exact failing command replayed in --dry on a copy of the live drill.db → both registered as residents, opt-in kept.

## 2026-10-17 · the plan around other people, in words (D57) · branch soham/drill
What: from Soham's two-phone run. residents/briefing.py builds sentences from the plan only: why this vehicle + who is ahead on it (offers), which vehicles fit the household and what each is doing, other households of the run near you and whether they share your vehicle, ETA / pickup place / destination / what to bring. Extraction gains `question_topic`; intake answers by topic (else "passed to the coordinators"). A NO to the only fitting vehicle asks first; YES after a decline undoes it; status after YES never says "Reply YES"; "arranging a pickup" replaced by honest texts (declined the only vehicle → "reply YES if you want it after all"; nothing scheduled → say so). Offers outside the flood say they're a precaution; the drill tells testers outside the flood which corner to use. The model's own clarifying question next to a need is sent after the offer ("Welch's" → "Did you mean a wheelchair-accessible vehicle?").
Run: 181 passed (6 new transcript-replay tests + 2 updated reject tests: one NO to the only accessible van now asks first). 8 mutations of the new guards caught. Live eval 32/32 (+5: question topics, decline + question, garbled need), median 2.3 s. Soham's transcript replayed with the real LLM in --dry: every reply now matches the plan.
Interfaces: D57. Fact.question_topic; behaviour change: a texted NO to the only fitting vehicle needs a second NO (POST /assignments/{id}/reject from the console is unchanged).
Next (engine, Aryaman): (1) declines as constraints: the allocator re-proposes a declined (vehicle, household) pair; the backend hides it, so the household gets nothing even when another vehicle is free; (2) multi-household trips: each trip carries one household, so neighbours at one corner can't ride together even with seats free; (3) drop-off choice: every rescue goes to the response base (EMS 14), never the Treehouse shelter, even for people standing next to the base; (4) unthreatened households: sometimes served, sometimes not (solo vs crowded).

## 2026-10-17 · HANDOFF.md refreshed for the next agent · branch soham/drill
What: rewrote residents/HANDOFF.md to the current state: open stacked PRs #38/#39 and how to merge them (#38 first, then rebase #39), every residents file incl. places/locate/guide/briefing/drill, how the planner decides and its engine-side limits, the drill flow and flood zone, live processes, decisions D55–D57, engine asks for Aryaman, gotchas.
Status: in #39. No code change.

## 2026-10-17 · HANDOFF §12: everything an agent needs to continue in a new chat · branch soham/drill
What: added residents/HANDOFF.md §12: Soham's standing instructions, session history, verification commands (dry drill by piped console, mutation checks, live eval), tool quirks on this Mac, environment and local files, key scenario ids and the flood-zone corners, code conventions and test helpers, prioritized next steps. Drill settings added to residents/.env.example.
Status: in #39. No code change.

## 2026-10-17 · every question gets an answer from the plan (D60) · branch soham/questions
What: live, a resident at 125 Western Ave (outside the flood, details not given yet) asked "what's the plan?" and "what to do?" and got only "We've passed your question to the coordinators." (topic `other`, no needs → no status → bare escalation, and nobody reads that queue). Now the LLM still only labels the question (new topics `plan`, `flood`, `roads` + `road_hint`, `safety`; asking whether an item or pet is allowed = `other`) and every answer is computed: `plan` and any topic with nothing specific for the person (an ETA before a vehicle is assigned) get their situation (`Outbound.situation`: status + the step they're on via `Guide.current_text` + the plan's open question); flood = scenario keyframes (their street, the first corners); roads = closures in the state for the whole named street (`EngineBridge.named_edges`); safety = fixed Ready.gov wording ("In a real emergency, call 911…"). `other` gets the situation and goes on a coordinators' queue (kv `question:`, `GET /questions`, `POST /questions/{report_id}/answer`, drill console `questions` / `tell r1 …`, printed as it happens). A question before a location says why we need it; a need + question gets the offer and the answer; a question with missing details asks once. Also on this branch: rebased #38/#39 onto main with D58; after D58 the "you declined the only vehicle" status must come before the engine's new unresolved entry (it said "outside the flood area" instead); `test_listener` poll test made relative to now (it hard-coded 12:00 UTC and failed once that was > 10 min old: D54's window clamp).
Files: residents/residents/{extract,briefing,outbound,intake,guide,locate,engine_bridge,app,drill,db}.py, residents/tests/test_questions.py (new, 16), test_drill.py / test_conversation.py (the two pinned "passed to the coordinators" replies, updated on purpose), test_listener.py, samples.json (+13), README, docs/DECISIONS.md (D60).
Run: cd residents && uv run pytest -q → 198 passed. 21 mutations of the new guards, all caught (after removing one redundant guard and adding a cross-street test). Live eval 45/45 (3 samples verbatim from the run), median 2.2 s. Dry drills with the real LLM + Nominatim: the live transcript (125 western ave → what's the plan? → what to do?) and a flood-zone run (lobby question, details + "how long?", YES, "what now", cat → queue → tell, safety, DONE → step 2).
Interfaces: D60. New: GET /questions, POST /questions/{report_id}/answer; Fact.question_topic gains plan/flood/roads/safety; Outcome.road. Contracts unchanged (question metadata lives in kv, not the report payload).
Also: after Aryaman's D59 (shared trips, merged meanwhile; mine renumbered to D60) the texts said "each vehicle takes one household per trip": `Briefing.trip_mates` reads the engine's "shares the trip with household #…" rationale (both directions, whole chain); offers and "is anyone near me?" say you share the trip, or why not (seats). +1 test, 4 more mutations caught.
Status: on soham/questions (contains #38 and #39, rebased on main). Not yet on a real phone.
Next: Soham re-runs the two-phone drill; then the voice channel (residents/VOICE_PLAN.md).

## 2026-10-17 · phone calls: ElevenLabs on the Photon number, EMBER as its Custom LLM (D61) · branch soham/voice
What: Soham set up Photon SMS number ↔ ElevenLabs (inbound + outbound tested). The backend is now the agent's Custom LLM: residents/voice.py serves `/{secret}/v1/chat/completions` (OpenAI-compatible SSE, "One moment..." after 1.2 s) on its own port; each caller turn goes through `Messenger.phone_inbound` like a text, and while a call is live everything the backend would text that phone is captured and said instead (speech.py renders it). Caller identified from the agent's system prompt (system__caller_id / called_number, the end that isn't our number); unknown callers admitted as residents to locate. Outbound: `Voice.call` (ElevenLabs sip-trunk/outbound-call, first message = OPENER + the situation, falls back if overrides are off), `POST /calls`, console `call r1`, `ember-drill --caller PHONE=ADDRESS` (placed, called only if the forecast flood reaches it). `--voice` starts the voice app + a cloudflared quick tunnel + read-modify-writes the agent's custom_llm URL and system prompt (verified by a second read).
Files: residents/residents/{voice,speech}.py (new), messaging.py, app.py, config.py, drill.py, tests/test_voice.py (new, 19), .env.example, README, docs/DECISIONS.md (D61).
Run: uv run pytest -q → 217 passed. 13 mutations of the new guards caught. Parity test: the same words by text and by call give the same replies. Live: dry backend + real cloudflared tunnel + a pretend ElevenLabs turn over the internet → wrong path 404, reply streamed in 0.7 s (the Mac's DNS took ~78 s to resolve the new trycloudflare hostname).
Interfaces: D61. POST/GET /calls; Settings PHOTON_VOICE_NUMBER, ELEVENLABS_*, VOICE_PORT, VOICE_ADMIT_CALLERS. Contracts unchanged.
Status: not yet a real call through the backend: needs Soham's ElevenLabs keys in .env, then `ember-drill --voice`.
Next: a real inbound call, then `--caller` to his phone; then the two-phone voice drill.
