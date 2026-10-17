# Voice channel plan: EMBER calls residents in the flood zone

Status: **superseded in part (D61):** built with **ElevenLabs** as the call runtime (Soham's choice) and EMBER as its Custom LLM, not LiveKit; see residents README "Calls" and `residents/voice.py`. The rest (parity rule, who gets called, failure modes) still holds. Originally: plan only. Written 2026-10-17 after D60. The voice decision will be D61 (open
question on the D-list: "voice line"). Owner: Soham's lane (`residents/`). No engine, contract or web change is
required. One optional contract ask is in §9.

## 0. The goal, and the one rule that makes it achievable
**Goal.** Every drill resident whose household is in the forecast flood area gets a **phone call** from EMBER, and the
call does exactly what the text thread does today:
1. where are you
2. the plan's question
3. the offer
4. YES
5. one step at a time with DONE
6. questions answered from the plan (D60)
7. changes as the plan moves

**The rule:** voice is a **transport**, not a second brain. The conversation stays where it is (`Locator`,
`Intake`, `Guide`, `Outbound`, `Briefing`):
- What the person says on the call is turned into text (speech-to-text) and enters through the **same function** as a
  typed or texted message (`Messenger.phone_inbound`).
- Everything EMBER would text is **spoken** instead while a call is live: the same `send_message`, with the
  routing changed.
- Nothing on the call is generated:
  - no LLM writes a sentence, as hard rule 2 and D46 require;
  - the one LLM call (extraction) is unchanged;
  - a deterministic `speech.py` turns each text into something that sounds right ("Reply YES" → "Say yes", "Ave" →
    "Avenue", "911" → "nine one one").

