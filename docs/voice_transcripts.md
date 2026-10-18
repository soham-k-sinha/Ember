# EMBER on the phone: simulated calls

Written by `residents/scripts/sim_calls.py` (D80, D85, D92): the real planner on the Allston drill (40 scenario households
plus six people who text in), the clock moved 5 min at a time; EMBER decides whom to call and why. Each turn goes through
ElevenLabs' endpoint and says what the thread would text, shortened for speech (lists and steps follow by text).
**Synthetic:** the people, their words, the flood timing, the fleet. No model: the keyword parser reads every reply.
Speech at 150 words a minute; "ms" is EMBER's reply time (a replan when needs change).

### Margaret (84, uses a wheelchair, slow to answer): EMBER calls, mobility, sim 0:05
Before: plan v9: needs people=1, mobility=True, accessible_vehicle=True, out by 1:15; Accessible Van 3 offered, pickup at 0:14

- `  0.0s` **EMBER** (13.6 s): Hi, this is EMBER, an automated assistant for the flood drill, calling about your wheelchair-accessible pickup. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Can you be ready?
- ` 17.6s` *Margaret*: Hello?
- ` 18.0s` **EMBER** (22 ms, 11.6 s): Hi, this is EMBER, an automated assistant for the flood drill. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Can you be ready?
- ` 32.6s` *Margaret*: Who is this?
- ` 33.8s` **EMBER** (19 ms, 14.4 s): It's EMBER, an automated assistant for the HackHarvard flood drill; this is a drill, not a real emergency. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Can you be ready?
- ` 53.2s` *Margaret*: Oh. Yes, yes please.
- ` 54.9s` **EMBER** (106 ms, 13.6 s): Confirmed: Accessible Van 3 is coming to your door. Stay inside at Flagg Street and Memorial Drive. The crew arrives in about 9 minutes. Tell me when you're ready. I'll text you this too.
- ` 72.5s` *Margaret*: Thank you, dear.
- ` 73.7s` **EMBER** (1 ms, 4.4 s): You're welcome. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Accessible Van 3 is arriving in about 9 min. Right now: Step 1 of 4: Stay inside at Flagg Street and Memorial Drive. Get medications, ID, your phone and charger ready, plus anything you use, like a walker or oxygen. The crew arrives in about 9 min. Reply DONE when you're ready. (plan v9)

Outcome: **confirmed**, 4 turns in 78 s. After: plan v9: needs people=1, mobility=True, accessible_vehicle=True, out by 1:15; Accessible Van 3 confirmed, pickup at 0:14

_sim 0:05: a neighbour reports Callender St flooded; EMBER replans._

### Sam (said yes by text, then the pickup changed): EMBER calls, pickup changed, sim 0:05
Before: plan v10: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:53

- `  0.0s` **EMBER** (13.2 s): Hi, this is EMBER, an automated assistant for the flood drill, calling because your pickup has changed. Update: Callender Street was reported blocked, so Van 2 is now arriving in about 108 minutes.
- ` 14.2s` *Sam*: Oh, okay. What changed?
- ` 15.8s` **EMBER** (23 ms, 18.4 s): Your pickup is confirmed: Callender Street was reported blocked, so Van 2 is arriving in about 108 minutes. Right now: Go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Tell me when you're outside. I'll text you this too.
- ` 35.2s` *Sam*: Okay, got it.
- ` 36.4s` **EMBER** (1 ms, 4.0 s): Great. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Callender Street was reported blocked, so Van 2 is arriving in about 108 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 108 min. Reply DONE when you're there. (plan v10)

Outcome: **talked**, 2 turns in 40 s. After: plan v10: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:53

### Jordan (calls in with questions): calls EMBER, sim 1:00
Before: not placed yet

