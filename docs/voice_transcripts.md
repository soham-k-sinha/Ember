# EMBER on the phone: calls first (simulated)

Written by `residents/scripts/sim_calls.py` (D100): the real planner on the Allston flood (40 scenario households plus
the players), the clock moved a minute at a time. A player who joins is called right away; EMBER calls again for the
pickup that changed and "2 minutes away"; everything else goes out as one short text after the call, on the plan's
clock, with no YES or DONE needed. At most 3 calls at once, earliest flood deadline first; a missed call is tried once
more 2 sim-min later, then texted. **Synthetic:** the people, their words, the flood timing, the fleet. No model: the
keyword parser reads every reply and a question gets talk.py's in-world answer without the reply model (D111). Speech at
150 words a minute; "ms" is EMBER's reply time (a replan when needs change).

### Maria (74, her mother uses a wheelchair and oxygen): EMBER calls, first contact, sim 0:00
Before: plan v4: needs unknown, out by 1:15; no vehicle

- `  0.0s` **EMBER** (14.8 s): Hi, this is EMBER, an automated flood-response assistant for this live demo. The river reaches Soldiers Field Road in about 90 minutes. How many people are with you, and does anyone need a wheelchair or medical help?
- ` 17.8s` *Maria*: Hello?
- ` 18.2s` **EMBER** (13 ms, 7.2 s): Hi, it's EMBER. How many people are with you, and does anyone need a wheelchair or medical help?
- ` 27.4s` *Maria*: It's me and my mother. She's in a wheelchair and she needs her oxygen.
- ` 33.9s` **EMBER** (912 ms, 14.0 s): Accessible Van 3 is coming to your door in about 15 minutes. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care.
- ` 49.9s` *Maria*: Okay. Thank you.
- ` 51.1s` **EMBER** (1 ms, 4.4 s): You're welcome. I'll text you all of this now. Take care.
- after the call, by text: From our call: Accessible Van 3 is coming to your door in about 15 min. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care. (plan v5)

Outcome: **updated**, 3 turns in 56 s. After: plan v5: needs people=2, mobility=True, accessible_vehicle=True, medical=True, out by 1:15; Accessible Van 3 confirmed, pickup at 0:15

### Dev (the live call's turns, re-sent and revised the way ElevenLabs posted them): EMBER calls, first contact, sim 0:00
Before: plan v5: needs unknown, out by 1:15; no vehicle

- `  0.0s` **EMBER** (14.8 s): Hi, this is EMBER, an automated flood-response assistant for this live demo. The river reaches Soldiers Field Road in about 90 minutes. How many people are with you, and does anyone need a wheelchair or medical help?
- ` 15.8s` *Dev*: Um, there are four of us, and one needs a wheelchair.
- ` 21.2s` **EMBER** (969 ms, 10.0 s): Accessible Van 3 is coming to your door in about 15 minutes. Be ready at the door with medications, ID, your phone and the wheelchair.
- ` 33.2s` *Dev*: A walker.
- ` 34.0s` **EMBER** (44 ms, 4.8 s): Got it. Accessible Van 3 gets to you in about 15 minutes.
- ` 39.3s` *Dev*: A walker. I need my ankle. _(revised)_
- ` 41.8s` **EMBER** (91 ms, 4.8 s): Got it. Accessible Van 3 gets to you in about 15 minutes.
- ` 47.1s` *Dev*: A walker. I need my needle. _(revised)_
- ` 50.4s` **EMBER** (891 ms, 14.8 s): Got it. Accessible Van 3 is coming to your door in about 15 minutes. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care.
- ` 67.2s` *Dev*: I'm done.
- ` 68.1s` **EMBER** (101 ms, 8.0 s): Thanks. Accessible Van 3 gets to you in about 15 minutes. I'll text you all of this now. Take care.
- ` 76.6s` *Dev*: I'm done. Okay, done. _(revised)_
- ` 78.2s` **EMBER** (48 ms, 8.0 s): Thanks. Accessible Van 3 gets to you in about 15 minutes. I'll text you all of this now. Take care.
- ` 86.7s` *Dev*: A walker. I need my needle. _(re-sent)_
- ` 89.1s` **EMBER** (1 ms): the same reply again, not processed again
- ` 89.6s` *Dev*: I'm done. _(re-sent)_
- ` 90.4s` **EMBER** (1 ms): the same reply again, not processed again
- ` 90.9s` *Dev*: I'm done. _(re-sent)_
- ` 91.7s` **EMBER** (1 ms): the same reply again, not processed again
- after the call, by text: From our call: Accessible Van 3 is coming to your door in about 15 min. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care. (plan v7)

