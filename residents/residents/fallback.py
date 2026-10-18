"""When the one LLM call is unavailable (API down, usage limit, timeout): a small keyword parser for the replies a
drill actually needs, so a text or a call keeps working instead of answering "couldn't read that" forever.

It returns the same `Extraction` the model would, so everything after it is unchanged (`to_outcome`: a need
without a head count still asks "how many", a YES only counts if something was offered, ...). It only reads
what is unmistakable: "yes" / "no" / "done", "2 of us" / "just me" / "me and my mom", "wheelchair", a question's
topic by its key words, "<street> is flooded", "we'll be okay here" (the safety advice for staying), and urgency ("the water
is at our door", "we're trapped", "hurry", "help"). Anything else → None (the caller asks a specific question, never
a guess). Confidence is 0.8 for recognized facts. An unrecognized request for assistance asks for clarification
before publishing a pickup on the head count alone; clear urgency still reaches the intake.
"""

from __future__ import annotations

import re

from .extract import Extraction, Fact

NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_N = r"(\d+|" + "|".join(NUM) + r")"
YES = re.compile(r"^((oh|um+|uh+|well) )*(yes|yeah|yep|yup|sure|ok|okay|confirm(ed)?|sounds good|please do|y|correct|"
                 r"that works)\b(?!.*\bnot?\b)")  # "oh, yes, yes please" (heard on calls)
ACK = re.compile(r"^((oh|um+|uh+|well) )*(ok|okay)\b")  # "okay, what changed?": a nod, then the question
NO = re.compile(r"^(?:(?:no|nope|nah)(?: (?:no|nope|nah))*(?:$| (?:thanks?|thank you)\b)|cancel\b|decline\b|"
                r"(?:don't|do not) (?:send|come|pick|want)\b)")
REFUSAL = re.compile(r"\b(?:i|we) (?:don't|do not|won't|will not) (?:go|leave|evacuate|"
                     r"want (?:a |the |this |your )?(?:pickup|van|vehicle|ride|rescue)|take (?:the |a )?(?:van|bus|ride))\b|"
                     r"^no (?:we|i) want (?:to travel|another|a different)\b|\brefuses? to go\b")
STAY = re.compile(r"\b(stay(ing)? (put|here|home)|(we|i)'?re staying|(we|i)'?ll be (ok|okay|fine|alright))\b")
DONE = re.compile(r"\b(done|ready|(we'?re|i'?m|we are|i am) (here|outside)|at the corner|on the (van|truck|bus)|"
                  r"aboard|on board|arrived|checked in|it'?s connected|connected)\b")
COUNT = re.compile(r"\b" + _N + r"\s+(of us|people|persons?|adults|in total|total)\b")
SPOKEN_COUNT = re.compile(r"\b(?:we are|we're)\s+" + _N + r"\b(?!\s+(?:minutes?|mins?|hours?|years?|blocks?|miles?|km|meters?))")
ALONE = re.compile(r"\b(just me|only me|myself|i'?m alone|i am alone|just one)\b")
PAIR = re.compile(r"\b(me and my|my (?!house|home|place|apartment|room)\w+ and (i|me))\b")
CHAIR = re.compile(r"\b(wheel ?chair|walker|can'?t walk|cannot walk|bed ?ridden|mobility|help walking|crutches|accessible|stuck|can'?t get out)\b")
MEDICAL = re.compile(r"\b(oxygen|dialysis|insulin|medical|injur\w*|medications?|hurt|bleeding|broken|needle)\b")
# "nobody's hurt", "no one needs a wheelchair": the answer to first contact's question (D100) names what isn't there
NONE_OF = re.compile(r"\b(no ?one|nobody|none of us|not|isn'?t|aren'?t|don'?t|doesn'?t|no)\b(?:'s)?"
                     r"(?:\s+(?:is|are|was|were|needs?|requires?|has|have|uses?|using|an?|any|longer))*\s+"
                     r"(hurt|injur\w*|medical|medications?|oxygen|wheel ?chair|walker|bleeding|help walking|"
                     r"accessible(?: vehicle)?)\b")