- `  0.0s` **EMBER** (6.0 s): Hi, this is EMBER, an automated assistant for the flood drill. How can I help?
- `  7.0s` *Jordan*: I got a flood alert. What's going on?
- ` 10.2s` **EMBER** (9 ms, 5.6 s): Where are you right now? Tell me your street address or the nearest intersection.
- ` 16.8s` *Jordan*: Memorial Drive and River Street.
- ` 20.1s` **EMBER** (1284 ms, 14.8 s): One moment... Got it: we have you at Memorial Drive and River Street. Water is forecast to reach your street in about 120 minutes. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 35.9s` *Jordan*: Where would you take us?
- ` 37.9s` **EMBER** (19 ms, 9.6 s): Everyone we pick up goes to David Rubenstein Treehouse (drill shelter). How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 48.5s` *Jordan*: Just me and my cat.
- ` 51.5s` **EMBER** (1000 ms, 9.2 s): Van 2 will pick you up at the corner of Memorial Drive and River Street in about 16 minutes. Can you be ready?
- ` 61.7s` *Jordan*: Can I bring my cat?
- ` 63.7s` **EMBER** (17 ms, 9.2 s): Bring medications, ID and your phone. Bring pets too, in a carrier or on a leash. One small bag each; leave everything else.
- ` 73.9s` *Jordan*: Yes.
- ` 74.4s` **EMBER** (118 ms, 14.0 s): Confirmed. Go out to the pickup point right outside: the corner of Memorial Drive and River Street. Van 2 gets there in about 16 minutes. Tell me when you're outside. I'll text you this too.
- ` 89.4s` *Jordan*: Thanks, bye.
- ` 90.2s` **EMBER** (1 ms, 4.4 s): You're welcome. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 16 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Memorial Drive and River Street. Van 2 gets there in about 16 min. Reply DONE when you're there. (plan v12)

Outcome: **confirmed**, 7 turns in 95 s. After: plan v12: needs people=1, out by 2:45; Van 2 confirmed, pickup at 1:16

### Rosa (says she's fine, but the water reaches her street): EMBER calls, pickup changed, sim 1:00
Before: plan v12: needs people=2, out by 2:15; Utility truck offered, pickup at 1:11

- `  0.0s` **EMBER** (18.8 s): Hi, this is EMBER, an automated assistant for the flood drill, calling with a new pickup for you, because we re-planned the routes. The utility truck will pick you up at the corner of Putnam Avenue and Western Avenue in about 11 minutes. Can you be ready?
- ` 20.3s` *Rosa*: No, I'm fine, we're staying put.
- ` 23.8s` **EMBER** (1070 ms, 21.2 s): Understood, we won't send the utility truck. The water reaches your street in about 90 minutes; if you stay, go to the highest floor and keep your phone with you. Van 2 will pick you up at the corner of Putnam Avenue and Western Avenue in about 56 minutes. Can you be ready?
- ` 47.0s` *Rosa*: We're on the second floor, we'll be okay.
- ` 50.2s` **EMBER** (19 ms, 13.6 s): In a real emergency, call 9 1 1. Don't walk or drive through floodwater. If water comes inside, go to a higher floor (not a closed attic), and stay away from downed power lines.
- ` 65.8s` *Rosa*: Okay. Yes, send it.
- ` 67.6s` **EMBER** (170 ms, 14.0 s): Confirmed. Go out to the pickup point right outside: the corner of Putnam Avenue and Western Avenue. Van 2 gets there in about 56 minutes. Tell me when you're outside. I'll text you this too.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 56 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Putnam Avenue and Western Avenue. Van 2 gets there in about 56 min. Reply DONE when you're there. (plan v13)

Outcome: **confirmed**, 3 turns in 82 s. After: plan v13: needs people=2, out by 2:15; Van 2 confirmed, pickup at 1:56

### Sam (said yes by text, then the pickup changed): EMBER calls, pickup changed, sim 1:00
Before: plan v13: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:39