Outcome: **updated**, 6 turns in 92 s. After: plan v7: needs people=4, mobility=True, accessible_vehicle=True, medical=True, out by 1:15; Accessible Van 3 confirmed, pickup at 0:15

### Jordan (calls the number, joins by voice): calls EMBER, sim 0:04
Before: not placed yet

- `  0.0s` **EMBER** (6.4 s): Hi, this is EMBER, an automated flood-response assistant for this live demo. How can I help?
- `  7.4s` *Jordan*: Hi, I saw the flood sign. Can I join?
- ` 12.1s` **EMBER** (1105 ms, 14.8 s): You're Player 5, living by the corner of Elmer Street and Hingham Street; the river reaches your street in about 146 minutes. How many people are with you, and does anyone need a wheelchair or medical help?
- ` 28.4s` *Jordan*: Just me.
- ` 30.4s` **EMBER** (1241 ms, 12.8 s): Van 1 picks you up in about 19 minutes. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Elmer Street and Hingham Street.
- ` 44.2s` *Jordan*: Thanks, bye.
- ` 45.0s` **EMBER** (1 ms, 4.4 s): You're welcome. I'll text you all of this now. Take care.
- after the call, by text: EMBER flood response, live demo. From our call: Van 1 picks you up in about 19 min. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Elmer Street and Hingham Street. (plan v10)

Outcome: **updated**, 3 turns in 49 s. After: plan v10: needs people=1, out by 2:15; Van 1 confirmed, pickup at 0:23

### Ana (calls in, asks for the police, then hurts her leg): calls EMBER, sim 0:06
Before: not placed yet

- `  0.0s` **EMBER** (6.4 s): Hi, this is EMBER, an automated flood-response assistant for this live demo. How can I help?
- `  7.4s` *Ana*: Hi, can I join?
- ` 10.0s` **EMBER** (1029 ms, 14.8 s): You're Player 6, living by the corner of Banks Street and Flagg Street; the river reaches your street in about 144 minutes. How many people are with you, and does anyone need a wheelchair or medical help?
- ` 26.3s` *Ana*: It's just me.
- ` 28.9s` **EMBER** (1325 ms, 13.6 s): One moment... Van 1 picks you up in about 16 minutes. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Banks Street and Flagg Street.
- ` 44.0s` *Ana*: Help me, where is the police?
- ` 48.5s` **EMBER** (2149 ms, 18.8 s): One moment... I'm here with you. Responders are working the flood zone; for you the fastest help is Van 1, which gets to you in about 4 minutes. Be at the corner of Banks Street and Flagg Street with your medications and phone before it gets there.
- ` 69.3s` *Ana*: I hurt my leg and I can't move.
- ` 73.7s` **EMBER** (1207 ms, 10.0 s): We've got you: Accessible Van 3's crew knows someone is hurt and comes to your door in about 37 minutes. Keep the injured leg still.
- ` 85.2s` *Ana*: Okay, thank you.
- ` 86.4s` **EMBER** (1 ms, 4.4 s): You're welcome. I'll text you all of this now. Take care.
- after the call, by text: EMBER flood response, live demo. From our call: Your pickup changed because your household's needs changed. Accessible Van 3 is coming to your door in about 37 min. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and any walker or cane; the crew knows someone needs medical care. (plan v14)

Outcome: **updated**, 5 turns in 91 s. After: plan v14: needs people=1, mobility=True, medical=True, out by 2:15; Accessible Van 3 confirmed, pickup at 0:43

### Lee's texts
- `0:00` EMBER flood response, live demo. You're Player 4, living by the corner of Ballord Place and Putnam Avenue; the river reaches your street in about 150 min. We're calling you now.
- `0:02` We just tried to call you. The river reaches your street in about 148 min, so we're planning to pick you up. How many people are with you, and does anyone need a wheelchair or medical help? (plan v7)
- `0:02` Van 1 picks you up in about 15 min. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Ballord Place and Putnam Avenue. It picks up 2 other households first; you share the trip with 2 other households: it collects you all before the drop-off. (plan v8)
- `0:08` We just tried to call you. Your pickup changed because other households asked for pickups. Van 1 picks you up in about 8 min. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Ballord Place and Putnam Avenue. (plan v14)
- `0:14` We just tried to call you. Van 1 is 2 minutes away. Go to the corner of Ballord Place and Putnam Avenue now. (plan v14)
- `0:16` Van 1 is at the corner of Ballord Place and Putnam Avenue now. Tell the driver your address and that you are 2, then get in.
- `0:22` You're on board, on your way to David Rubenstein Treehouse (about 2 min). Stay with the crew; they'll take you inside.
- `0:24` You're checked in at David Rubenstein Treehouse, out of the flood area. Stay there until the all-clear; we'll text you if anything changes.
