# Soham — backend, shared state, Photon, LLM extraction (`residents/`)

Paste this file into your Claude session (or: "read docs/team/soham.md and follow it").

## Context in five lines
- EMBER: disaster coordination for an urban flood in one district around the Treehouse. One shared state, an allocator + simulator producing one coordinated plan and a personal instruction per household, people in the loop over Photon, robustness on Daytona, sustainability = m³ of wastewater kept out of the Charles. Spec: `docs/TECHNICAL.md` (read §0–§2, §4, §7–§11).
- You own the backend: the shared-state DB, the HTTP/WS API the web uses, the Photon threads (resident, operator), the **only LLM call in the system** (free text → structured report), plan versioning, and the replan loop that calls Aryaman's `engine` functions.
- The judge moment runs through you: judge texts → extraction → report row → `replan` → new plan version → only the changed instructions go out, each tagged with its `plan_version`.
- Photon facts (verified, plan doc §6.6): use **Beta / Photon 2.0** (`api.photon.codes/v1`, `pip install photonhq-api`, $100 free credit; the `HACKWITHPHOTON` code is for the old API, fallback only). Shared iMessage lines: the tester must text first, no group chats, no calls. Inbound via Socket.IO `message.received`; outbound `POST /messages` with an `Idempotency-Key`. Voice needs a bought SMS number + a SIP vendor: stretch only.
- Safety: every message starts with "[EMBER drill]"; nobody is auto-assigned to help a stranger; offers stay provisional until confirmed.

## Setup (once)
```bash
git clone https://github.com/arnav-k-sinha/Ember.git && cd Ember
git checkout main && git pull && git checkout -b soham/<topic>
cd residents && uv init --python 3.12 && uv add fastapi uvicorn httpx python-socketio[client] pydantic sqlalchemy anthropic
uv add --editable ../engine          # import ember_engine
cp .env.example .env                 # PHOTON_API_KEY, PHOTON_PROJECT_ID, ANTHROPIC_API_KEY (never commit)
uv run uvicorn residents.app:app --reload
```
Photon: project + key with `project:read/write, platforms:read/write`; assign two team phones (`POST /platforms/imessage/assignments {handle}`), have each text "hi" to its assigned number, confirm a `message.received` event arrives.

## Tasks, in order (acceptance in brackets)
1. **Skeleton + DB** [FastAPI app; SQLite tables from `docs/TECHNICAL.md` §2; `GET /state` serves `contracts/fixtures/state.fixture.json` loaded into the DB; `WS /ws` broadcasts a `state` event on connect].
2. **Photon plumbing** [two assignments; Socket.IO listener logs inbound; `send_message(thread, text, plan_version)` works; messages stored].
3. **LLM extraction** [`extract(text, role, record) → report JSON` per §4 schema using tool-use/structured output; a test set of 20 sample resident/operator messages in `residents/tests/samples.json` with expected `kind`; accuracy printed; low confidence → one clarifying question, never a guess].
4. **Reports + replan loop** [`POST /reports` writes a row and calls `ember_engine.allocator.replan(state, report)`; new plan version stored; assignment diff computed; only changed instructions sent; WS emits `plan`, `assignment`, `message`]. Until Aryaman's `replan` exists, call a stub that returns the fixture plan with one assignment changed, so the loop is testable end to end.
5. **Confirm / reject** [`POST /assignments/{id}/confirm|reject`; reject triggers replan; stale `plan_version` replies trigger a replan check instead of being applied blindly].
6. **Operator thread** [scripted prompts fired from the plan's `info_requests[]` ("What's your backup endurance now?"); replies become `facility_status` reports].
7. **Disruption + simulate + comparison endpoints** [`POST /disruption` (close edge / set facility field), `POST /simulate`, `GET /comparison`, forwarding `scatter_point` events from the Daytona runner].
8. Robustness: duplicate reports, two replies in a row, replies to old versions, Photon outage → polling fallback.
9. (Stretch, only if green-lit at the SpaceXAI workshop Sat 13:30) voice line via Photon SMS number + SIP vendor + Grok Voice; tools `get_assignment`, `record_report`.

## Interfaces you consume / produce
Consume: `state`, `assignment`, `report`, `comparison`, `scenario` schemas + fixtures; `ember_engine.allocator.replan`, `.simulate`, `.compare` (Aryaman). Produce: the HTTP/WS API (`contracts/ws-events.schema.json` is yours to draft with Aryaman) and `residents/tests/samples.json`.

## Git and logging (non-negotiable)
Branch per feature from `main`; `git add residents docs/log/soham.md`; rebase on `origin/main` before every push; PR; self-merge when only `residents/` + your log changed and `pytest` passes. After every feature: append to `docs/log/soham.md`. At session start: read `docs/log/*.md` and `docs/DECISIONS.md`. Never commit `.env`.

## Your Claude's opening prompt
```
Read CLAUDE.md, docs/TECHNICAL.md (§0–§2, §4, §7–§11), docs/team/soham.md, docs/DECISIONS.md and all of docs/log/*.md. You own residents/ only. Work through docs/team/soham.md tasks in order; use the fixtures in contracts/ and a stub replan until engine's replan lands. The LLM is used in exactly one place: turning a message into a structured report; it never produces routes, times or assignments. Every outbound message carries plan_version and starts with "[EMBER drill]". After each task: `uv run pytest -q`, append an entry to docs/log/soham.md, commit, rebase on origin/main, push, open a PR. Never commit secrets.
```

## Cut lines
Operator thread → scripted via the UI. Voice → cut. Email channel → skip.