The payoff is parity by construction, and it can be tested (§7). The rejected alternative was a hosted "voice
agent" (ElevenLabs / Retell / a realtime speech-to-speech model like Grok Voice) that converses on its own, with
our backend as its tools:
- it would generate its own words (breaks D46: "you're safe, stay put" from a model is the failure we can't have);
- its conversation state would drift from the text thread's, so the two workflows would differ by design;
- it can't be pinned by our transcript tests.

## 1. What Photon gives us (verified against api.photon.codes/openapi.json and photon.codes/docs/beta, 2026-10-17)
- **Shared iMessage lines can't take calls.** The docs say "Shared lines cannot take calls" and "Shared iMessage
  assignments do not support Voice". So our current line (shared iMessage) stays text-only, which is hard rule 9.
- **Voice needs an eligible number.** That is an SMS number bought through Photon (`POST
  /v1/projects/{id}/platforms/sms/numbers {countryCode: "US", areaCode}` → a 202 operation), or a dedicated
  iMessage/WhatsApp line.
- **Photon is a SIP trunk only.** There is no speech-to-text, text-to-speech or agent:
  - **Voice profile** (`PUT …/platforms/voice/profiles/default`, protocol `sip`), assigned to the line.
  - **Inbound:** `PUT …/voice/profiles/{id}/inbound {destinationUri, credentials, expectedVersion}`. Photon forwards
    calls to our SIP destination.
  - **Outbound:** `PUT …/voice/profiles/{id}/outbound {authentication: {algorithm: "SHA-256"}, expectedVersion}`.
    This returns a SIP username and a password **shown once**, and a connection such as `sip.photon.codes:5061` (TLS).
  - **Billing:** "Outbound calls are paid usage, so the organization needs a payment method …; otherwise this
    returns 402 ENTITLEMENT_REQUIRED". The number has a cost too. The plan doc's figure is voice at $0.013/min US.
  - **Events:** webhook types `call.started / ringing / answered / connected / ended / dtmf.received` exist.
- **Our project today** (read-only check, 2026-10-17): `platforms/resources` = **[]** and `voice/profiles` = **[]**.
  There is no number and no profile yet.

## 2. The runtime: LiveKit (recommended), and why
Photon's cookbooks cover LiveKit, Twilio, Retell and ElevenLabs. **LiveKit Cloud + LiveKit Agents (Python)**:
- **Network:** the worker runs on the laptop and dials *out* to LiveKit Cloud, so there's **no public URL or tunnel**
  on hackathon wifi. Our backend stays on localhost.
- **No LLM:** we override the agent's reply step and supply our own text. LiveKit documents overriding `llm_node`
  with canned replies, and `session.say()` for pushed speech.
- **Call handling:** outbound calls are `CreateSIPParticipant(sip_trunk_id, sip_call_to, room_name,
  wait_until_answered=True)`. Errors come back as `SipCallError` with SIP codes: 486/603 busy or declined, 408/480 no
  answer. Answering-machine detection exists. Hang-up is `delete_room()`. Krisp noise cancellation helps in a loud
  venue.
- **Free "Build" plan, no card:**
  - 1,000 agent minutes and 1,000 third-party SIP minutes
  - $2.50 of LiveKit Inference (speech-to-text + text-to-speech; about 50 minutes)
  - 5 concurrent sessions
- **Python:** `livekit-agents` supports 3.10–3.14, and we're on 3.13. **Pin versions that are at least 2 weeks old**:
  `livekit-agents==1.8.4` (2026-10-01) and its plugins at the same version, `livekit-api==1.2.1` (2026-08-27). Not
  1.8.8 (2 days old) and not 2.0.0b1.
- **Speech-to-text:** Deepgram (nova-3 class) with **key terms** = the town's street names from `Gazetteer.streets`,
  plus "EMBER", "wheelchair", "accessible". "Putnam Avenue" and "Memorial Drive" have to come through right, or
  location fails. Smart formatting turns "one twenty five western avenue" into "125 Western Avenue".
- **Text-to-speech:** any natural voice (Cartesia / ElevenLabs / Deepgram Aura through Inference). If the team wants
  the SpaceXAI track (D9: "only if voice ships"), xAI's TTS through `livekit-plugins-xai` is a drop-in swap. TTS
  only, no Grok-generated words.

## 3. Architecture
```
phone ⇄ PSTN ⇄ Photon number (SIP, TLS) ⇄ LiveKit Cloud (one room per call)
                                              ⇅ (worker dials out over WSS)
                         ember-voice worker (residents/residents/voice/agent.py, separate process)
                           speech-to-text → "heard" text ─┐   ┌─ "say" text → speech.render → text-to-speech
                                                          ▼   │
                     backend :8000  WS /voice/calls/{call_id}/ws   (one socket per live call)
                       CallManager ── Messenger.phone_inbound(handle, text, channel="voice")  ← same as a text
                                  └── Messenger.send_message(...) → live call? speak it : Photon text  ← same callers
                       Locator · Intake (one LLM call) · Planner · Outbound · Guide · Briefing   ← unchanged
```
New code, all in `residents/`:

| File | Role |
|---|---|
| `residents/voice/speech.py` | Pure functions. `render(text)`: strip `[EMBER drill]` and `(plan vN)`, "Reply YES/NO/DONE" → "Say yes/no/done", "text you" → "call you", "reply here" → "tell me", street suffixes (St/Ave/Rd/Dr/Pl/N/S…; reuse `engine_bridge._ABBREV`), "min" → "minutes", "m" → "meters", "#10296" → "household 10296", "911" → "nine one one", semicolons → pauses. Also the call frames: `OPENER` (disclosure), `STILL_THERE`, `DIDNT_CATCH`, `CALL_BACK`, `GOODBYE`. |
| `residents/voice/calls.py` | `CallManager`: who to call and when (§4), the call state machine (`dialing → ringing → live → ended(reason)`), retries, a concurrency cap, and the `calls` table. It talks to a `CallProvider` interface (`dial(handle, call_id)`, `hangup(call_id)`). `LiveKitProvider` is the real one; `FakeCallProvider` is for tests and `--dry`. |
| `residents/voice/agent.py` | The LiveKit worker (`uv run ember-voice`, also started by `ember-drill --voice`). Joins the call's room and runs voice activity detection, turn detection, speech-to-text and text-to-speech. Bridges to the backend socket: sends `heard {utt_id, text, confidence}`, receives `say {id, text, interruptible}` and `hangup`, acks `spoken {id}`. Thin; all logic is in a LiveKit-free `CallBridge` class so tests don't need LiveKit. |
| `residents/voice/setup.py` | `uv run ember-voice-setup`: one-time provisioning (§6). Dry by default; `--buy` / `--apply` are needed to spend money or change config. Prints what it will do first. |
| `messaging.py` (edit) | Channel routing: `send_message` / `send_to_phone` check `CallManager.live(handle)`. If a call is live, queue the text on the call (delivery `voice`) instead of Photon. `phone_inbound(handle, text, channel=…)` stores inbound with its channel. New DB column `messages.channel` (`imessage` / `voice`, migration like `recipient_handle`). |
| `db.py` (edit) | `calls` table (call_id, handle, thread_key, reason, state, attempts, started/answered/ended wall + sim t, end reason). Phones gain `voice` (consent) and `prefer` (`text` / `voice`). `clear_scenario()` ends live calls and clears `calls` (new kv prefixes, if any, go in its list too). |
| `app.py` (edit) | `GET /calls`, `POST /calls {handle}` (call now), `POST /calls/{id}/hangup`, `WS /voice/calls/{id}/ws`. `POST /phones` gains `voice: bool` and `prefer`. |
| `drill.py` (edit) | `--caller <phone>[=<address>]` registers a resident who is **called**; the optional address is where they live. `--voice` starts the worker. Console: `call r1`, `hangup r1`, `calls`. With `--dry` the call is simulated: `@r1 …` lines are what r1 *says*, and spoken lines print as `EMBER (call) → r1:`. |

## 4. Who gets called, and when ("whoever's in the critical area")
- **Only consenting drill participants.** Only phones registered with `voice: true` are called: `--caller` on the
  drill command line, or `POST /phones {voice: true}`. Synthetic households have no phones. **No surprise calls.** This
  is the same rule as for texts (never contact a real phone outside a run Soham starts).
- **Critical area = the plan's own definition.** The household's `deadline_s` is not None, i.e. the forecast flood
  reaches its node. This is the same test the planner uses and that `locate.py` texts.
- **We need to know where they are to know they're critical:**
  - **(a) Registered address (Reverse-911 / CodeRED model).** `--caller +1617…="Putnam Ave and Western Ave"`. At run
    start the address is placed with the existing `Gazetteer.locate` + `Locator.place`, and EMBER calls only if the
    household is critical. People outside the flood get no call. If they're opted in on iMessage, they get the
    existing "outside the forecast flood area" text.
  - **(b) No address given.** We can't know, so we call and ask where they are: the lobby flow, spoken.
- **Triggers** (all through `CallManager.want_call(handle, reason)`):
  1. **Run start / reset:** every critical voice phone.
  2. **Plan hook:** something would be **texted** to a voice-preferring phone with no live call, i.e. a new or
     changed instruction (D44 material change), "no longer coming", or a guide step coming due. Instead of the text,
     EMBER calls; the call opens with the **fresh** situation (`Outbound.situation`), never a backlog of old texts.
  3. **A step waiting for DONE after they hung up:** call back after `VOICE_CALLBACK_S` (default 120 s): "Are you
     ready? Say done when you are."
- **Retries.** No answer, busy or voicemail → retry after 2, then 4 min, at most 3 attempts per trigger. Then the
  phone is marked `unreachable`; the console and `GET /calls` show it, and it falls back to iMessage if opted in.
- **Rate limits.** At most 1 live call per phone, at most `VOICE_MAX_CONCURRENT` (4; LiveKit free = 5), queued
  **earliest deadline first**, the same priority the planner uses. No re-call within 5 min of a finished call unless
  the instruction changed materially.
- **Restart-safe.** The `calls` table is the source of truth: a restart never redials a finished call, and live calls
  found at startup are marked `ended(backend_restart)` and re-queued per the triggers.

## 5. The call, line by line (the text flow, spoken)

| Text workflow today | On the call |
|---|---|
| (iMessage needs them to text HI first) | Not needed: we call them. They must allow calls from the EMBER number (iOS "Silence Unknown Callers": the console tells testers to save the number). |
| `[EMBER drill]` prefix on every text | **Opener, once per call, not interruptible:** "Hello, this is EMBER, an automated flood drill. This is only a drill." Then the content. |
| WELCOME / ASK (lobby) | "Where are you right now? Say your street address or the nearest intersection." |
| PLACED: "Got it: we have you at …" | Same sentence, spoken. **New for voice (also helps text): a correction.** "No, I'm at …" right after placement re-places them (today a location fact from a placed phone is ignored; speech-to-text errors make this essential). |
| The plan's question | Spoken; their spoken answer → extraction → replan, exactly like a text. |
| Offer (who, where, when, why, who's ahead) + "Reply YES" | Spoken, ending "Say yes to confirm, or tell me what changed." |
| YES / NO (LLM extraction, D45/D57 checks) | Same path; the same "only vehicle" double-check on a NO. |
| Step texts + "Reply DONE" | Spoken. "Say done when you're there. You can stay on the line, or hang up and we'll call you back." `STEP_DONE` (no LLM) works on the transcript. |
| Clock moves → next step texted | Spoken on the live call, or a call is placed (trigger 2). |
| Step 4 "checked in" (no DONE wanted) | Spoken, then GOODBYE, then hang up after playout. |
| Any question (D60) | The same computed answers, spoken. "Repeat that" / "say again" / "what?" (a fixed regex, transport-level) replays the last spoken line without touching the backend. |
| Operator (hospital power) | The same, if an operator phone is registered with `voice`. |
| Silence | After 20 s: STILL_THERE ("Are you still there? …"). After 3 min with a step pending: CALL_BACK, hang up, trigger 3. |
| Low-confidence speech-to-text (< 0.5) | DIDNT_CATCH ("Sorry, I didn't catch that, could you say it again?"). Not sent to the backend. |
| Long pause while the backend works | After 1.2 s with no reply: "One moment." (once per turn). |

**Latency budget:** end of speech → about 0.3 s speech-to-text final → about 2.2 s extraction (median, live eval) →
0.1–0.7 s replan → about 0.3 s to the first audio. That's **about 3–3.5 s**, covered by "One moment." DONE / repeat
/ goodbye skip the LLM. Haiku for extraction would be faster, but changes accuracy for text and voice alike: a
separate decision, made only with the eval.

**Barge-in:** allowed, except during the opener and the SAFETY text. A "yes" spoken over a long offer cuts it off and
is handled.

## 6. Exact setup steps (one-time, about 30 min; Soham clicks, nothing here texts or calls anyone)
**Photon's hackathon guidelines:**
- "Voice: phone calls run on an SMS number, not on iMessage. Add an SMS number to your project, set up a Voice
  profile, and connect it over SIP to Retell, ElevenLabs, LiveKit, or Twilio."
- "the beta is free to use".
- **Best Voice Agent** ($300 + $100 credits): "real phone calls in and out", judged on "natural turn-taking, low latency,
  and an agent that remembers the call when the conversation moves back to text". Our design does that by
  construction: the call and the texts are one thread.

**A. Photon** (app.photon.codes → project `pho_prj_…`, the one in `residents/.env`)
1. **Add an SMS number.** SMS → buy/add a US number, area code 617 if offered. If it asks for a card or shows a
   price, stop and decide. The API docs say outbound calls need a payment method (402 ENTITLEMENT_REQUIRED otherwise).
2. **Voice → Lines:** the new number appears. If there's no default profile: **Set up default → SIP → Create
   profile**. The line uses the default profile.
3. **Voice profile → Outbound calls:**
   - Digest algorithm **SHA-256** → **Enable outbound**.
   - **Copy the password now** (it's shown once), then **I saved it**.
   - Also copy the **Username** and the **SIP connection** server + TLS port, e.g. `sip.photon.codes:5061`. Use the
     SIP connection, *not* the realm.
4. Leave inbound for step C.

**B. LiveKit Cloud** (cloud.livekit.io, free "Build" plan, no card)
1. **Create a project.** Settings → API keys → create one. Copy `LIVEKIT_URL` (`wss://<project>.livekit.cloud`),
   `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`. Also note the project's **SIP URI** (`<id>.sip.livekit.cloud`).
2. **Telephony → SIP trunks → Create new trunk → Outbound:**

   | Field | Value |
   |---|---|
   | Address | `sip.photon.codes:5061`, no `sip:` prefix (the value from A3) |
   | Transport | **TLS** |
   | Numbers | the Photon number, `+1617…` (this is the caller ID) |
   | Media encryption | **enabled** |
   | Username / Password | the Photon outbound ones from A3 |

   Copy the trunk id `ST_…`.
3. **Telephony → SIP trunks → Create new trunk → Inbound.** In the JSON editor:
   ```json
   {"name": "photon-inbound", "numbers": ["+1617…"],
    "authUsername": "<pick one>", "authPassword": "<pick a long one>",
    "mediaEncryption": "SIP_MEDIA_ENCRYPT_ALLOW"}
   ```
   Leave Allowed addresses empty.
4. **Telephony → Dispatch rules → Create:**
   - type **Individual**, room prefix `ember-call-`, trunk = photon-inbound;
   - **Add agent** `ember-voice`, with **Restart on failure**.

**C. Photon inbound** (Voice profile → Inbound calls → Enable inbound)
- **SIP address:** `sips:<id>.sip.livekit.cloud` (from B1)
- **Transport:** TLS
- **SIP username / password:** the `authUsername` / `authPassword` from B3 (not the Photon outbound ones)
- **Media encryption:** Auto

**D. `residents/.env`** (gitignored; never commit). Add:
```
VOICE_ENABLED = 1
PHOTON_VOICE_NUMBER = +1617…
LIVEKIT_URL = wss://<project>.livekit.cloud
LIVEKIT_API_KEY = …
LIVEKIT_API_SECRET = …
LIVEKIT_SIP_TRUNK_ID = ST_…
```
- Keep the Photon outbound password only in LiveKit (our code never needs it); a password manager is fine as a backup.
- Speech-to-text and text-to-speech come from LiveKit Inference (no extra key; $2.50 free ≈ 50 min). For more
  minutes or Grok: `DEEPGRAM_API_KEY` / `CARTESIA_API_KEY` / `XAI_API_KEY`.

**E. Check before any code** (the setup alone proves nothing: "A saved SIP destination is not proof of a working call")
- In LiveKit's dashboard, **Telephony → Calls** / the CLI: `lk sip participant create` with `sip_call_to` = Soham's
  phone, `wait_until_answered: true`. His phone rings and shows the Photon number. Answer, then hang up: silence is
  expected (no agent yet).
- Call the Photon number from another phone: LiveKit shows a room `ember-call-…`. It's silent until the worker runs.
- Then Photon → **Voice → Recent calls** shows both.
- iPhone testers: save the Photon number as a contact, or turn off *Silence Unknown Callers*.

**Why LiveKit over ElevenLabs** (Photon's quick-start uses ElevenLabs):
- ElevenLabs' agent writes its own replies with its own LLM, which breaks D46 and the text/voice parity.
- Driving it from our backend needs its custom-LLM webhook, i.e. a public URL / tunnel from the laptop.
- Its free tier has few agent minutes.
- LiveKit's worker dials out (no tunnel), lets our code supply every sentence, and its free plan covers the drill.

## 7. Proving it works the same (tests, in this order)
1. **Speech unit tests:** golden renders for every outbound template (offers, steps, statuses, D60 answers, SAFETY,
   WELCOME…).
2. **Speakability lint:** run every existing drill transcript test and pass every outbound text through
   `render()`. None may contain `[EMBER`, `(plan v`, `Reply `, a bare `St`/`Ave`, `911` as digits, or `#`.
3. **The parity test (the key one):** parametrize the existing transcript flows (`test_drill.py`,
   `test_questions.py`) over `channel ∈ {text, voice}`. Voice runs over `FakeCallProvider` plus a fake worker on the
   real WebSocket (TestClient), saying the same lines. Assert:
   - the backend's sequence of outbound texts is **identical** across channels, apart from the opener;
   - the fake text-to-speech received `render()` of each one.
4. **CallManager tests:**
   - only voice-consenting and critical phones are called; outside the flood → no call;
   - retries and backoff on busy / no answer / voicemail, then unreachable → iMessage fallback;
   - the concurrency cap with earliest-deadline-first ordering;
   - hang-up mid-step → callback; final step → hang-up;
   - reset ends calls; restart never redials;
   - duplicate or out-of-order worker events (`utt_id` dedupe, the D54 lesson);
   - backend restart mid-call.
5. **Mutation checks** on every new guard (consent, critical-only, the retry cap, dedupe, routing), as for D56/D57/D60.
6. **Live, each step only when Soham says go:**
   1. `--dry --voice` console simulation with the real LLM.
   2. LiveKit's agent **console mode** (laptop mic/speakers): the full speech loop, no telephony, no cost.
   3. One **inbound** call from Soham's phone to the Photon number.
   4. One **outbound** call to Soham's phone.
   5. A two-phone voice drill.
   6. A **mixed** drill: one resident by text, one by voice, on the same plan. This proves both channels see the same
      plan.

## 8. Failure modes and what happens

| Failure | Behaviour |
|---|---|
| Worker not running / LiveKit down | Dial fails → logged, console warning, iMessage fallback if opted in; `GET /health` shows `voice: down`. |
| Photon 402 (no payment method) | The setup script stops with the reason. Plan B: §10. |
| Voicemail / screened call | Answering-machine detection, or no speech within 6 s of the opener → hang up, no message left, retry per §4. |
| Speech-to-text mishears the address | The PLACED line repeats where we put them; "no, I'm at …" re-places them (new correction path). |
| The worker's socket drops mid-call | It reconnects with `call_id` and resumes from the last acked `spoken` id; never replays heard text (utterance dedupe). |
| Backend restarts mid-call | The call is ended politely ("We had a problem; we'll call you right back."), then re-queued. |
| Two EMBER backends | The existing preflight blocks it; the worker refuses to join a call it didn't get from this backend. |

## 9. Lanes, contracts, rules
- **All code in `residents/`** (Soham's lane). The engine, `contracts/` and `web/` are untouched.
- **Optional ask to Aryaman (contracts):** an optional `channel: "imessage" | "voice"` on state/ws-event messages
  (version bump), so the web can show a phone icon. Without it, spoken lines appear in the web's message list as
  ordinary messages (same text), which is acceptable.
- **Hard rules:**
  - #2 (no LLM in the loop; extraction only labels) and D46 (no generated answers) are kept by §0.
  - #9: calls only on the bought number; shared iMessage stays text-only.
  - #10: the opener and the console say it's a drill.
- **DECISIONS:** D61 = voice architecture + who-gets-called policy. Log entries per feature.

## 10. Phases and time (Devpost due Sun 8:00 AM)

| Phase | What | Needs Soham | Est. |
|---|---|---|---|
| V0 | Provision: payment method, buy the number, LiveKit project, setup script | yes (card, accounts) | 45 min |
| V1 | `speech.py`, channel routing in Messenger, FakeCallProvider, the call socket, parity + lint tests | no | 2.5 h |
| V2 | CallManager (§4), `/calls` API, drill `--caller` / `call r1`, dry voice simulation, location correction | no | 2 h |
| V3 | LiveKit worker + CallBridge, console-mode test on the laptop mic | LiveKit keys | 1.5 h |
| V4 | Telephony: first inbound, then outbound call to Soham's phone | yes (his phone, go-ahead) | 1 h |
| V5 | Two-phone + mixed drill, tune endpointing and latency, D61, HANDOFF/README, PR | yes (phones) | 1.5 h |

- **V1–V3 don't depend on V0**, so they start right away while the accounts are set up.
- **Plan B** if Photon outbound can't be enabled in time: inbound-only on the Photon number (the judge *calls*
  EMBER). If no Photon number at all: LiveKit's free US number for an inbound demo, with the drill still on Photon
  iMessage. This is honest in the write-up, but then the "best voice agent on a Photon number" prize is out.

## 11. Decisions needed from Soham
1. **Number:** add the SMS number in Photon (§6 A1; the beta is free, but stop if it asks for a card). Outbound calls
   may need a payment method.
2. **LiveKit:** create the free LiveKit Cloud project and put its keys in `residents/.env`? (Recommended over
   ElevenLabs/Retell for the reasons in §0 and §2.)
3. **Voice provider:** LiveKit Inference (default), or Grok TTS for the SpaceXAI track?
4. **Between steps:** keep the line open by default ("say done when you're there"), or always hang up and call back
   when the next step is due?
5. **Who is called:** registered address (Reverse-911, recommended) and/or "call and ask where you are"?