STREET = re.compile(r"\b([a-z]+(?: [a-z]+)? (?:st|street|ave|avenue|rd|road|dr|drive|pl|place|sq|square|bridge))\b")
BLOCKED = re.compile(r"\b(flooded|blocked|closed|under water|impassable)\b")
GREETING = re.compile(r"^(hi|hello|hey|hiya|good (morning|afternoon|evening))\b")
URGENT = re.compile(r"\b(hurry|(?<!medical )help|trapped|water('s| is)? (at|under|by|coming (in(?: under| through)?|under|through)) (our|my|the) (front )?"
                    r"(door|house|home|apartment|basement|stairs)|(water|flooding|flooded)( is)? (inside|in (our|my|the) "
                    r"(house|home|apartment|basement)))\b")
NOT_URGENT = re.compile(r"\b(?:(?:no ?one|nobody|none of us) (?:needs?|requires?) (?:any )?help|"
                        r"(?:we|i) (?:don't|do not) need (?:any )?help|(?:no need to|don't|do not) hurry|"
                        r"(?:not|aren't|isn't) trapped)\b")
REQUESTED_AID = re.compile(r"\bneeds? (?:an?|some) ([\w']+)")
KNOWN_AID = {"wheelchair", "walker", "accessible", "van", "vehicle", "ride", "lift", "pickup", "rescue", "help", "hand",
             "oxygen", "medication", "medications", "insulin", "doctor", "ambulance", "medical", "stretcher", "crutches"}
_LEAD = {"is", "are", "the", "on", "at", "of", "a", "an", "near", "across", "get", "by", "to", "from", "via", "and"}
QUESTION = re.compile(r"\?|^(what|when|where|how|is|are|can|could|will|would|should|who|why|do|does|did)\b")
TOPICS = [  # first match wins
    ("plan", r"\b(plan|what (do|should) (i|we) do|what now|what happens|what'?s going on|what changed|is anyone coming|"
             r"status)\b"),
    ("safety", r"\b(safe|danger|dangerous|emergency|drown|water (is )?coming in)\b"),
    ("roads", r"\b(open|closed|blocked|passable|across|get through|cross)\b"),
    ("flood", r"\b(flood|water)\b"),
    ("bring", r"\b(bring|pack)\b"),
    ("destination", r"\bwhere\b.*\b(take|taking|going|shelter)\b"),
    ("pickup_place", r"\bwhere\b"),
    ("eta", r"\b(how long|when|what time|how soon|eta|minutes)\b"),
    ("vehicles", r"\b(van|vans|vehicle|vehicles|bus|car)\b"),
    ("others", r"\b(near me|neighbou?rs?|others|together|anyone else)\b"),
]


def _fact(kind: str, **kw) -> Fact:
    base = {k: None for k in ("people", "mobility", "accessible_vehicle", "medical", "road_hint", "cross_street",
                              "address", "endurance_min", "facility_state", "question_topic")}
    return Fact(kind=kind, **{**base, **kw})


def _street(t: str) -> str | None:
    m = STREET.search(t)
    if not m:
        return None
    words = m[1].split()
    while len(words) > 2 and words[0] in _LEAD:
        words = words[1:]
    return " ".join(words) if words[0] not in _LEAD else " ".join(words[1:]) or None


def _people(t: str) -> int | None:
    if (m := COUNT.search(t)):
        v = m[1]
        return int(v) if v.isdigit() else NUM[v]
    if (m := SPOKEN_COUNT.search(t)):
        v = m[1]
        return int(v) if v.isdigit() else NUM[v]
    if ALONE.search(t):
        return 1
    if PAIR.search(t):
        return 2
    if re.fullmatch(_N, t):  # a bare "3" answering "how many people"
        return int(t) if t.isdigit() else NUM[t]
    return None