- `  0.0s` **EMBER** (12.8 s): Hi, this is EMBER, an automated assistant for the flood drill, calling because your pickup has changed. Update: we re-planned the routes, so Van 2 is now arriving in about 39 minutes.
- ` 13.8s` *Sam*: Oh, okay. What changed?
- ` 15.4s` **EMBER** (27 ms, 18.0 s): Your pickup is confirmed: we re-planned the routes, so Van 2 is arriving in about 39 minutes. Right now: Go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Tell me when you're outside. I'll text you this too.
- ` 34.4s` *Sam*: Okay, got it.
- ` 35.6s` **EMBER** (1 ms, 4.0 s): Great. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: we re-planned the routes, so Van 2 is arriving in about 39 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 39 min. Reply DONE when you're there. (plan v13)

Outcome: **talked**, 2 turns in 40 s. After: plan v13: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:39

### Dev (panics): EMBER calls, no reply, sim 1:30
Before: plan v13: needs unknown, out by 2:15; no vehicle

- `  0.0s` **EMBER** (16.0 s): Hi, this is EMBER, an automated assistant for the flood drill, calling because the water reaches your street in about 60 minutes and we haven't heard back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 16.5s` *Dev*: Oh my god, is the water coming? What do I do?
- ` 20.9s` **EMBER** (21 ms, 17.6 s): I'm here with you; we'll go one step at a time. In this drill's flood forecast, water reaches your street in about 60 minutes, so we're planning to pick you up. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 39.5s` *Dev*: Okay. Okay. It's me and my two kids, three of us.
- ` 45.0s` **EMBER** (1069 ms, 9.2 s): Van 1 will pick you up at the corner of Banks Street and Flagg Street in about 17 minutes. Can you be ready?
- ` 55.0s` *Dev*: Yes. Yes, please hurry.
- ` 56.8s` **EMBER** (160 ms, 14.0 s): Confirmed. Go out to the pickup point right outside: the corner of Banks Street and Flagg Street. Van 1 gets there in about 17 minutes. Tell me when you're outside. I'll text you this too.
- ` 72.3s` *Dev*: Okay, we're ready.
- ` 73.5s` **EMBER** (79 ms, 4.8 s): Thanks. We'll let you know the next step in about 17 minutes.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 1 is arriving in about 17 min. Right now: You've done step 1 of 4; we'll text you the next step in about 17 min. (plan v14)

Outcome: **confirmed**, 4 turns in 78 s. After: plan v14: needs people=3, out by 2:15; Van 1 confirmed, pickup at 1:47

### Lee (garbled and off-topic answers): EMBER calls, no reply, sim 1:30
Before: plan v14: needs unknown, out by 2:15; no vehicle

- `  0.0s` **EMBER** (16.0 s): Hi, this is EMBER, an automated assistant for the flood drill, calling because the water reaches your street in about 60 minutes and we haven't heard back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 18.0s` *Lee*: Sorry, what? The dog is going crazy here.
- ` 21.2s` **EMBER** (19 ms, 9.6 s): Hi, this is EMBER, an automated assistant for the flood drill. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 32.8s` *Lee*: Uh, the purple one, by the window.
- ` 35.6s` **EMBER** (13 ms, 7.2 s): Sorry, I didn't catch that. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 44.3s` *Lee*: Two of us.
- ` 46.6s` **EMBER** (1071 ms, 9.2 s): Van 1 will pick you up at the corner of Hingham Street and Putnam Avenue in about 34 minutes. Can you be ready?
- ` 56.8s` *Lee*: Yes.
- ` 57.3s` **EMBER** (147 ms, 14.0 s): Confirmed. Go out to the pickup point right outside: the corner of Hingham Street and Putnam Avenue. Van 1 gets there in about 34 minutes. Tell me when you're outside. I'll text you this too.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 1 is arriving in about 34 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Hingham Street and Putnam Avenue. Van 1 gets there in about 34 min. Reply DONE when you're there. (plan v15)

Outcome: **confirmed**, 4 turns in 71 s. After: plan v15: needs people=2, out by 2:15; Van 1 confirmed, pickup at 2:04
