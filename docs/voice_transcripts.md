# EMBER on the phone: simulated calls

Written by `residents/scripts/sim_calls.py` (D80). One run of the Allston flood drill: the real planner and its
40 scenario households, six residents who text in, the sim clock moved 5 minutes at a time. EMBER decides on its own
whom to call and why (no reply while the water is close, a wheelchair or medical need not yet confirmed, a pickup
that changed), most at-risk first, at most two calls at once. Every caller turn goes through the same endpoint
ElevenLabs uses; every instruction EMBER says is the one its texts would say, rendered for speech. **Synthetic:** the six
people and their words, the flood timing, the fleet. The keyword parser stands in for the LLM, so no model is in these
calls. Times: EMBER speaks at 150 words a minute; "ms" is how long EMBER took to answer (a replan when needs change).

### Margaret (84, uses a wheelchair, slow to answer): EMBER calls, mobility, sim 0:05
Before: plan v9: needs people=1, mobility=True, accessible_vehicle=True, out by 1:15; Accessible Van 3 offered, pickup at 0:14

- `  0.0s` **EMBER** (12.0 s): Hi, it's EMBER from the flood drill, calling about your wheelchair-accessible pickup. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Say yes to confirm.
- ` 16.0s` *Margaret*: Hello?
- ` 16.4s` **EMBER** (16 ms, 12.0 s): Hi, it's EMBER from the flood drill, calling about your wheelchair-accessible pickup. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Say yes to confirm.
- ` 31.4s` *Margaret*: Who is this?
- ` 32.6s` **EMBER** (14 ms, 14.4 s): This is EMBER, the HackHarvard flood drill, with your evacuation plan. It's a drill, not a real emergency. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Say yes to confirm.
- ` 52.0s` *Margaret*: Oh. Yes, yes please.
- ` 53.7s` **EMBER** (76 ms, 22.0 s): Confirmed: Accessible Van 3 is coming to your door. Step 1 of 4: Stay inside at Flagg Street and Memorial Drive. Get medications, ID, your phone and charger ready, plus anything you use, like a walker or oxygen. The crew arrives in about 9 minutes. Say done when you're ready. I'll text you this too.
- ` 79.7s` *Margaret*: Thank you, dear.
- ` 80.9s` **EMBER** (1 ms, 4.4 s): You're welcome. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Accessible Van 3 is arriving in about 9 min. Right now: Step 1 of 4: Stay inside at Flagg Street and Memorial Drive. Get medications, ID, your phone and charger ready, plus anything you use, like a walker or oxygen. The crew arrives in about 9 min. Reply DONE when you're ready. (plan v9)

Outcome: **confirmed**, 4 turns in 85 s. After: plan v9: needs people=1, mobility=True, accessible_vehicle=True, out by 1:15; Accessible Van 3 confirmed, pickup at 0:14

_sim 0:05: a neighbour reports Callender St flooded; EMBER replans._

### Sam (said yes by text, then the pickup changed): EMBER calls, pickup changed, sim 0:05
Before: plan v10: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:53

- `  0.0s` **EMBER** (9.2 s): Hi, it's EMBER from the flood drill, calling because your pickup has changed. Update: Van 2 is now arriving in about 108 minutes.
- ` 10.2s` *Sam*: Oh, okay. What changed?
- ` 11.8s` **EMBER** (21 ms, 24.0 s): Your pickup is confirmed: Van 2 is arriving in about 108 minutes. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 108 minutes. Say done when you're there. I'll text you this too.
- ` 36.8s` *Sam*: Okay, got it.
- ` 38.0s` **EMBER** (1 ms, 4.0 s): Great. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 108 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 108 min. Reply DONE when you're there. (plan v10)

Outcome: **talked**, 2 turns in 42 s. After: plan v10: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:53

### Jordan (calls in with questions): calls EMBER, sim 1:00
Before: not placed yet

