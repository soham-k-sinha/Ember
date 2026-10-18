# EMBER on the phone: simulated calls

Written by `residents/scripts/sim_calls.py` (D80, D85): the real planner on the Allston drill (40 scenario households
plus six people who text in), the clock moved 5 min at a time; EMBER decides whom to call and why. Each turn goes through
ElevenLabs' endpoint and says what the thread would text, shortened for speech (lists and steps follow by text).
**Synthetic:** the people, their words, the flood timing, the fleet. No model: the keyword parser reads every reply.
Speech at 150 words a minute; "ms" is EMBER's reply time (a replan when needs change).

### Margaret (84, uses a wheelchair, slow to answer): EMBER calls, mobility, sim 0:05
Before: plan v9: needs people=1, mobility=True, accessible_vehicle=True, out by 1:15; Accessible Van 3 offered, pickup at 0:14

- `  0.0s` **EMBER** (12.0 s): Hi, it's EMBER from the flood drill, calling about your wheelchair-accessible pickup. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Say yes to confirm.
- ` 16.0s` *Margaret*: Hello?
- ` 16.4s` **EMBER** (16 ms, 10.0 s): Hi, it's EMBER from the flood drill. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Say yes to confirm.
- ` 29.4s` *Margaret*: Who is this?
- ` 30.6s` **EMBER** (14 ms, 12.8 s): It's EMBER, the HackHarvard flood drill; this is a drill, not a real emergency. Accessible Van 3 is assigned to pick you up, arriving in about 9 minutes. Say yes to confirm.
- ` 48.4s` *Margaret*: Oh. Yes, yes please.
- ` 50.1s` **EMBER** (76 ms, 13.6 s): Confirmed: Accessible Van 3 is coming to your door. Stay inside at Flagg Street and Memorial Drive. The crew arrives in about 9 minutes. Say done when you're ready. I'll text you this too.
- ` 67.7s` *Margaret*: Thank you, dear.
- ` 68.9s` **EMBER** (1 ms, 4.4 s): You're welcome. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Accessible Van 3 is arriving in about 9 min. Right now: Step 1 of 4: Stay inside at Flagg Street and Memorial Drive. Get medications, ID, your phone and charger ready, plus anything you use, like a walker or oxygen. The crew arrives in about 9 min. Reply DONE when you're ready. (plan v9)

Outcome: **confirmed**, 4 turns in 73 s. After: plan v9: needs people=1, mobility=True, accessible_vehicle=True, out by 1:15; Accessible Van 3 confirmed, pickup at 0:14

_sim 0:05: a neighbour reports Callender St flooded; EMBER replans._

### Sam (said yes by text, then the pickup changed): EMBER calls, pickup changed, sim 0:05
Before: plan v10: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:53

- `  0.0s` **EMBER** (11.6 s): Hi, it's EMBER from the flood drill, calling because your pickup has changed. Update: Callender Street was reported blocked, so Van 2 is now arriving in about 108 minutes.
- ` 12.6s` *Sam*: Oh, okay. What changed?
- ` 14.2s` **EMBER** (21 ms, 18.4 s): Your pickup is confirmed: Callender Street was reported blocked, so Van 2 is arriving in about 108 minutes. Right now: Go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Say done when you're there. I'll text you this too.
- ` 33.6s` *Sam*: Okay, got it.
- ` 34.8s` **EMBER** (1 ms, 4.0 s): Great. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Callender Street was reported blocked, so Van 2 is arriving in about 108 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 108 min. Reply DONE when you're there. (plan v10)

Outcome: **talked**, 2 turns in 39 s. After: plan v10: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:53

### Jordan (calls in with questions): calls EMBER, sim 1:00
Before: not placed yet

