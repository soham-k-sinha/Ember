"""A text message → the same words, said on a phone call (D74). Deterministic rewrites only: the call says
exactly what the thread would text, minus what only makes sense on a screen.

- the "[EMBER drill]" prefix, "Welcome to the EMBER flood drill." and "(plan vN)" tags (the call opens by saying who
  is calling, once);
- what a call has no time for (D80): examples in parentheses ("(e.g. 125 Western Ave)"), an offer's out-by time
  and the plan's reasons behind it ("It picks up 8 other households first; you share the trip with ..."), the
  "Step 1 of 4" labels and packing lists (the follow-up text has them), a pickup's destination, an ETA said twice, and
  asides like "or tell us what changed" or, before a new offer in the same turn, "tell me if you change your mind";
- "Reply YES / NO / DONE" → "Say yes / no / done", "reply with / send your" → "tell me", "we'll text you" →
  "we'll let you know", "text us" → "tell us";
- street suffixes ("Western Ave" → "Western Avenue", "N Harvard St" → "North Harvard Street");
- units ("12 min" → "12 minutes", "120 m" → "120 meters", "m³"), "#10296" → "number 10296", "911" → "9 1 1"
  (said as digits, never "nine hundred eleven"), "e.g." → "for example".
"""

from __future__ import annotations

import re

_SUFFIX = {"St": "Street", "Ave": "Avenue", "Av": "Avenue", "Rd": "Road", "Dr": "Drive", "Pl": "Place",
           "Blvd": "Boulevard", "Sq": "Square", "Pkwy": "Parkway", "Ct": "Court", "Ln": "Lane", "Ter": "Terrace"}
_DIR = {"N": "North", "S": "South", "E": "East", "W": "West"}


def _case(word: str, like: str) -> str:
    return word[0].upper() + word[1:] if like[:1].isupper() else word


_RULES: list[tuple[re.Pattern, object]] = [
    (re.compile(r"\[EMBER drill\]\s*"), ""),
    (re.compile(r"Welcome to the EMBER flood drill\.\s*"), ""),
    (re.compile(r"\s*\(e\.g\.[^)]*\)"), ""),
    (re.compile(r"\s*\b(?:It picks up|You share the trip)\b[^.]*\."), ""),
    (re.compile(r";\s*(?:it picks up|you share the trip)\b[^.]*"), ""),
    (re.compile(r"\s*Plan to be out within about \d+ min, before the water reaches your street\."), ""),
    (re.compile(r"\s*\(plan v\d+\)"), ""),
    (re.compile(r"\bStep \d+ of \d+: "), ""),
    (re.compile(r"Pack medications, ID, your phone and charger, then (\w)"), lambda m: m[1].upper()),
    (re.compile(r"\s*Get medications, ID, [^.]*\."), ""),
    (re.compile(r"Bring medications \(and prescriptions\), [^.]*\."), "Bring medications, ID and your phone."),
    (re.compile(r"Confirmed: (.+?) is coming to you\. (?=.*\b\1 gets there)"), "Confirmed. "),
    (re.compile(r"(\b([A-Z][\w ]*?) is arriving (in about \d+ min)\b.*?)\s*\2 gets there \3\."), r"\1"),
    (re.compile(r" and take you to [^.]+(?=\.)"), ""),
    (re.compile(r"; we need a few details to send the right vehicle|Please tell us: |, or tell us what changed"), ""),
    (re.compile(r": 6 inches of moving water [^.]*\."), "."),
    (re.compile(r"\s*Reply here if you change your mind\.(?=.*\bReply YES\b)"), ""),
    (re.compile(r"\b([Rr])eply (YES|NO|DONE)\b"), lambda m: _case("say", m[1]) + " " + m[2].lower()),
    (re.compile(r"\b(YES|NO|DONE)\b"), lambda m: m[1].lower()),
    (re.compile(r"\b([Rr])eply (?:with|here)\b"), lambda m: _case("tell me", m[1])),
    (re.compile(r"\b([Ss])end (your|a|an|the two) (street address|address|intersection|nearest|cross streets)"),
     lambda m: _case("tell me", m[1]) + f" {m[2]} {m[3]}"),
    (re.compile(r"\b([Ww]e'll|[Ww]e will|will) text you\b"), r"\1 let you know"),
    (re.compile(r"\b([Tt])ext us\b"), lambda m: _case("tell", m[1]) + " us"),
    (re.compile(r"\be\.g\.\s*"), "for example, "),
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
