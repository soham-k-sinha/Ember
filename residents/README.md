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
| `WS /ws` | events `{type, seq, t_s, data}`; a `state` event on connect, then broadcasts. Contract: `contracts/ws-events.schema.json` |
| `POST /reports` | a structured fact (`report.schema.json`; `id`/`observed_at_t_s` default to new/the clock). `need` / `closure_report` / `facility_status` → replan → WS `report`, `plan`, one `assignment` per change, `metrics` |
| `POST /disruption` | judge's map controls: `{"close_edges": [edge ids]}` (reverse direction closed too) or `{"facility_id", "set": {...}}` → report → replan |
| `POST /replan` | replan now (no new fact) |
| `POST /optimize?seeds=20&k=4` → 202 | robust fan-out (top-k candidates × perturbed worlds + baseline; Daytona if engine/.env has a key, else local processes). Streams WS `scatter_point`, then `plan`. Runs outside the planner lock on its own engine session + World (clock / texts / replans keep flowing); if a replan lands meanwhile the result is discarded as superseded. 409 while running; `GET /optimize` = `{running, last}` |
| `POST /simulate {planner: ember\|baseline}` | projected metrics over the horizon for the current plan or the incident-by-incident baseline, with every report known by the clock |
| `POST /ask {role, household_id?, facility_id?, question?}` | prompt a specific household/facility. A role alone works with at most one active registration of that role; multiple matches → 422. Returns delivery status, assigned_number and action_needed; blocked sends do not consume the plan's question. |
| `POST /clock {t_s}` | move the sim clock (play / scrub); broadcasts `state` |
| `GET /comparison?seeds=5` | baseline vs EMBER on paired perturbations (`comparison.schema.json`), cached per plan version (~3 s first call) |
| `POST /assignments/{id}/confirm`, `/reject` `{plan_version?}` | the person accepts / declines an offer (texts "yes"/"no" take the same path). Reject → replan; that vehicle is never re-offered to them. 409 if `plan_version` is older and the assignment changed since (stale) |
| `GET /phones`, `POST /phones {role, handle, household_id?, facility_id?}` | one phone per household/facility, many residents/operators. Residents specify household_id, operators facility_id. Omission uses the original judge/hospital default. Occupied target or a phone bound elsewhere → 409; never silently replaces a registration. Returns thread, assigned_number, opted_in and action_needed. |
| `POST /messages {thread, text, plan_version?, assignment_id?}` | send on a thread (gets the `[EMBER drill]` prefix); returns `delivery`: `sent` / `failed` / `not_opted_in` / `no_phone` / `dev` |
| `POST /dev/reset` | reseed from `SEED_STATE` and broadcast `state` (rehearsals; `DEV_ENDPOINTS=0` hides it) |
| `POST /dev/inbound {role, text, household_id?, facility_id?}` | inject a message into a specific thread; role-only is rejected if ambiguous. Does not opt a real phone in. With Photon enabled, replies can still go to real phones. |

## Photon (2.0 Beta)
1. `.env`: `PHOTON_ENABLED=1`, `PHOTON_API_KEY`, `PHOTON_PROJECT_ID` (key needs project:read/write, platforms:read/write).
2. `curl -X POST localhost:8000/phones -H 'content-type: application/json' -d '{"role":"resident","handle":"4135550100"}'` (and `operator`).
3. Each tester texts anything to their `assigned_number` (Photon's opt-in rule: a shared line can't text first). `GET /phones` then shows `opted_in: true`.
4. `GET /health` → `photon_listener.socket` should be `subscribed`; if the socket is down for 5 s, the backend polls `GET /messages` every 2 s instead.

Inbound texts are deduped by Photon message id; the event cursor is saved after each handled event and survives restarts and `/dev/reset`.

## Multiple residents: setup and test

Restart the backend after updating this code. The automatic SQLite migration preserves existing
registrations and their Photon chat/opt-in credentials, binds legacy resident/operator rows to the
current judge/hospital, and removes the old one-phone-per-role constraint. No reset is needed.
Bindings are preserved across resets and restarts; bindings from another scenario are inactive
rather than silently attached to a different household. Previously replaced registrations cannot
be recovered by the migration: register those phones again against an unused household.

From the repository root, load the request helpers (bash/zsh):

```bash
source residents/scripts/requests.sh
ember_get /health
ember_get /phones
curl -sS "$EMBER_API/state" | python3 -c 'import json,sys; s=json.load(sys.stdin); print(json.dumps([{ "household_id": h["household_id"], "label": h.get("label"), "needs": h["needs"] } for h in s["households"]], indent=2))'
```

Choose **existing household IDs** from that response. Use a different real tester phone for each ID.
The example 555 numbers below are placeholders; do not register them for live testing.

```bash
ember_post /phones '{"role":"resident","handle":"+16175550101","household_id":10296}'
ember_post /phones '{"role":"resident","handle":"+16175550102","household_id":516}'
```

Each tester must text **HI to their own returned `assigned_number`**. Registration alone does not
authorize replies: `space_id` and `agent_user_id` are learned from that first received message.
`opted_in` is computed from these details; it cannot be set with a request field. Check `/phones`
until each tester shows `opted_in: true`. Re-registering the same phone/target preserves opt-in
when Photon returns the same line. A different line requires a fresh first text.

```bash
ember_get /phones
ember_post /ask '{"role":"resident","household_id":10296}'
ember_post /ask '{"role":"resident","household_id":516,"question":"How many people need pickup?"}'
```