- `  0.0s` **EMBER** (4.4 s): Hi, it's EMBER from the flood drill. How can I help?
- `  5.4s` *Jordan*: I got a flood alert. What's going on?
- `  8.6s` **EMBER** (7 ms, 5.6 s): Where are you right now? Tell me your street address or the nearest intersection.
- ` 15.2s` *Jordan*: Memorial Drive and River Street.
- ` 18.0s` **EMBER** (744 ms, 14.0 s): Got it: we have you at Memorial Drive and River Street. Water is forecast to reach your street in about 120 minutes. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 33.0s` *Jordan*: Where would you take us?
- ` 35.0s` **EMBER** (15 ms, 9.6 s): Everyone we pick up goes to David Rubenstein Treehouse (drill shelter). How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 45.6s` *Jordan*: Just me and my cat.
- ` 48.3s` **EMBER** (752 ms, 9.2 s): Van 2 will pick you up at the corner of Memorial Drive and River Street in about 16 minutes. Say yes to confirm.
- ` 58.5s` *Jordan*: Can I bring my cat?
- ` 60.5s` **EMBER** (12 ms, 9.2 s): Bring medications, ID and your phone. Bring pets too, in a carrier or on a leash. One small bag each; leave everything else.
- ` 70.7s` *Jordan*: Yes.
- ` 71.2s` **EMBER** (78 ms, 14.0 s): Confirmed. Go out to the pickup point right outside: the corner of Memorial Drive and River Street. Van 2 gets there in about 16 minutes. Say done when you're there. I'll text you this too.
- ` 86.2s` *Jordan*: Thanks, bye.
- ` 87.0s` **EMBER** (1 ms, 4.4 s): You're welcome. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 16 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Memorial Drive and River Street. Van 2 gets there in about 16 min. Reply DONE when you're there. (plan v12)

Outcome: **confirmed**, 7 turns in 91 s. After: plan v12: needs people=1, out by 2:45; Van 2 confirmed, pickup at 1:16

### Rosa (says she's fine, but the water reaches her street): EMBER calls, pickup changed, sim 1:00
Before: plan v12: needs people=2, out by 2:15; Utility truck offered, pickup at 1:11

- `  0.0s` **EMBER** (14.4 s): Hi, it's EMBER from the flood drill, calling because your pickup has changed. Utility truck will pick you up at the corner of Putnam Avenue and Western Avenue in about 11 minutes. Say yes to confirm.
- ` 15.9s` *Rosa*: No, I'm fine, we're staying put.
- ` 19.1s` **EMBER** (796 ms, 20.8 s): Understood, we won't send Utility truck. The water reaches your street in about 90 minutes; if you stay, go to the highest floor and keep your phone with you. Van 2 will pick you up at the corner of Putnam Avenue and Western Avenue in about 56 minutes. Say yes to confirm.
- ` 41.9s` *Rosa*: We're on the second floor, we'll be okay.
- ` 45.1s` **EMBER** (16 ms, 13.6 s): In a real emergency, call 9 1 1. Don't walk or drive through floodwater. If water comes inside, go to a higher floor (not a closed attic), and stay away from downed power lines.
- ` 60.7s` *Rosa*: Okay. Yes, send it.
- ` 62.5s` **EMBER** (145 ms, 14.0 s): Confirmed. Go out to the pickup point right outside: the corner of Putnam Avenue and Western Avenue. Van 2 gets there in about 56 minutes. Say done when you're there. I'll text you this too.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 56 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Putnam Avenue and Western Avenue. Van 2 gets there in about 56 min. Reply DONE when you're there. (plan v13)

Outcome: **confirmed**, 3 turns in 76 s. After: plan v13: needs people=2, out by 2:15; Van 2 confirmed, pickup at 1:56

### Sam (said yes by text, then the pickup changed): EMBER calls, pickup changed, sim 1:00
Before: plan v13: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:39

- `  0.0s` **EMBER** (9.2 s): Hi, it's EMBER from the flood drill, calling because your pickup has changed. Update: Van 2 is now arriving in about 39 minutes.
- ` 10.2s` *Sam*: Oh, okay. What changed?
- ` 11.8s` **EMBER** (23 ms, 16.0 s): Your pickup is confirmed: Van 2 is arriving in about 39 minutes. Right now: Go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Say done when you're there. I'll text you this too.
- ` 28.8s` *Sam*: Okay, got it.
- ` 30.0s` **EMBER** (1 ms, 4.0 s): Great. I'm texting you all of this now. Take care.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 2 is arriving in about 39 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Callender Street and Putnam Avenue. Van 2 gets there in about 39 min. Reply DONE when you're there. (plan v13)

