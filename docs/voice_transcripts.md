# EMBER on the phone: calls first (simulated)

Written by `residents/scripts/sim_calls.py` (D99): the real planner on the Allston flood (40 scenario households plus
the players), the clock moved a minute at a time. A player who joins is called right away; EMBER calls again for the
pickup that changed and "2 minutes away"; everything else goes out as one short text after the call, on the plan's
clock, with no YES or DONE needed. At most 3 calls at once, earliest flood deadline first; a missed call is tried once
more 2 sim-min later, then texted. **Synthetic:** the people, their words, the flood timing, the fleet. No model: the
keyword parser reads every reply. Speech at 150 words a minute; "ms" is EMBER's reply time (a replan when needs change).

### Maria (74, her mother uses a wheelchair and oxygen): EMBER calls, first contact, sim 0:00
Before: plan v4: needs unknown, out by 1:15; no vehicle

- `  0.0s` **EMBER** (16.4 s): This is EMBER, an automated assistant in a live flood simulation. The river reaches Soldiers Field Road in about 90 minutes. How many people are with you, and is anyone hurt, in a wheelchair, or in need of oxygen or medication?
- ` 19.4s` *Maria*: Hello?
- ` 19.8s` **EMBER** (13 ms, 9.2 s): Hi, it's EMBER. How many people are with you, and is anyone hurt, in a wheelchair, or in need of oxygen or medication?
- ` 31.0s` *Maria*: It's me and my mother. She's in a wheelchair and she needs her oxygen.
- ` 37.5s` **EMBER** (880 ms, 14.0 s): Accessible Van 3 is coming to your door in about 15 minutes. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care.
- ` 53.5s` *Maria*: Okay. Thank you.
- ` 54.7s` **EMBER** (1 ms, 4.4 s): You're welcome. I'll text you all of this now. Take care.
- after the call, by text: From our call: Accessible Van 3 is coming to your door in about 15 min. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care. (plan v5)

Outcome: **updated**, 3 turns in 59 s. After: plan v5: needs people=2, mobility=True, accessible_vehicle=True, medical=True, out by 1:15; Accessible Van 3 confirmed, pickup at 0:15

### Dev (the live call's turns, re-sent and revised the way ElevenLabs posted them): EMBER calls, first contact, sim 0:00
Before: plan v5: needs unknown, out by 1:15; no vehicle

- `  0.0s` **EMBER** (16.4 s): This is EMBER, an automated assistant in a live flood simulation. The river reaches Soldiers Field Road in about 90 minutes. How many people are with you, and is anyone hurt, in a wheelchair, or in need of oxygen or medication?
- ` 17.4s` *Dev*: Um, there are four of us, and one needs a wheelchair.
- ` 22.7s` **EMBER** (936 ms, 10.0 s): Accessible Van 3 is coming to your door in about 15 minutes. Be ready at the door with medications, ID, your phone and the wheelchair.
- ` 34.7s` *Dev*: A walker.
- ` 35.6s` **EMBER** (34 ms, 4.8 s): Got it. Accessible Van 3 gets to you in about 15 minutes.
- ` 40.9s` *Dev*: A walker. I need my ankle. _(revised)_
- ` 43.3s` **EMBER** (33 ms, 4.8 s): Got it. Accessible Van 3 gets to you in about 15 minutes.
- ` 48.6s` *Dev*: A walker. I need my needle. _(revised)_
- ` 51.9s` **EMBER** (901 ms, 14.8 s): Got it. Accessible Van 3 is coming to your door in about 15 minutes. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care.
- ` 68.7s` *Dev*: I'm done.
- ` 69.5s` **EMBER** (32 ms, 4.4 s): Thanks. Accessible Van 3 gets to you in about 15 minutes.
- ` 74.4s` *Dev*: I'm done. Okay, done. _(revised)_
- ` 76.1s` **EMBER** (31 ms, 4.4 s): Thanks. Accessible Van 3 gets to you in about 15 minutes.
- ` 81.0s` *Dev*: A walker. I need my needle. _(re-sent)_
- ` 83.4s` **EMBER** (1 ms): the same reply again, not processed again
- ` 83.9s` *Dev*: I'm done. _(re-sent)_
- ` 84.7s` **EMBER** (1 ms): the same reply again, not processed again
- ` 85.2s` *Dev*: I'm done. _(re-sent)_
- ` 86.0s` **EMBER** (1 ms): the same reply again, not processed again
- after the call, by text: From our call: Accessible Van 3 is coming to your door in about 15 min. Be ready at the door with medications, prescriptions, any oxygen, ID, your phone and the wheelchair; the crew knows someone needs medical care. (plan v7)

Outcome: **updated**, 6 turns in 86 s. After: plan v7: needs people=4, mobility=True, accessible_vehicle=True, medical=True, out by 1:15; Accessible Van 3 confirmed, pickup at 0:15

### Jordan (calls the number, joins by voice): calls EMBER, sim 0:04
Before: not placed yet

- `  0.0s` **EMBER** (6.0 s): This is EMBER, an automated assistant in a live flood simulation. How can I help?
- `  7.0s` *Jordan*: Hi, I saw the flood sign. Can I join?
- ` 11.5s` **EMBER** (918 ms, 16.8 s): You're Player 5, living by the corner of Elmer Street and Hingham Street; the river reaches your street in about 146 minutes. How many people are with you, and is anyone hurt, in a wheelchair, or in need of oxygen or medication?
- ` 29.8s` *Jordan*: Just me.
- ` 31.6s` **EMBER** (998 ms, 12.8 s): Van 1 picks you up in about 19 minutes. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Elmer Street and Hingham Street.
- ` 45.4s` *Jordan*: Thanks, bye.
- ` 46.2s` **EMBER** (1 ms, 4.4 s): You're welcome. I'll text you all of this now. Take care.
- after the call, by text: EMBER flood simulation, live demo, not a real emergency. From our call: Van 1 picks you up in about 19 min. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Elmer Street and Hingham Street. (plan v10)

Outcome: **updated**, 3 turns in 51 s. After: plan v10: needs people=1, out by 2:15; Van 1 confirmed, pickup at 0:23

### Lee's texts
- `0:00` EMBER flood simulation, live demo, not a real emergency. You're Player 4, living by the corner of Ballord Place and Putnam Avenue; the river reaches your street in about 150 min. We're calling you now.
- `0:02` We just tried to call you. The river reaches your street in about 148 min, so we're planning to pick you up. How many people are with you, and is anyone hurt, in a wheelchair, or in need of oxygen or medication? (plan v7)
- `0:02` Van 1 picks you up in about 15 min. Pack medications, ID and your phone, then go out to the pickup point right outside: the corner of Ballord Place and Putnam Avenue. It picks up 2 other households first; you share the trip with 2 other households: it collects you all before the drop-off. (plan v8)
- `0:15` We just tried to call you. Van 1 is 2 minutes away. Go to the corner of Ballord Place and Putnam Avenue now. (plan v10)
- `0:17` Van 1 is at the corner of Ballord Place and Putnam Avenue now. Tell the driver your address and that you are 2, then get in.
- `0:23` You're on board, on your way to David Rubenstein Treehouse (about 8 min). Stay with the crew; they'll take you inside.
- `0:31` You're checked in at David Rubenstein Treehouse, out of the flood area. Stay there until the all-clear; we'll text you if anything changes.
