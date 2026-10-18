# EMBER × sponsor tracks

How each sponsor is used, how deep it goes, where it lives in the code, what a judge sees, and why it wins its track.
Every number here was measured on this repo (sources in brackets). Households, needs, flood timing and the fleet are
synthetic; the streets, buildings, the venue, Mount Auburn Hospital, Cottage Farm and the MWRA figures are real.

**The loop all four sit in:** a person speaks → **Photon** carries it → **ElevenLabs** hears and speaks → **Claude via
Chalk** turns the words into a fact → a deterministic simulator replans the district in ~1 s → **Daytona** stress-tests
the plan across thousands of perturbed nights → everyone affected hears their own instruction. Take any one sponsor out and
a beat of the demo stops working.

| Track | Role in EMBER | Without it | Judge sees it in |
|---|---|---|---|
| Daytona | Stress-tests every candidate plan; its pick becomes the next plan | No robust plan, 4.6× slower at scale | Daytona view (key 4): the 90-sandbox grid lighting up |
| Photon | The phone number and the message line: joins, calls in and out, multiplayer | Nobody can join or be reached | Photon view (key 2): phones → Photon → AI → planner → told |
| ElevenLabs | Every live conversation, both directions, up to 3 at once | No voice; the "call when the van arrives" beat is gone | The judges' own phones ringing and talking |
| Chalk | The gateway for every model call (reading people, answering questions) | Keyword parser only; open questions get templates | "AI reads: Claude via Chalk" on the Photon view |

---

## Daytona · the plan has to survive tonight, not just the forecast

**What we do.** A forecast-best plan is fragile: a slower road or an earlier flood strands people. EMBER sends every
candidate plan (4 + the incident-by-incident baseline) to Daytona and runs each against thousands of perturbed worlds
(travel times ×0.8–1.6, backup endurance, storage, sewage inflow and storm timing). It keeps the plan with the best
worst 20% (people first, then sewage overflow) and only switches if that saves at least one person.

**How deep.**
- A **warm pool of 90 sandboxes** on Tier 2 (100 vCPU) starts with the backend and stays warm. [`engine/ember_engine/daytona/pool.py`]
- A **snapshot bakes the engine and the whole town** in, so sandboxes need no internet; results return as the `run_code`
  value (Tier 2 rule). It is named by a content hash and rebuilt when sandbox code changes (`ember-engine-3884c8eb34`). [`pool.py`, CLAUDE.md rule 8]
- **Chunked jobs, zlib-compressed batch setup (60 → 8 KB), retries on dropped connections** (D84); pools carry an
  owner label so two processes never delete each other's sandboxes (D92). [`daytona/jobs.py`]
- **Every world streams back live** as a `scatter_point` over the WebSocket; the Daytona view lights one cell per sandbox. [`daytona/robust.py`, `web/src`]
- **The result is load-bearing:** the robust pick becomes the next published plan (plan v6 "robust optimization" in the decisions ticker).

**Measured.** Laptop vs Daytona, identical results (D86):

| worlds | laptop | Daytona (90 sandboxes) | speed-up |
|---|---|---|---|
| 250 | 2.3 s | 2.1 s | 1.1× |
| 1,000 | 4.5 s | 2.6 s | 1.7× |
| 5,000 | 13.7 s | 4.0 s | 3.4× |
| 10,000 | 24.3 s | 5.3 s | 4.6× |

Tonight on the integrated build: 10,000 worlds in 5.0–6.6 s fan-out on 90 sandboxes (e2e 88/88). At 0:00 the robust
pick leaves 15.7 people unreached in the worst 20% of worlds vs 30.3 for the forecast-best plan (baseline 40.8). After it,
the plan reaches 84 before the water (+28 vs baseline).

**Why we win the track.** Daytona isn't a code-runner bolted on: it's a decision step inside a live loop. The sandboxes
run our own simulator on our own baked data, at a scale the laptop can't match in demo time, and the answer changes what
the vans do. We measured where Daytona becomes necessary (~1,000 worlds) instead of asserting it.

---

## Photon · one number, real multiplayer

**What we do.** Photon gives EMBER its number, (346) 566-0512, and its message line. A judge calls the number (or scans
the QR) and becomes Player N on a real flood-zone home; their words change the plan for everyone; EMBER calls them back
when it matters.

**How deep.**
- **Voice:** the number is a Photon SIP trunk (`sip.photon.codes:5061`, TLS) carrying calls both ways into ElevenLabs:
  inbound joins and outbound calls at key moments. [ElevenLabs phone number import; `residents/residents/voice.py`]
- **Messages:** Photon 2.0 (`api.photon.codes/v1`): per-player assignments on the shared iMessage line, idempotent joins,
  a 25-seat cap answered cleanly (409, not a 502), seats released for players who never text (D89, D92). A socket
  listener takes inbound texts. [`residents/residents/photon.py`, `messaging.py`]
- **Multiplayer placement:** a caller with no account is registered and placed on a real household inside the forecast
  flood zone, one replan per join burst (~0.8 s). [`residents/residents/locate.py`, D89, D100]
- **Delivery that never silently fails:** a text that Photon can't deliver becomes a call (D90); every resident message
  goes through one `_send_or_call`.

