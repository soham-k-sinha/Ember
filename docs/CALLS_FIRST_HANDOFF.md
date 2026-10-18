# Calls-first takeover — 2026-10-18

Branch: `codex/call-first-takeover`, based on main `c0ca991` (PRs #54 and #55 included).
Worktree: `/Users/aryamangoenka/Ember/.claude/worktrees/codex-call-first`.

The user asked Codex to take over while Claude was rate-limited, then explicitly selected **Finish and test calls-first**.
The source was the uncommitted `aryaman/call-first` worktree at `wf_f716c14f-6a8-1` (base `6527ff7`). Its changes were
preserved as `/private/tmp/ember-call-first-takeover/call-first.patch` and applied onto current main. The original
worktrees and main were left untouched. Compatible question/fixture wording from `aryaman/proactive-voice` was
incorporated without replacing main's denser traffic playback. D99 was already the merged traffic decision, so the
calls-first decision is **D100**, followed by the delivery fixes in **D101**.

## Current behavior

- A player registers on the web and texts the returned iMessage line; EMBER calls with its simulation notice,
  location/flood timing, and one combined head-count, mobility and medical-needs question.
- Unknown incoming callers become players and are placed immediately. Their first answer is processed, including
  needs supplied before the introduction; they do not have to repeat it.
- Pickup instructions, material pickup changes and the two-minute arrival warning are calls. The queue prioritizes
  flood deadlines, with three concurrent calls by default. An active text conversation is answered by text.
- Instructions proceed without required YES/DONE replies. Delivered instructions become confirmed; later guidance
  follows the simulator clock. Repeated/revised speech turns are serialized and do not skip steps or double-decline.
- An answered call gets a written follow-up when the phone has opted into its iMessage chat. A voice-only caller
  is told to send JOIN EMBER to their assigned line to enable it. A missed call gets one retry after two simulation minutes or 60 wall
  seconds, then a text. The five-second poll works even with the simulation clock paused.
- First text/call carries the simulation disclosure; later messages use the plan's wording. No official authority
  is claimed. The medical-needs question and facility names agree across the engine, fixtures, seed and backend.

## Additional defects reproduced and fixed

Six regression tests were added. Five exposed failures in the unfinished implementation; the sixth verifies that a
missed-call retry works with a paused clock:

1. Concurrent plan/poll hooks could dial the same queued phone twice. Checks and dial requests are serialized;
   repeated requests for an active call reuse it.
2. A replan arriving during the outbound provider request could lose its message when the opening cleared the
   entire outbox. Only the messages included in the opening are removed.
3. A new caller's first needs were discarded during onboarding. They now enter the normal intake pipeline, and an
   already answered onboarding question is omitted from the speech reply.
4. Idle calls disappeared without a follow-up when provider status was unavailable. The asynchronous reaper now
   completes their follow-up/retry path.
5. Calls waiting for a free line could say an obsolete "two minutes away" warning after the van arrived. Openings
   refresh from the current plan and clock before dialing.

## Verification

- Residents: **307 passed** (full suite); focused voice/outbound/WS checks also run after fixture wording updates.
- Engine: **106 passed**; `ember smoke` passed.
- Web: production build and WS, closures, crowd and traffic checks passed.
- HTTP/WebSocket demo: **74/74**, `engine/scripts/e2e.py --skip-optimize`, using a temporary DB and a keyless local
  backend on port 8067. Covers judge rescue, decline/confirmation, road closure, hospital/sewage trade-off, both
  playbacks, end-of-horizon state, three joins and the player cap.
- `residents/scripts/sim_calls.py` completed the five-person scenario with mocked ElevenLabs and the keyword parser;
  transcripts regenerated in `docs/voice_transcripts.md`, complete console log in
  `/private/tmp/ember-call-first-takeover/sim-calls.log`.
- Ruff and `git diff --check` passed. Contract shape unchanged; the state schema edit only corrects its prose.
- Snapshot hash remains **ember-engine-d9ea4508c1**; no sandbox snapshot rebuild is needed for these changes.

No real phones were called or texted, no provider settings changed, and no paid model/Daytona runs were started.
The earlier main-branch 83/83 real-Daytona result is historical, not a result of this takeover.

## Next live checks

Additional reliability and UI work after the initial calls-first commit is recorded in
[POLISH_QA.md](POLISH_QA.md): scoped negative needs, unclear assistance, honest urgency scoring, clock-safe
optimization, district-load recovery and a phone layout that keeps the join form accessible.

1. Rehearse one opted-in iPhone: register → text → first-contact call → spoken needs → computed instruction →
   follow-up text → clock-driven arrival call. Also test a missed call and retry with the clock paused.
2. Verify ElevenLabs call-ended status and first-message override against the real API. Incoming callers need an
   opted-in iMessage chat for Photon to deliver the written follow-up; voice admission alone does not establish it.
3. Rerun the paid extraction eval with the urgent/medical wording if desired; it was not rerun here.
4. Use `docs/QA.md` on the visible demo machine; projector FPS, real-player labels and unused Photon-seat release
   still need the live checks already listed in the main handoff.

To resume, work in this worktree. Keep real-phone services off during automated runs:

```bash
cd /Users/aryamangoenka/Ember/.claude/worktrees/codex-call-first/residents
EMBER_LOCAL_POOL=1 GEOCODE=0 PHOTON_ENABLED=0 EXTRACT_ENABLED=0 REPLY_ENABLED=0 \
  ANTHROPIC_API_KEY= ELEVENLABS_API_KEY= CHALK_ROUTER_KEY= uv run pytest -q
```