def parse(text: str, role: str = "resident") -> Extraction | None:
    t = re.sub(r"[^\w' ?]+", " ", text.lower().replace("’", "'")).strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^(?:(?:um+|uh+|erm|er)\b\s*)+", "", t).strip()
    if not t:
        return None
    facts: list[Fact] = []
    if role == "operator":
        mins = re.search(_N + r"\s*(minutes?|mins?|hours?|hrs?)\b", t)
        state = ("down" if re.search(r"\b(no power|power is out|power'?s out|blackout|down)\b", t) else
                 "backup" if re.search(r"\b(backup|generator)\b", t) else
                 "ok" if re.search(r"\b(grid|power is back|back on)\b", t) else None)
        if mins or state:
            n = mins and (int(mins[1]) if mins[1].isdigit() else NUM[mins[1]])
            facts.append(_fact("facility_status", facility_state=state,
                               endurance_min=(n * 60 if mins and mins[2].startswith("h") else n) if mins else None))
    said = NONE_OF.sub(" ", t)  # what they say someone needs, without what they say nobody needs
    denied = " ".join(m[0] for m in NONE_OF.finditer(t))
    people, chair, med = _people(t), bool(CHAIR.search(said)), bool(MEDICAL.search(said))
    no_chair, no_med = bool(CHAIR.search(denied)), bool(MEDICAL.search(denied))
    accessible, no_accessible = bool(re.search("wheel|accessible", said)), bool(re.search("wheel|accessible", denied))
    if role != "operator" and (people or chair or med or no_chair or no_med):
        facts.append(_fact("need", people=people, mobility=True if chair else False if no_chair else None,
                           accessible_vehicle=True if accessible else False if no_accessible else None,
                           medical=True if med else False if no_med else None))
    if role != "operator" and not chair and not med and any(m[1] not in KNOWN_AID for m in REQUESTED_AID.finditer(said)):
        urgent = bool(URGENT.search(NOT_URGENT.sub(" ", t)))
        return Extraction(facts=[_fact("urgent")] if urgent else [], confidence=0.8,
                          clarifying_question="What assistance do you need, and how many people are with you?")
    if (street := _street(t)) and BLOCKED.search(t) and not QUESTION.search(t):
        facts.append(_fact("closure_report", road_hint=street))
    urgent = bool(URGENT.search(NOT_URGENT.sub(" ", t)))
    if not facts:
        if NO.search(t) or REFUSAL.search(t):
            facts.append(_fact("reject"))
        elif YES.search(t) and not (ACK.search(t) and QUESTION.search(t)):
            facts.append(_fact("confirm"))
        elif urgent:  # "no help has arrived" is news about the situation, never a declined pickup or a DONE
            facts.append(_fact("urgent"))
        elif DONE.search(t) and not re.search(r"\b(not|n't|isn't|aren't|haven't)\b|n't\b", t):
            facts.append(_fact("done"))
        elif STAY.search(t):  # "we're upstairs, we'll be okay" (no pickup cancelled on it): what to do if they stay
            facts.append(_fact("question", question_topic="safety"))
    if urgent and not any(f.kind in ("confirm", "reject", "urgent") for f in facts):
        facts.append(_fact("urgent"))
    if not facts and GREETING.search(t) and len(t.split()) <= 4:
        return Extraction(facts=[_fact("other")], confidence=0.8, clarifying_question=None)  # → their status / the plan's question
    if QUESTION.search(t) and not any(f.kind == "confirm" for f in facts):
        topic = "safety" if urgent else next((k for k, pat in TOPICS if re.search(pat, t)), "other")
        road = _street(t) if topic == "roads" else None
        facts.append(_fact("question", question_topic=topic, road_hint=road))
    return Extraction(facts=facts, confidence=0.8, clarifying_question=None) if facts else None