`delivery: sent` means Photon accepted the request, not proof of delivery to the handset.
`not_opted_in` means nothing was sent: follow `action_needed`, then retry. `dev` means Photon is
disabled. `failed` means sending failed and the background retry loop will try again for up to
10 minutes. A failed message keeps the original recipient and idempotency key.

For a clean two-person rehearsal:

1. `ember_post /dev/reset` (clears run history and sends current questions/offers to opted-in phones).
2. `ember_post /clock '{"t_s":300}'`; leave dashboard playback paused.
3. Tester A texts **“2 of us, one uses a wheelchair”**; tester B texts **“3 of us need pickup”**.
4. Inspect `ember_get /state`: each inbound message and need report must carry the correct household ID.
5. Each tester replies **YES** to their own offer. Inspect `/state` for the confirmation reports and
   `/plan/{version}` for the stored `confirmed` assignments. `/plan/current` shows simulation progress,
   so an accepted assignment can appear `en_route` there. Confirmations must target their respective
   households. A repeated fact should not create another plan; a new fact should.
6. An unrelated household can also receive a changed instruction, because everyone shares one plan.

To inject sample texts instead of receiving them through Photon:

```bash
ember_post /dev/inbound '{"role":"resident","household_id":10296,"text":"2 of us, one uses a wheelchair"}'
ember_post /dev/inbound '{"role":"resident","household_id":516,"text":"3 of us need pickup"}'
```

For a test with no real phone sends, start the backend with `PHOTON_ENABLED=0`. Injections still use
the real extraction API if enabled. For automated tests with fake Photon and fake extraction:

```bash
cd residents
uv run pytest -q tests/test_multi_household.py
uv run pytest -q
```

**Engine mode (default):** `SCENARIO` (default `scenarios/allston_flood_v1/scenario.json`) → plan v1 by the
allocator at startup (~2 s), state = `simulate(plan, reports).state_at(clock)`. The DB is kept across
restarts (a crash mid-demo keeps plans, reports, messages); it re-plans from scratch when `SCENARIO`
changes, on `RESET_ON_START=1`, or `POST /dev/reset`. All engine calls go through `residents/engine_bridge.py` → `ember_engine.api.EngineSession`, resumed from the DB before every call.
**Static mode:** `SCENARIO=` (empty) serves `SEED_STATE` (the state fixture) as-is; engine endpoints return 503.

Check the live output against the contract:
```bash
curl -s localhost:8000/state > /tmp/state.json
uv run --project ../engine ember validate-state /tmp/state.json --scenario ../contracts/fixtures/scenario.fixture.json
```

## The one LLM call (text → report)
`residents/extract.py`: each inbound text (Photon or `/dev/inbound`) → Claude (`EXTRACT_MODEL`, default `claude-opus-5-5`, effort `low`, structured outputs) → `facts[]` + confidence + optional clarifying question. Everything after is code: confidence < 0.6 or a missing head count / unplaceable street → one clarifying question (a partial need waits in `pending` for the reply); street names → town edges near the household (`engine_bridge.resolve_road`, both directions); minutes → `backup_endurance_s`. All facts from one text → one replan. The model never sees or emits routes, times or assignments.
Live accuracy: `uv run python scripts/eval_extract.py` on `tests/samples.json` (20 messages; last run 20/20, median 1.9 s). Unit tests use a fake model and never call the API.

## Outbound instructions
After every plan version (`residents/outbound.py`), each opted-in phone thread is compared with the last instruction actually texted to it: a text goes out only if a vehicle is newly assigned / replaced, is no longer coming, or the ETA moved ≥ 10 min. Fixed templates over computed fields, `[EMBER drill]` prefix, `plan_version` + `assignment_id` on every message; the assignment becomes `offered` (WS `assignment` with `change: status_changed`). The plan's `info_requests` for a phone thread are asked once each (e.g. right after the tester's first "hi").

## Robustness
- Inbound texts are processed one at a time end to end (the next text sees the previous one's needs and plan); Photon deliveries are deduped by message id across socket, redelivery and polling.
- A double-sent fact (same kind, target and payload as that thread's previous report) is answered with the person's status, not a second replan.
- If the planner throws, the report is kept (unresolved), the person is told a coordinator is looking at it, and the server keeps serving; the next replan uses the report.
- Failed outbound sends (Photon down) are retried every `RETRY_EVERY_S` (20 s) for up to 10 minutes with the same Idempotency-Key, so a retry can never double-text.
- Street names in texts resolve to that street within 150 m of the household (engine's `edges_by_name`, same as the tested demo beat) or at a named cross street, both directions; wider would close whole streets and can cut a household off.

## Confirm / reject
A "yes"/"no" text is extracted as `confirm`/`reject` for the last instruction texted on that thread, carrying the plan version it answered. If the plan moved on and that assignment changed (gone / other vehicle / other target), nothing is applied and the latest instruction is re-sent. Confirm → `confirmed` on the stored raw plan (the allocator keeps confirmed work across replans) + ack text; a later material change to it is texted as "Update: …" without asking again. Reject → `rejected` + ack + replan; the backend never re-offers that vehicle to that thread and keeps re-proposed copies `rejected` (engine doesn't exclude declined pairs yet).

## WS events (`contracts/ws-events.schema.json`)
`state` (full snapshot) · `plan` (a new plan version) · `assignment` (`{plan_version, change, assignment_id, assignment}`, one per changed assignment) · `message` · `report` · `metrics` · `scatter_point`.
`seq` goes up by 1 per broadcast; on a gap, re-fetch `GET /state`.
