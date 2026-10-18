# Eval: does a misread text change who gets out in time? (D83)

The one LLM step turns a text into facts. We grade it with the simulator, not by field accuracy alone. For each of
the 51 messages in `residents/tests/samples.json` (drill texts, operator reports, a real phone call), the same
deterministic code (`to_outcome`) turns the gold reading and the extractor's reading into reports. Both start from
the same seeded plan: allston_flood_v1 v1, with the judge's household known as 3 people at t = 10 min. The planner
replans on each set of reports, and both plans are simulated in the gold world. A message **passes** when:

- the household is still picked up before its flood deadline whenever the gold plan picks it up (the simulator only
  boards a wheelchair user onto an accessible vehicle);
- it causes no regret, that is, extracted minus gold is 0 or less for people unreached, hospital outage and sewage overflow.

**ASK** means the extraction asked instead of guessing, or read nothing, in which case the backend asks the plan's
open question. An ASK is safe, but it is not counted as a pass.

```
cd residents && uv run python scripts/eval_sim.py                  # --extractor fallback (default, no network)
cd residents && uv run python scripts/eval_sim.py --extractor llm  # the real model (paid API)
```

## Claude Sonnet 5.5 through Chalk's Model Gateway (what runs on stage)

**50/51 pass (98 %), 1 asked instead of guessing, 0 fail, so 100 % are safe.** Measured 2026-10-18 with
`--extractor llm`, every call routed through Chalk's Model Gateway (`anthropic/claude-sonnet-5-5`, structured
output, about 2.5 s per text). The one ASK is #32 "we need a Welch's": the model asks what was meant instead of
guessing, as D76 tells it to.

## D75 keyword parser (what runs when the model is down)

**46/51 pass (90 %), 4 asked instead of guessing, 1 fail, so 98 % are safe.** The run is deterministic: two runs
gave identical tables. It takes about 18 s with the engine's default search budget.

- **Fail, #32** "4 people and we need a Welch's": "Welch's" is an autocorrected "wheelchair". The parser plans a
  standard van, and the simulator can't board the wheelchair user (+4 people unreached). The model is told to ask
  about garbled words (D76). The parser can't do that, so this fail stays.
- **The eval found two parser bugs, both now fixed** in `residents/fallback.py`:
  - #47 "I'm stuck in my house and I can't get out" was read as 2 people ("my house and I") with no mobility need.
    A standard van came, and the household was left behind (+3 unreached).
  - #3 "we need an accessible vehicle" dropped the need (+3).

  Both messages now pass, and each has a test case.
- The ASK rows lose nothing. They are a closure the parser can't place, "thanks", and two locations (the drill
  reads locations in a separate step).

Households, needs,
deadlines and scenario timing are synthetic drill data (`scenarios/allston_flood_v1`).

