# Product polish verification — 2026-10-18

Local work on `codex/call-first-takeover`, following the calls-first integration. Automated runs disable Photon,
ElevenLabs and model credentials and use temporary SQLite databases. Original worktrees and main remain unchanged.

## Intake and call delivery

- Negative answers can clear a known need: no wheelchair, no accessible vehicle, nobody hurt, no help walking.
- Negation ends with its phrase. “No wheelchair, I need oxygen” retains the medical need.
- “Nobody needs help” is not urgent; “no help has arrived, please hurry” is urgent and never a declined pickup.
- Water coming in under the door is urgent even when followed by a question.
- An unrecognized request for assistance is clarified before publishing a pickup from the head count alone.
  Clear urgency still reaches intake. This may require the caller to repeat the head count.
- A voice-only caller without an opted-in Photon chat is told how to enable the written copy; the call no longer
  promises an undeliverable text. Local mode retains the transcript behavior used by the test harness.

The expanded fallback eval (`scripts/eval_sim.py --extractor fallback --moves 10`) has **50 passes, 6 clarifications,
0 failures**, and **56/56 urgency matches**. The scoring now distinguishes clarification from a harmful partial
report and checks urgency even when physical metrics are identical. This is a development eval with a ten-move
search budget, not a paid-model rerun or a production safety guarantee. Historical 51-message results are separate.

## Operator behavior and browser checks

- Optimization pauses and synchronizes the playhead. Play and scrub stay disabled until completion; transient poll
  failures retry within the existing five-minute limit.
- The backend rejects results computed at an obsolete clock time, preserving the current clock and plan.
- Edge browser check: started playback, ran the 250-world local batch, saw the paused/disabled controls, then plan v2
  and re-enabled controls at the same paused time (~6 s). The worker pool reported 8 workers and 2.3 s fan-out.
- Temporarily withheld the district JSON in the isolated worktree: verified the failure message, restored the asset,
  and retried successfully without a reload. Also verified the flat-map fallback and return to the district view.
- At a 390×844 viewport, the join form and a two-column scorecard precede the map. They no longer obscure it.
  Important map labels wrap to the viewport width; the latest-change banner leaves room for camera controls.
- Loading has a visible status, failed fetches leave the cache retryable, and district requests time out after 20 s.
- The web behavioral checks now run in CI alongside the production build.

Verification: **330 residents tests passed** in the full suite; **56 fallback/conversation tests passed** after
the final explicit-refusal cases were added. Production web build, WS/closures/crowd/traffic checks, Ruff and
`git diff --check` passed. The engine was unchanged in this checkpoint; its 106-test result is in the initial handoff.

Live iPhone/ElevenLabs behavior, projector performance, and paid-model accuracy still require the live checks in
[CALLS_FIRST_HANDOFF.md](CALLS_FIRST_HANDOFF.md). Browser frame rates vary under test load; no new universal FPS
claim is made here.
