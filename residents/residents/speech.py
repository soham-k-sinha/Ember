"""A text message → the same words, said on a phone call (D74). Deterministic rewrites only: the call says
exactly what the thread would text, minus what only makes sense on a screen. At most two short sentences a turn
is the aim (D100): the texts are written that way, and this drops what a call has no time for.

- the texts' one-line notice and "(plan vN)" tags (a call says who is calling itself, D100);
- the coordinators: a call never names them (D111; a question the plan can't answer gets its answer from talk.py);
- what a call has no time for (D80): examples in parentheses ("(e.g. 125 Western Ave)"), the plan's reasons behind a
  pickup ("Accessible Van 3 is the only wheelchair-accessible vehicle that fits 4 people; it picks up 8 other households
  first; you share the trip with ..."), how long the walk takes, the full packing list of a question's answer and a
  pickup's destination (the follow-up text has them);
- asks, as a person would make them: "reply with / send your" → "tell me", "Reply YES / NO" → "Say yes / no",
  "we'll text you" → "we'll let you know", "text us" → "tell us";
- "Utility truck" → "the utility truck";
- street suffixes ("Western Ave" → "Western Avenue", "N Harvard St" → "North Harvard Street");
- units ("12 min" → "12 minutes", "120 m" → "120 meters", "m³"), "#10296" → "number 10296", "911" → "9 1 1"
  (said as digits, never "nine hundred eleven"), "e.g." → "for example".
"""

from __future__ import annotations

import re

from .messaging import DISCLOSURE

_SUFFIX = {"St": "Street", "Ave": "Avenue", "Av": "Avenue", "Rd": "Road", "Dr": "Drive", "Pl": "Place",
           "Blvd": "Boulevard", "Sq": "Square", "Pkwy": "Parkway", "Ct": "Court", "Ln": "Lane", "Ter": "Terrace"}
_DIR = {"N": "North", "S": "South", "E": "East", "W": "West"}


def _case(word: str, like: str) -> str:
    return word[0].upper() + word[1:] if like[:1].isupper() else word


_RULES: list[tuple[re.Pattern, object]] = [
    (re.compile(re.escape(DISCLOSURE) + r"\s*"), ""),
    (re.compile(r"Our plan doesn't cover that, [^.]*\.(?: Meanwhile, here's where you stand:)?\s*"), ""),
    (re.compile(r"\s*A coordinator can see the request to travel together\."), ""),
    (re.compile(r"a coordinator has been told"), "we're working on it"),
    (re.compile(r"a coordinator is looking at it and will text you"), "we're on it and will let you know"),
    (re.compile(r"\s*\(e\.g\.[^)]*\)"), ""),
    (re.compile(r"\s*\b[A-Z][\w ]*? is the only [\w-]+ ?vehicle that fits [^.;]*[.;]"), ""),
    (re.compile(r"\s*\b(?:It picks up|it picks up|You share the trip|you share the trip)\b[^.]*\."), ""),
    (re.compile(r";\s*(?:it picks up|you share the trip)\b[^.]*"), ""),
    (re.compile(r"\s*\(plan v\d+\)"), ""),
    (re.compile(r"\s*\(about \d+ min on foot\)"), ""),
    (re.compile(r"Bring medications \(and prescriptions\), [^.]*\."), "Bring medications, ID and your phone."),
    (re.compile(r" and take you to [^.]+(?=\.)"), ""),
    (re.compile(r": 6 inches of moving water [^.]*\."), "."),
    (re.compile(r"\b([Rr])eply (YES|NO|DONE)\b"), lambda m: _case("say", m[1]) + " " + m[2].lower()),
    (re.compile(r"\b(YES|NO|DONE)\b"), lambda m: m[1].lower()),
    (re.compile(r"who will reply here\b"), "who will get back to you"),
    (re.compile(r"\b([Rr])eply (?:with|here)\b"), lambda m: _case("tell me", m[1])),
    (re.compile(r"\b([Ss])end (your|a|an|the two) (street address|address|intersection|nearest|cross streets)"),
     lambda m: _case("tell me", m[1]) + f" {m[2]} {m[3]}"),
    (re.compile(r"\b([Ww]e'll|[Ww]e will|will) text you\b"), r"\1 let you know"),
    (re.compile(r"\b([Tt])ext us\b"), lambda m: _case("tell", m[1]) + " us"),
    (re.compile(r"\be\.g\.\s*"), "for example, "),
    (re.compile(r"(^|[.:;] )Utility truck\b"), r"\1The utility truck"),
    (re.compile(r"\bUtility truck\b"), "the utility truck"),
    (re.compile(r"\b(N|S|E|W) (?=[A-Z][a-z])"), lambda m: _DIR[m[1]] + " "),
    (re.compile(r"(?<=[A-Za-z]) (" + "|".join(_SUFFIX) + r")\b\.?"), lambda m: " " + _SUFFIX[m[1]]),
    (re.compile(r"(\d[\d,]*) m³"), r"\1 cubic meters"),
    (re.compile(r"\b1 min\b"), "1 minute"),
    (re.compile(r"(\d) min\b"), r"\1 minutes"),
    (re.compile(r"(\d) m\b"), r"\1 meters"),
    (re.compile(r"(\d) km\b"), r"\1 kilometers"),
    (re.compile(r"#(\d+)"), r"number \1"),
    (re.compile(r"\b911\b"), "9 1 1"),
    (re.compile(r"\s*·\s*"), ", "),
    (re.compile(r"\s{2,}"), " "),
]


def render(text: str) -> str:
    """What the call says for one outbound text."""
    for pat, rep in _RULES:
        text = pat.sub(rep, text)
    return text.strip()


def render_all(texts: list[str]) -> str:
    """One turn's texts, said as one."""
    return render(" ".join(texts))
