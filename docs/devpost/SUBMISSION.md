# EMBER — Devpost submission (HackHarvard 2026)

**EMBER: adaptive coordination for disasters, shown on a Charles River flood.**
*Forecasts are wrong by minute 10. EMBER keeps the plan right once real people start talking.*

Call **(346) 566-0512** from any phone and you become a household in the flood.

## Inspiration
In a flood the plan is made once, from a forecast, and it is wrong ten minutes later. Then people start calling: a mother in a wheelchair, a street under water, a hospital on backup power. Coordinators handle each call as it comes, and shared resources like the one accessible van or the one big generator get committed early and never reconsidered.

We are next to the Charles. On 10 January 2024, the Cottage Farm facility across the river released about 80,700 m³ of untreated sewage into it in one storm (MWRA). We wanted a system that re-plans the whole district every time someone speaks, and says what each choice costs.

## What it does
EMBER simulates a flood around the David Rubenstein Treehouse in Allston on real OpenStreetMap streets and buildings. Mount Auburn Hospital and Cottage Farm are in it.

1. **People talk to it.** Residents and facility operators call or iMessage the EMBER number. Judges join by calling.
2. **The AI understands.** Claude reads each sentence into a structured fact: how many people, a wheelchair, an injury, a blocked street, ten minutes of backup power.
3. **The simulator decides.** A deterministic planner scores candidate plans by simulating the whole district (roads closing as the water rises, vehicles, the hospital, the sewage system) and re-plans in about 0.7–1 s. The AI never picks a route, a time or a vehicle.
4. **The AI words the reply.** It phrases what the planner computed, and a guard rejects any number, vehicle, place or street the plan does not contain.
5. **Everyone affected hears about it.** When a vehicle reaches a player, the simulation pauses and EMBER calls them: "outside now."
6. **Daytona stress-tests the plan** across thousands of perturbed versions of tonight and keeps the one that holds up in the worst 20%.

One judge says "I fell and hurt my leg"; Ambulance 1 is re-routed to them, and another player's van changes order. One player's words move a stranger's rescue.

## How we built it
- **Engine** (Python, numpy): the OSM district, a flood that closes roads over time behind a single hazard interface, vehicle, facility and wastewater models, and a plan simulator that runs in milliseconds. The objective is lexicographic: people not reached, then hospital outage, then sewage overflow.
- **Planner:** priority rules plus local search, every candidate scored by the simulator. Each decision carries its counterfactual in simulated numbers.
- **Daytona:** a warm pool of 90 sandboxes with code and data baked into a snapshot. Results return through `run_code`, since the sandboxes have no internet.
- **Photon 2.0** carries iMessage and the phone line; calls go over SIP into **ElevenLabs** voice agents whose LLM is EMBER's own backend.
- **Claude via Chalk's Model Gateway** reads the words and answers open questions under the guard.
- **Backend** (FastAPI, SQLite, WebSocket) holds the single shared state. The **website** (React, PixiJS isometric stage) has four views: Live, Photon, Impact and Daytona.
- **JSON Schema contracts and fixtures** let four people build in parallel.

## Challenges we ran into
- **Keeping the LLM out of the plan while answering every question.** We built a guard that rejects any reply naming a number, vehicle or street the planner didn't compute, with deterministic fallbacks when the model is slow.
- **Calls that feel live.** First answers took 7–12 s with three callers, because every caller waited on one lock. Per-thread locks brought answers to about a second.
- **Real strangers on a fake flood.** One opening line says it is a live demo, everything after stays in the flood, and "this is a real emergency" always gets "If this is a real emergency, please hang up and call 911."
- **Finding planner gaps.** Explaining every decision with counterfactual simulations showed the planner once left the hospital dark when moving the generator cost no rescue.

## Accomplishments that we're proud of
All numbers come from the simulator on synthetic households:
- Plan v1 reaches **78 people before the water vs 58** for an incident-by-incident baseline; after the robust pick, **84 (+28)**.
- Hospital outage **13 min vs 27**.
- Sewage overflow **0 m³ vs 2,317 m³**: the generator is pre-positioned at Cottage Farm. EMBER keeps 5,167 m³ out of the Charles before the hospital needs the generator. Then it accepts 9,600 m³ to keep the hospital powered, and says so on screen.
- Re-plans in about 0.7–1 s; end-to-end test **88/88** against the live stack with real Daytona.
- Real calls tonight, answered in about a second.

## What we learned
The split between understanding and deciding is what makes this trustworthy. Every instruction a resident hears has a computed reason, so we can grade the AI by what it does to outcomes rather than by how it sounds.

## What's next
- More hazards behind the same interface: a synthetic chemical plume already runs on the engine; heat waves and winter storms are next.
- Calibrated flood and travel models from real elevation and traffic data.
- Pre-season staging for utilities and cities: where to place generators and crews so the plan holds up across thousands of storms.

## What's real and what's synthetic
**Real:** OSM streets and buildings, the venue, Mount Auburn Hospital, Cottage Farm and MWRA's 2024 discharge figures. **Synthetic, and labelled in the app:** the households and their needs, the flood timing and the fleet, Ambulance 1 included.

