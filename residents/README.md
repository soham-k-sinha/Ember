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

## The drill: a whole run on real phones, one process (D56)

```bash
cd residents && uv sync
uv run ember-drill --resident 6175550101                     # your phone is a resident (real texts via Photon)
uv run ember-drill --resident 6175550101 --resident 6175550102 --operator 6175550103@mt-auburn
uv run ember-drill --dry                                     # no phones, nothing sent: type texts as @r1 …
uv run ember-drill --crowded …                               # also the scenario's 40 synthetic households compete (default: only you)
```
Put real numbers in `residents/.env` instead of the command line if you like (`DRILL_RESIDENTS=…,…`,
`DRILL_OPERATORS=PHONE@mt-auburn`); never commit them. One process runs the backend (planner, Photon listener,
HTTP/WS on :8000 so the web map can watch), starts the run from scratch (`--keep` continues the last one; its
own DB `residents/drill.db`, log `residents/drill.log`), registers the phones and prints every text in and out.
It refuses to start while another EMBER backend with Photon on is running (both would answer every text).

What happens, all by text:
1. **Text HI** to the number the console prints (Photon only lets EMBER reply after you text first).
2. EMBER asks **where you are**. Reply with an address ("125 Western Ave"), an intersection ("Putnam Ave and
   Western Ave"), a landmark, or a maps link / coordinates. It's placed on the engine's map: coordinates →
   street intersection in town.json → OSM Nominatim (bounded to the town). The nearest building nobody else has
   becomes your household; you're told your pickup corner and when the water reaches your street (or that it
   doesn't: then the plan says shelter in place). The console lists flood-zone corners to try.
3. The **plan asks** its question ("How many people are with you, and does anyone need a wheelchair-accessible
   vehicle?"). Answer in your own words; it replans and **offers** a vehicle: who, where, when, drop-off, and
   how long you have.
4. Reply **YES**. From then on one text per step, each computed from the plan's simulation (never the LLM):
   *Step 1* get ready and walk to the pickup corner (distance, direction, minutes on foot), or stay inside if
   someone needs help to walk (the crew comes to the door) → *Step 2* the vehicle is at the corner, board →
   *Step 3* on the way to the drop-off → *Step 4* checked in. Reply **DONE** after each ("we're at the corner"
   works too). Operators get the generator version: meet the crew → connecting → powered.
5. **The clock moves one step at a time:** when everyone EMBER is waiting on has replied DONE, the sim clock
   jumps to the next event (the vehicle arriving, the pickup, the drop-off). `--manual-clock` turns that off.

Ask anything; every question is answered from the plan (D60): "what's the plan?" / "what do I do?" (where you
stand, the step you're on, what we still need from you), "how long?", "where do we go?", "are there other vans?",
"is anyone near me?", "what should we bring?", "where is the flood?", "is River St open?", "is it safe to drive?"
(fixed safety wording, starting with 911). Something the plan doesn't cover ("can I bring my cat?") gets your
situation too and goes to the coordinators' queue: the console prints it, `tell r1 <text>` answers it. Offers say
why you got that vehicle and who is picked up before you. Saying NO to the only vehicle that can take you asks you to confirm first.
Anything else you text goes through the same path as always: "my dad uses a wheelchair" or "the corner is
flooded" → replan → changed instruction; "NO" → another vehicle.
Console: `status`, `next` (jump to the next step), `+10` (minutes), `@r1 <text>` (text as r1), `close <street>
and <cross street>`, `plan`, `questions`, `tell r1 <text>` (reply as the coordinator), `reset`, `quit`.

API for the same flow: `POST /phones {role: "resident", handle, locate: true}` registers a phone with no household;
`POST /dev/inbound {role, handle, text}` texts as that phone (also before it's placed).

## The AI talks, the planner decides (D76)
Claude Sonnet 5.5 reads each text or spoken turn with the conversation so far and turns it into facts (needs, location,
yes/no, done, questions); the planner and the guide compute everything that follows, exactly as before. The person
then gets **one** reply per turn, written by Claude Haiku 5.5 from those computed messages ("I'm sorry about your leg.
Accessible Van 3 will pick you up at your door in about 3 min…"). A guard sends the computed messages instead if the
reply mentions any number, vehicle, place or street they don't, drops a YES/DONE ask or a question, or makes a safety
claim. `REPLY_ENABLED=0` turns the rewriting off.

## Calls: the same conversation by phone (D74)
ElevenLabs runs the call on the Photon SMS number (speech, voice, turn-taking); **EMBER's backend is the agent's
Custom LLM**, so the call says exactly what the thread would text (`residents/speech.py` makes it sound right:
"Say yes", "Avenue", "9 1 1"). What the caller says goes through the same path as a text; the call and the texts are
one thread.

One-time: Photon number → ElevenLabs (inbound + outbound) as in Photon's voice guide, then in `residents/.env`:
`PHOTON_VOICE_NUMBER`, `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_PHONE_NUMBER_ID` (see `.env.example`).
In ElevenLabs → the agent → Security, allow overriding the **first message** (outbound calls open with the plan).

```bash
uv run ember-drill --voice --caller +1617…="Putnam Ave and Western Ave"     # EMBER calls them if the flood reaches it
uv run ember-drill --voice --resident +1617…                               # take calls on the Photon number
uv run ember-drill --dry --caller 6175550101="Putnam Ave and Western Ave"   # pretend call: type what they say with @r1
```
`--voice` starts the voice app on `VOICE_PORT` (8100), a cloudflared quick tunnel to it (only that endpoint is
public, behind a random path), and points the ElevenLabs agent at it (Custom LLM URL + the system prompt that names
the caller). It prints what to paste if it can't. Give the new tunnel about a minute before the first call.
Console: `call r1`, `calls`. API: `POST /calls {handle}`, `GET /calls`.

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
| `GET /playback?which=ember\|baseline` | the current plan or the baseline on the same reports, simulated over the whole horizon (`playback.schema.json`) for the map's replay; cached per plan version and report count (~4 s first call) |
| `POST /assignments/{id}/confirm`, `/reject` `{plan_version?}` | the person accepts / declines an offer (texts "yes"/"no" take the same path). Reject → replan; that vehicle is never re-offered to them. 409 if `plan_version` is older and the assignment changed since (stale) |
| `GET /phones`, `POST /phones {role, handle, household_id?, facility_id?}` | one phone per household/facility, many residents/operators. Residents specify household_id, operators facility_id. Omission uses the original judge/hospital default. Occupied target or a phone bound elsewhere → 409; never silently replaces a registration. Returns thread, assigned_number, opted_in and action_needed. `locate: true` (resident, no household_id): the phone gets a household when it texts where it is (D56). Each item also has `household_id` and `player` (join order of drill players, else null). |
| `POST /messages {thread, text, plan_version?, assignment_id?}` | send on a thread (gets the `[EMBER drill]` prefix); returns `delivery`: `sent` / `failed` / `not_opted_in` / `no_phone` / `dev` |
| `GET /questions?open_only=` | questions the plan couldn't answer (D60): `{report_id, thread, handle, text, t_s, answer}`; each person already got their situation |
| `POST /questions/{report_id}/answer {text}` | a coordinator's reply, texted on that thread as written (drill prefix); marks it answered. 404 if not in this run |
| `POST /dev/reset` | reseed from `SEED_STATE` and broadcast `state` (rehearsals; `DEV_ENDPOINTS=0` hides it) |
| `POST /dev/inbound {role, text, household_id?, facility_id?, handle?}` | inject a message into a specific thread (or as a registered phone, `handle`, also before it has a household); role-only is rejected if ambiguous. Does not opt a real phone in. With Photon enabled, replies can still go to real phones. |

## Photon (2.0 Beta)
1. `.env`: `PHOTON_ENABLED=1`, `PHOTON_API_KEY`, `PHOTON_PROJECT_ID` (key needs project:read/write, platforms:read/write).
2. `curl -X POST localhost:8000/phones -H 'content-type: application/json' -d '{"role":"resident","handle":"4135550100"}'` (and `operator`).
3. Each tester texts anything to their `assigned_number` (Photon's opt-in rule: a shared line can't text first). `GET /phones` then shows `opted_in: true`.
4. `GET /health` → `photon_listener.socket` should be `subscribed`; if the socket is down for 5 s, the backend polls `GET /messages` every 2 s instead.

**Join by QR (D78):** a phone we don't know that texts "JOIN EMBER" to `JOIN_NUMBER` (default `PHOTON_VOICE_NUMBER`,
the SMS number: a shared iMessage line only delivers assigned handles) becomes Player N, up to `MAX_PLAYERS` (30), on a
free building in the forecast flood that we choose; the plan then asks its own question. Over the cap: "the drill is
full". `/dev/reset` places players again. Replies on the SMS number need the line's SMS campaign (Photon).

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