**Measured.** Three phones joined at once and were each placed and called (05:20 live run); one join = one replan
(~0.8 s); e2e checks idempotent joins, the cap and an unregistered text being refused.

**Why we win the track.** Most Photon projects are a bot on one thread. EMBER is many strangers on one live, shared
world: the Photon view draws the path phones → Photon → AI → planner → told, and one player's sentence reroutes another
player's vehicle within a second. It uses Photon for both voice and messaging, handles the shared-line rules (opt-in,
seats, no group chats) properly, and never drops a message.

---

## ElevenLabs · live agents that call you when it matters

**What we do.** Every conversation is a real phone call. ElevenLabs runs speech-to-text, turn-taking and the voice;
EMBER is the agent's **Custom LLM**, so every sentence comes from the computed plan.

**How deep.**
- **Custom LLM over a tunnel:** an OpenAI-compatible, streamed `/v1/chat/completions` that only the agent can reach
  (secret path, cloudflared); EMBER configures the agent at start-up (custom LLM URL, system prompt carrying the caller
  id, first message, `end_call` tool, listening hints, silence timeout). [`voice.py`: `create_voice_app`, `configure_agent`]
- **Calls first, both directions:** outbound via the SIP-trunk API at the moments that matter (first contact, a pickup,
  a changed pickup with the reason, "2 minutes away") and **the moment a vehicle reaches a player: the simulation pauses
  and their phone rings** (D112). Inbound callers join as players. Up to 3 at once, most at-risk first; missed → one
  retry → text. (D100)
- **Built for real speech:** re-sent and revised ASR turns never count twice; stutters ("med- medical") are stripped;
  hesitation and silence are handled ("Are you still there?", then a goodbye); voicemail ends the call at once; "okay"
  once they know their pickup gets a spoken goodbye and `end_call`; "one moment…" is streamed when a turn takes >1.2 s. (D100, D107, D108, D110)
- **In-world and caring:** one opening line, then no "simulation", "drill" or "I can't". A hurt caller hears who is
  coming and one thing to do ("We've got you: Ambulance 1's paramedics… Keep the injured leg still."). An explicit
  "this is a real emergency" gets only "please hang up and call 911". (D111)

**Measured (real calls, 2026-10-18).** Replies in 0.6–1.4 s on short turns; 2–6 s when a long sentence goes to the
model; three concurrent calls each placed and answered; every call ended by EMBER with a spoken goodbye after the fixes.

**Why we win the track.** The agent isn't a scripted IVR or a free-running chatbot: it's a voice front-end on a live
planner that decides who gets the only accessible van. It calls *you* when your van is at the door, handles messy real
speech, and stays honest (D76 guard: no invented vehicle, time or street). Every rough edge we found on real calls tonight
became a test (`residents/tests/test_voice.py`, `test_tonights_live_calls`).

---

## Chalk · every model call, routed and graded

**What we do.** Both of EMBER's model uses go through **Chalk's Model Gateway** (`api.chalk.ai/v1/router`,
`X-Chalk-Env-Id`, model prefix `anthropic/`): reading what people say into a structured fact, and answering open
questions on calls ("where are the police?", "can I bring my dog?"). [`residents/residents/extract.py` `anthropic_client`, `talk.py`]

**How deep.**
- **Reading:** Claude turns free speech into a typed fact (people, wheelchair, medical, urgent, a blocked street, a
  facility's backup minutes); the planner, never the model, decides. (D76)
- **Answering:** `talk.py` gives the model a sheet of what EMBER knows about this caller (vehicle, ETA, step, water time,
  closures, shelter, facilities) under a guard that rejects any new number, vehicle or street, dead ends and over-long
  answers; a 3.5 s limit falls back to a computed answer. (D111)
- **Speed where it matters:** short call turns the keyword parser reads with certainty skip the model (~1 s pickups);
  long or unclear sentences go through Chalk. (D108)
- **Graded by outcomes, not words:** a simulator-graded eval asks whether the household was reached in time with the
  right vehicle. Through Chalk: **50/51 pass, 0 fail, 100% safe** (keyword fallback 46/51). [`docs/eval.md`, D91; the
  eval predates the newest fact kinds]
- **Visible:** `/health` reports the reader, and the Photon view's "AI reads" box says **Claude via Chalk**.

**Why we win the track.** Chalk is the single, swappable path for every model call in a safety-critical loop, and we
evaluate it the way the domain demands: by whether people are reached, simulated, not by text similarity. The guard and
the fallback mean the gateway can be slow or down and EMBER still answers.

---

## What a judge can verify in 60 seconds
- **Daytona:** press **Large stress test** on the Daytona view: the sandbox grid, worlds, seconds vs the laptop, and the plan it picks.
- **Photon + ElevenLabs:** call (346) 566-0512; your Player card appears, your words show on it, a vehicle is assigned, and your phone rings again when it arrives.
- **Chalk:** ask EMBER an open question on the call; the Photon view shows "AI reads: Claude via Chalk".
- **Code:** `engine/ember_engine/daytona/`, `residents/residents/{photon,voice,talk,extract}.py`, decisions D76, D84–D86, D89–D92, D100, D107–D114 in `docs/DECISIONS.md`.
