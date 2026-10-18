# EMBER: the 3-minute pitch and judge Q&A

Numbers marked † are re-measured after round 2 (`engine/scripts/e2e.py`, DEMO.md). Never say a number that isn't on screen or in DEMO.md.

## The pitch (≈3:00)

**0:00 Hook (15 s).** "In a flood, the plan is made once, from a forecast, and it's wrong by minute ten: a wheelchair nobody knew about, a street that's blocked, a hospital on backup. EMBER keeps the plan right once real people start texting."

**0:15 What it is (20 s).** "People report over iMessage. One AI call turns the text into a fact. Then a simulator, not the AI, scores candidate plans and replans the whole district in under a second, and everyone whose instruction changed gets a text, or a call if they're most at risk. Flood response is our first demonstration; adaptive coordination is the product."

**0:35 Beat 1: you're in it (35 s).** Hand the judge the join card. "Type your number, scan, text JOIN EMBER." They become Player N on a flood-zone house and get EMBER's question on their phone. "Every judge at this table is now a household in this flood."

**1:10 Beat 2: one text changes other people's plans (35 s).** The judge texts "2 of us, my mom's in a wheelchair, River St is blocked". On screen: the latest-change strip, the accessible van rerouted, and the generator rerouted because of *their* road. "Your text moved a van you've never seen. Replanned in 0.7 s †."

**1:45 Beat 3: hospital vs sewage, people first (25 s).** The operator says "on backup, 10 minutes left". The generator moves to Mount Auburn, and EMBER states the cost: "9,600 m³ of untreated sewage into the Charles, stated, not hidden." "Before that call, EMBER had kept 5,167 m³ † out of the river. The real Cottage Farm facility released 80,700 m³ in one 2024 storm."

**2:10 Beat 4: Daytona stress test (30 s).** Press Optimize. "Ninety Daytona sandboxes run every candidate plan against thousands of versions of tonight: slower roads, an earlier flood, a van failing. 10,000 worlds in about 5 s †, 4.6× our laptop. We pick the plan that holds up when things go wrong."

**2:40 Close (20 s).** "Versus the baseline that handles each call as it comes: 37 † more people reached before the water, a shorter hospital outage, zero sewage until the hospital needs the generator. Real streets and facilities; households and timings are synthetic and labelled. Every decision has a computed reason. Ask us anything."

## Judge Q&A

- **"Is the AI making the plan?"** No. The AI only reads a text into a fact and words the reply; a guard rejects any number, vehicle or street the planner didn't produce. Routes, ETAs and assignments come from a deterministic numpy simulator and local search, about 0.7 s per replan.
- **"How is this different from LANDFALL / forecast planners?"** They plan once from a forecast, in minutes to hours. We replan in under a second from what people report, and send each person their own instruction.
- **"What's real?"** OSM streets and buildings, the venue, Mount Auburn Hospital, the Cottage Farm CSO and outfall MWR201, and the MWRA 2024 discharge figures. Synthetic, labelled in the app: households and needs, flood timing, fleet, background traffic and passers-by.
- **"Why Daytona and not your laptop?"** Isolation and scale. At 250 worlds they're even; at 10,000 Daytona is 4.6× faster (24 s vs 5 s †), fast enough to stress-test a plan during a call.
- **"Why trust the text understanding?"** We grade it by outcomes, not words: a simulator-graded eval asks whether the household was reached in time with the right vehicle. 50/51 pass, 100% safe through Chalk's Model Gateway; when unsure it asks instead of guessing. With no AI available, a keyword parser keeps texts working.
- **"What about the hospital vs the environment?"** The objective is lexicographic: people first, then hospital outage, then sewage overflow. Every trade-off is stated with simulated numbers.
- **"Voice?"** EMBER calls the most at-risk people first: no reply while the water is close, a wheelchair or medical need, or a changed pickup. Same words as the texts, short and calm, and a text follows. ElevenLabs on our Photon number. (Say "tested in simulation" unless the live call was verified.)
- **"What would it take to use for real?"** Real household data from city 311 and utility outage feeds, a calibrated flood model from elevation data, and an operator console. The coordination loop stays the same, and other hazards plug into the same hazard interface.
- **"Who built what?"** Each member gives 20 s on their part (see docs/devpost "Who built what").