- `  0.0s` **EMBER** (4.4 s): Hi, it's EMBER from the flood drill. How can I help?
- `  5.4s` *Jordan*: I got a flood alert. What's going on?
- `  8.6s` **EMBER** (7 ms, 11.2 s): We can tell you exactly what to do once we know where you are. Where are you right now? Tell me your street address or the nearest intersection.
- ` 20.8s` *Jordan*: Memorial Drive and River Street.
- ` 23.5s` **EMBER** (735 ms, 14.0 s): Got it: we have you at Memorial Drive and River Street. Water is forecast to reach your street in about 120 minutes. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 38.5s` *Jordan*: Where would you take us?
- ` 40.6s` **EMBER** (15 ms, 9.6 s): Everyone we pick up goes to David Rubenstein Treehouse (drill shelter). How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 51.2s` *Jordan*: Just me and my cat.
- ` 53.9s` **EMBER** (778 ms, 14.8 s): Van 2 will pick you up at the corner of Memorial Drive and River Street in about 16 minutes and take you to David Rubenstein Treehouse (drill shelter). Say yes to confirm, or tell us what changed.
- ` 69.7s` *Jordan*: Can I bring my cat?
- ` 71.7s` **EMBER** (12 ms, 15.2 s): Bring medications (and prescriptions), ID, your phone and charger, glasses, and anything someone with you needs, like a walker or oxygen. Bring pets too, in a carrier or on a leash. One small bag each; leave everything else.
- ` 87.9s` *Jordan*: Yes.
- ` 88.4s` **EMBER** (79 ms, 21.2 s): Confirmed: Van 2 is coming to you. Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Memorial Drive and River Street. Van 2 gets there in about 16 minutes. Say done when you're there. I'll text you this too.
- `110.6s` *Jordan*: Thanks, bye.
- `111.4s` **EMBER** (1 ms, 4.4 s): You're welcome. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 16 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Memorial Drive and River Street. Van 2 gets there in about 16 min. Reply DONE when you're there. (plan v12)

Outcome: **confirmed**, 7 turns in 116 s. After: plan v12: needs people=1, out by 2:45; Van 2 confirmed, pickup at 1:16

### Rosa (says she's fine, but the water reaches her street): EMBER calls, pickup changed, sim 1:00
Before: plan v12: needs people=2, out by 2:15; Generator truck offered, pickup at 1:11

- `  0.0s` **EMBER** (20.0 s): Hi, it's EMBER from the flood drill, calling because your pickup has changed. Generator truck will pick you up at the corner of Putnam Avenue and Western Avenue in about 11 minutes and take you to David Rubenstein Treehouse (drill shelter). Say yes to confirm, or tell us what changed.
- ` 21.5s` *Rosa*: No, I'm fine, we're staying put.
- ` 24.7s` **EMBER** (785 ms, 29.2 s): Understood, we won't send Generator truck. The water reaches your street in about 90 minutes; if you stay, go to the highest floor and keep your phone with you. Tell me if you change your mind. Van 2 will pick you up at the corner of Putnam Avenue and Western Avenue in about 56 minutes and take you to David Rubenstein Treehouse (drill shelter). Say yes to confirm, or tell us what changed.
- ` 55.9s` *Rosa*: We're on the second floor, we'll be okay.
- ` 59.1s` **EMBER** (16 ms, 8.8 s): Sorry, I didn't catch that. Van 2 is assigned to pick you up, arriving in about 56 minutes. Say yes to confirm.
- ` 69.9s` *Rosa*: Okay. Yes, send it.
- ` 71.6s` **EMBER** (129 ms, 21.2 s): Confirmed: Van 2 is coming to you. Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Putnam Avenue and Western Avenue. Van 2 gets there in about 56 minutes. Say done when you're there. I'll text you this too.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 56 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Putnam Avenue and Western Avenue. Van 2 gets there in about 56 min. Reply DONE when you're there. (plan v13)

Outcome: **confirmed**, 3 turns in 93 s. After: plan v13: needs people=2, out by 2:15; Van 2 confirmed, pickup at 1:56

### Sam (said yes by text, then the pickup changed): EMBER calls, pickup changed, sim 1:00
Before: plan v13: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:39