Outcome: **talked**, 2 turns in 34 s. After: plan v13: needs people=1, out by 2:15; Van 2 confirmed, pickup at 1:39

### Dev (panics): EMBER calls, no reply, sim 1:30
Before: plan v13: needs unknown, out by 2:15; no vehicle

- `  0.0s` **EMBER** (14.4 s): Hi, it's EMBER from the flood drill, calling because the water reaches your street in about 60 minutes and we haven't heard back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 14.9s` *Dev*: Oh my god, is the water coming? What do I do?
- ` 19.3s` **EMBER** (18 ms, 17.6 s): I'm here with you; we'll go one step at a time. In this drill's flood forecast, water reaches your street in about 60 minutes, so we're planning to pick you up. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 37.9s` *Dev*: Okay. Okay. It's me and my two kids, three of us.
- ` 43.1s` **EMBER** (790 ms, 9.2 s): Van 1 will pick you up at the corner of Banks Street and Flagg Street in about 17 minutes. Say yes to confirm.
- ` 53.1s` *Dev*: Yes. Yes, please hurry.
- ` 54.8s` **EMBER** (128 ms, 18.4 s): I'm here with you; we'll go one step at a time. Confirmed. Go out to the pickup point right outside: the corner of Banks Street and Flagg Street. Van 1 gets there in about 17 minutes. Say done when you're there. I'll text you this too.
- ` 74.7s` *Dev*: Okay, we're ready.
- ` 76.0s` **EMBER** (65 ms, 4.8 s): Thanks. We'll let you know the next step in about 17 minutes.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 1 is arriving in about 17 min. Right now: You've done step 1 of 4; we'll text you the next step in about 17 min. (plan v14)

Outcome: **confirmed**, 4 turns in 81 s. After: plan v14: needs people=3, out by 2:15; Van 1 confirmed, pickup at 1:47

### Lee (garbled and off-topic answers): EMBER calls, no reply, sim 1:30
Before: plan v14: needs unknown, out by 2:15; no vehicle

- `  0.0s` **EMBER** (14.4 s): Hi, it's EMBER from the flood drill, calling because the water reaches your street in about 60 minutes and we haven't heard back. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 16.4s` *Lee*: Sorry, what? The dog is going crazy here.
- ` 19.6s` **EMBER** (15 ms, 8.0 s): Hi, it's EMBER from the flood drill. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 29.6s` *Lee*: Uh, the purple one, by the window.
- ` 32.4s` **EMBER** (11 ms, 7.2 s): Sorry, I didn't catch that. How many people are with you, and does anyone need a wheelchair-accessible vehicle?
- ` 41.1s` *Lee*: Two of us.
- ` 43.1s` **EMBER** (772 ms, 9.2 s): Van 1 will pick you up at the corner of Hingham Street and Putnam Avenue in about 34 minutes. Say yes to confirm.
- ` 53.3s` *Lee*: Yes.
- ` 53.8s` **EMBER** (151 ms, 14.0 s): Confirmed. Go out to the pickup point right outside: the corner of Hingham Street and Putnam Avenue. Van 1 gets there in about 34 minutes. Say done when you're there. I'll text you this too.
- after the call, by text: [EMBER drill] As promised, here's your plan in writing. Your pickup is confirmed: Van 1 is arriving in about 34 min. Right now: Step 1 of 4: Pack medications, ID, your phone and charger, then go out to the pickup point right outside: the corner of Hingham Street and Putnam Avenue. Van 1 gets there in about 34 min. Reply DONE when you're there. (plan v15)

Outcome: **confirmed**, 4 turns in 68 s. After: plan v15: needs people=2, out by 2:15; Van 1 confirmed, pickup at 2:04