```
 #  role      message                                   extracted                 vehicle  reached  Δunreached  Δoutage_min  Δoverflow_m3  result
 1  resident  there are 3 of us here, nobody needs he…  need                      van-2    yes              +0           +0            +0  PASS
 2  resident  Me and my mom. She's in a wheelchair      need                      van-3    yes              +0           +0            +0  PASS
 3  resident  we need an accessible vehicle, and the …  need,closure_report       van-3    yes              +0           +0            +0  PASS
 4  resident  River St is completely flooded near Mem…  closure_report            van-2    yes              +0           +0            +0  PASS
 5  resident  just me, I use a walker and I'm on oxyg…  need                      van-3    yes              +0           +0            +0  PASS
 6  resident  4 people incl 2 kids, we're fine to wal…  need                      van-2    yes              +0           +0            +0  PASS
 7  resident  yes                                       confirm                   van-2    yes              +0           +0            +0  PASS
 8  resident  no we can't leave, my dad refuses to go   reject                    van-1    -                +0           +0            +0  PASS
 9  resident  is the western ave bridge still open?     question                  van-2    yes              +0           +0            +0  PASS
10  resident  hi                                        other                     van-2    yes              +0           +0            +0  PASS
11  resident  2                                         need                      van-3    yes              +0           +0            +0  PASS
12  resident  water is coming up Western Avenue by th…  (none)                    van-2    yes              +0           +0            +0  ASK
13  resident  we have a dialysis patient here, 2 adul…  need                      van-2    yes              +0           +0            +0  PASS
14  resident  thanks!!                                  (none)                    van-2    yes              +0           +0            +0  ASK
15  operator  about 6 hours of diesel left on the bac…  facility_status           -        -                +0           +0            +0  PASS
16  operator  grid power just went out, we're on back…  facility_status           -        -                +0           +0            +0  PASS
17  operator  We lost everything, the whole site is d…  facility_status           -        -                +0           +0            +0  PASS
18  operator  power is back on, we're on the grid aga…  facility_status           -        -                +0           +0            +0  PASS
19  operator  how long until the generator truck gets…  facility_status,question  -        -                +0           +0            +0  PASS
20  operator  ok will do                                confirm                   -        -                +0           +0            +0  PASS
21  operator  Mount Auburn facilities: we lost grid p…  facility_status           -        -                +0           +0            +0  PASS
22  resident  I'm at 125 Western Ave                    (none)                    van-2    yes              +0           +0            +0  ASK
23  resident  corner of Putnam Ave and Western Ave      (none)                    van-2    yes              +0           +0            +0  ASK
24  resident  125 Western Ave, my mom uses a wheelcha…  need                      van-3    yes              +0           +0            +0  PASS
25  resident  hi                                        other                     van-2    yes              +0           +0            +0  PASS
26  resident  we're at the corner now                   done                      van-2    yes              +0           +0            +0  PASS
27  resident  ok we're on the van                       confirm                   van-2    yes              +0           +0            +0  PASS
28  resident  HOW MUCH TIME                             question                  van-2    yes              +0           +0            +0  PASS
29  resident  no, we want to travel with others, is t…  reject                    van-1    -                +0           +0            +0  PASS
30  resident  are there any other vans?                 question                  van-2    yes              +0           +0            +0  PASS
31  resident  where do we meet the van?                 question                  van-2    yes              +0           +0            +0  PASS
32  resident  4 people and we need a Welch's            need                      van-2    NO               +4           +0            +0  FAIL
33  resident  what’s the plan?                          question                  van-2    yes              +0           +0            +0  PASS
34  resident  what to do?                               question                  van-2    yes              +0           +0            +0  PASS
35  resident  what happens now?                         question                  van-2    yes              +0           +0            +0  PASS
36  resident  is anyone coming for us?                  question                  van-2    yes              +0           +0            +0  PASS
37  resident  where is the flood happening              question                  van-2    yes              +0           +0            +0  PASS
38  resident  will the water reach my street?           question                  van-2    yes              +0           +0            +0  PASS
39  resident  is River St open?                         question                  van-2    yes              +0           +0            +0  PASS
40  resident  can we still get across the Western Ave…  question                  van-2    yes              +0           +0            +0  PASS
41  resident  is it safe to drive to my sister's plac…  question                  van-2    yes              +0           +0            +0  PASS
42  resident  water is coming in under the door, what…  question                  van-2    yes              +0           +0            +0  PASS
43  resident  who is running this drill?                question                  van-2    yes              +0           +0            +0  PASS
44  resident  can I bring my cat?                       question                  van-2    yes              +0           +0            +0  PASS
45  resident  what should I pack?                       question                  van-2    yes              +0           +0            +0  PASS
46  resident  Um, we are three people, and no one nee…  need                      van-3    yes              +0           +0            +0  PASS
47  resident  No, uh, that's not okay because I'm cur…  need                      van-3    yes              +0           +0            +0  PASS
48  resident  No, um, actually, I'm injured right now…  need                      van-3    yes              +0           +0            +0  PASS
49  resident  no thanks, we'll drive ourselves to my …  reject                    van-1    -                +0           +0            +0  PASS
50  resident  No.                                       reject                    van-1    -                +0           +0            +0  PASS
51  resident  no, it's actually 4 of us                 need                      van-2    yes              +0           +0            +0  PASS

46/51 pass (90%), 4 asked instead of guessing, 1 fail · safe (pass or ask) 98%
```

## Expanded fallback check — 2026-10-18 (D102)

The sample set now has 56 messages, adding urgency and scoped negative-needs cases. The grader also requires urgency to match and no longer labels a harmful partial report as a safe clarification. `scripts/eval_sim.py --extractor fallback --moves 10`: **50 pass, 6 clarification, 0 fail; 56/56 urgency matches**. Unknown assistance is clarified before publishing a pickup. This local development run used ten allocator moves. The paid-model numbers above used the original 51-message set and previous scoring; they have not been rerun or revalidated under these checks.