- `  0.0s` **EMBER** (9.2 s): Hi, it's EMBER from the flood drill, calling because your pickup has changed. Update: Van 2 is now arriving in about 39 minutes.
- ` 10.2s` *Sam*: Oh, okay. What changed?
- ` 11.8s` **EMBER** (23 ms, 24.0 s): Your pickup is confirmed: Van 2 is arriving in about 39 minutes. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 39 minutes. Say done when you're there. I'll text you this too.
- ` 36.8s` *Sam*: Okay, got it.
- ` 38.0s` **EMBER** (1 ms, 4.0 s): Great. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 39 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 39 min. Reply DONE when you're there. (plan v13)

Outcome: **talked**, 2 turns in 42 s. After: plan v13: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:39

### Dev (panics): EMBER calls, no reply, sim 1:30
Before: plan v13: needs unknown, out by 2:15; no vehicle

- `  0.0s` **EMBER** (14.4 s): Hi, it's EMBER from the flood drill, calling because the water reaches your street in about 60 minutes and we haven't heard back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 14.9s` *Dev*: Oh my god, is the water coming? What do I do?
- ` 19.3s` **EMBER** (18 ms, 18.4 s): In this drill's flood forecast, water reaches your street in about 60 minutes, so we're planning to pick you up; we need a few details to send the right vehicle. Please tell us: How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 38.7s` *Dev*: Okay. Okay. It's me and my two kids, three of us.
- ` 43.9s` **EMBER** (785 ms, 14.8 s): Van 1 will pick you up at the corner of Banks Street and Flagg Street in about 17 minutes and take you to David Rubenstein Treehouse (drill shelter). Say yes to confirm, or tell us what changed.
- ` 59.5s` *Dev*: Yes. Yes, please hurry.
- ` 61.2s` **EMBER** (103 ms, 21.2 s): Confirmed: Van 1 is coming to you. Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Banks Street and Flagg Street. Van 1 gets there in about 17 minutes. Say done when you're there. I'll text you this too.
- ` 83.9s` *Dev*: Okay, we're ready.
- ` 85.2s` **EMBER** (92 ms, 4.8 s): Thanks. We'll let you know the next step in about 17 minutes.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 1 is arriving in about 17 min. Right now: You've done step 1 of 4; we'll text you the next step in about 17 min. (plan v14)

Outcome: **confirmed**, 4 turns in 90 s. After: plan v14: needs people=3, out by 2:15; Van 1 confirmed, pickup at 1:47

### Lee (garbled and off-topic answers): EMBER calls, no reply, sim 1:30
Before: plan v14: needs unknown, out by 2:15; no vehicle

- `  0.0s` **EMBER** (14.4 s): Hi, it's EMBER from the flood drill, calling because the water reaches your street in about 60 minutes and we haven't heard back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 16.4s` *Lee*: Sorry, what? The dog is going crazy here.
- ` 19.6s` **EMBER** (1 ms, 14.4 s): Hi, it's EMBER from the flood drill, calling because the water reaches your street in about 60 minutes and we haven't heard back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 36.0s` *Lee*: Uh, the purple one, by the window.
- ` 38.8s` **EMBER** (10 ms, 7.2 s): Sorry, I didn't catch that. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 47.5s` *Lee*: Two of us.
- ` 49.5s` **EMBER** (766 ms, 14.8 s): Van 1 will pick you up at the corner of Hingham Street and Putnam Avenue in about 34 minutes and take you to David Rubenstein Treehouse (drill shelter). Say yes to confirm, or tell us what changed.
- ` 65.3s` *Lee*: Yes.
- ` 65.8s` **EMBER** (120 ms, 21.2 s): Confirmed: Van 1 is coming to you. Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Hingham Street and Putnam Avenue. Van 1 gets there in about 34 minutes. Say done when you're there. I'll text you this too.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 1 is arriving in about 34 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Hingham Street and Putnam Avenue. Van 1 gets there in about 34 min. Reply DONE when you're there. (plan v15)

Outcome: **confirmed**, 4 turns in 87 s. After: plan v15: needs people=2, out by 2:15; Van 1 confirmed, pickup at 2:04