## Built with
Python, numpy, scipy, OSMnx, Shapely, FastAPI, SQLite, WebSocket, Daytona, Photon 2.0, ElevenLabs, Chalk Model Gateway, Anthropic Claude, React, TypeScript, Vite, PixiJS, deck.gl, MapLibre, cloudflared.

## Sponsor tracks
**Daytona (Tier 2).** Every candidate plan is stress-tested on 90 warm Daytona sandboxes. 10,000 perturbed worlds take about 4–7 s of fan-out, against about 24 s on the laptop (D86). The perturbations cover travel times, flood timing, backup endurance, sewage inflow and a vehicle failing. Code and data are baked into the snapshot, and results come back as `run_code` return values. The Daytona view shows the sandbox grid lighting up live, then the verdict.

**Photon.** The EMBER number, (346) 566-0512, carries both the calls (SIP into ElevenLabs) and iMessage. Judges join by calling it. This is real-time multiplayer: every phone is a household in the same flood, and one player's words re-route another player's vehicle. The Photon view draws phones → Photon → AI reads → planner → told, and the path pulses on every message.

**ElevenLabs.** Live voice agents use EMBER as their Custom LLM and take up to 3 calls at once. We measured answers of about 1 s on real calls tonight. EMBER also calls out: when a vehicle reaches a player, the simulation pauses on arrival and their phone rings.

**Chalk.** Claude, through Chalk's Model Gateway, reads what people say and answers open questions on calls under the guard. In a simulator-graded eval, a message passes only if the plan built from the model's reading reaches the same people with no regret. It scored 50/51 pass and 100% safe, with the one remaining message asked about instead of guessed (`docs/eval.md`). The eval predates the newest fact kinds (injuries, ambulance).

---

## Who built what
From git history and `docs/log/<name>.md`. Each person writes their own lesson; nobody writes one for someone else.
- **Aryaman:** the engine (OSM town, flood hazard, vehicle/facility/sewage models, plan simulator, allocator and replans, baseline, comparison), the contracts, Daytona robustness (snapshot, warm 90-sandbox pool), the PixiJS stage and judge-facing website, multiplayer join, proactive calls, the simulator-graded eval, integration and the end-to-end test.
  Lesson:
- **Soham:** the backend (FastAPI, SQLite shared state, WebSocket), Photon 2.0 threads, the text → fact extraction and its keyword fallback, the text-driven simulation, answering questions from the plan, and voice calls through ElevenLabs on the Photon number.
  Lesson:
- **Arnav:** the first operator map (React + deck.gl on MapLibre), its panels and the live WebSocket client.
  Lesson:
- **Anshuman:** the allston_flood_v1 scenario: flood keyframes, facilities, fleet, the households, assumptions and sources (MWRA, Climate Ready Boston).
  Lesson:

## Images
1. `docs/img/live.png`: the Live view. The district around the Treehouse, the score card against the baseline and the decisions ticker.
2. `docs/img/photon.png`: the Photon view. The join number and QR, each phone as a player, and the path phones → Photon → AI reads → planner → told.
3. `docs/img/impact.png`: the Impact view. People reached, hospital outage and sewage against the baseline, drawn to scale against Cottage Farm's 80,700 m³.
4. `docs/img/daytona.png`: the Daytona view. 10,000 worlds on 90 sandboxes against the laptop, and the verdict.

## Video shot list (3:00, follows `docs/DEMO.md`)
| Time | View | Shot | Voice-over |
|---|---|---|---|
| 0:00–0:15 | Live, clock 0:00 | The stage: Treehouse, river, Mount Auburn, Cottage Farm; score card 78 vs 58. | "In a flood the plan is made once and it's wrong in ten minutes. Watch what happens when the people in it can talk back." |
| 0:15–0:35 | Photon, clock 5:00 | Judges scan the QR or dial (346) 566-0512; each phone becomes a node and a player card. | "Any phone. You're now a household in this flood." |
| 0:35–1:25 | Photon → Live | One caller: "4 of us, my mom's in a wheelchair." Another: "I fell and hurt my leg, I can't walk." Cards show their words and EMBER's reply; Accessible Van 3 goes to the wheelchair home, Ambulance 1 to the hurt caller. Include a 15 s audio clip of a call. | "The AI only understands; a simulator decides. Your words just moved a stranger's rescue." |
| 1:25–1:45 | Live | Play. A vehicle reaches a player: the clock stops, the gold alert "Van 3 reached Player 1 · Show", the phone rings. Click Show for the close-up at the door. | "The vehicle is at your door, and EMBER calls you that second." |
| 1:45–2:10 | Impact | Soham texts as Mount Auburn: "we lost grid power, on backup, about 10 minutes left." Outage against the baseline; sewage to scale against Cottage Farm; the trade-off stated. | "People first, and EMBER says what it costs instead of hiding it." |
| 2:10–2:40 | Daytona | Large stress test: laptop → 90 sandbox cells lighting up → verdict; worlds, sandboxes, seconds vs the laptop. | "Daytona replays tonight thousands of ways in seconds and keeps the plan that holds up." |
| 2:40–3:00 | Live | Close on the district. | "Photon carries the calls, ElevenLabs the voices, Claude via Chalk reads them, Daytona stress-tests the plan. Every decision has a computed reason." |
