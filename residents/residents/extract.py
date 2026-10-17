"""The ONLY LLM call in EMBER: one inbound text → structured facts (report.schema.json payloads).

The model reads the text plus the thread's context (role, household/facility record, the last thing we
sent, any half-finished fact we're waiting on) and returns a typed `Extraction` via structured outputs.
It never produces routes, times, ETAs or assignments; those come from the allocator.

Everything after the model is deterministic code:
- confidence < CONFIDENCE_MIN, or a fact missing what the planner needs → one clarifying question,
  never a guess (e.g. a need without a head count is held as `pending` until the reply);
- street names → town edge ids near the household (`resolve_closure`); no match → ask which street;
- endurance minutes → backup_endurance_s (minutes, not hours: 10 min as hours rounds to 0.17 h = 612 s).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

log = logging.getLogger("residents.extract")

MODEL = os.environ.get("EXTRACT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("EXTRACT_EFFORT", "low")
CONFIDENCE_MIN = 0.6

Kind = Literal["need", "closure_report", "facility_status", "location", "done", "confirm", "reject", "question", "other"]


class Fact(BaseModel):
    """One fact in the message. Fields that the message doesn't state are null, never inferred."""
    kind: Kind
    people: int | None = Field(description="need: how many people need pickup, only if stated or clearly implied (e.g. 'me and my wife' = 2)")
    mobility: bool | None = Field(description="need: someone can't walk far / uses a wheelchair, walker, is bedridden")
    accessible_vehicle: bool | None = Field(description="need: they need a wheelchair-accessible vehicle")
    medical: bool | None = Field(description="need: a medical condition needing care (oxygen, dialysis, insulin, injury)")
    road_hint: str | None = Field(description="closure_report: the blocked street's name as written, e.g. 'River St'; null if not named")
    cross_street: str | None = Field(description="closure_report / location: a cross street or landmark that locates it")
    address: str | None = Field(description="location: where the sender is, as written: a street address ('125 Western Ave'), "
                                            "one street of an intersection ('Western Ave'), a landmark, or coordinates")
    endurance_min: float | None = Field(description="facility_status: MINUTES of backup power/fuel left, e.g. '10 minutes' = 10, '6 hours' = 360")
    facility_state: Literal["ok", "backup", "down"] | None = Field(
        description="facility_status: ok = on grid power, backup = running on backup/generator, down = no power / not operating")
    question_topic: Literal["eta", "pickup_place", "destination", "others", "vehicles", "bring", "other"] | None = Field(
        description="question: eta = when / how long; pickup_place = where to go or wait; destination = where they'll be "
                    "taken; others = other people near them / travelling together / neighbours; vehicles = which vehicles "
                    "are free, why this one, other options; bring = what to pack; other = anything else")


class Extraction(BaseModel):
    facts: list[Fact] = Field(description="Every distinct fact in the message, in order. Usually one.")
    confidence: float = Field(description="0-1: how sure you are that the facts are exactly what the sender meant")
    clarifying_question: str | None = Field(
        description="If something the coordinator needs is missing or ambiguous: ONE short question to ask back. Else null.")


SYSTEM = """You read text messages sent to EMBER, a flood-response coordination drill in Allston/Cambridge, and turn each message into structured facts. You only extract what the sender said; you never invent facts, plan routes, promise times, or decide who gets picked up.

Fact kinds:
- need: who needs pickup and what they need (people count, mobility, wheelchair-accessible vehicle, medical).
- closure_report: a road or street is flooded/blocked. Copy the street name as written into road_hint; a cross street or landmark into cross_street.
- facility_status: an operator reports their site's power state or how long backup power/fuel lasts.
- location: where the sender is right now (an address, an intersection, a landmark, coordinates). Copy it as written into address; for an intersection put one street in address and the other in cross_street.
- done: they report finishing the step we last asked them to do ("done", "we're at the corner", "on the van", "we've arrived", "it's connected").
- confirm: yes / accepting the instruction we last sent. reject: no / can't do it / declining it.
- question: they ask something; set question_topic. other: anything else (greetings, thanks, chatter).

Rules:
- Leave a field null unless the message states it or makes it unambiguous ("me and my mom" = 2 people; "she uses a wheelchair" = mobility and accessible_vehicle true).
- A short reply like "3" or "yes" answers the last message we sent or the pending question; use that context.
- One message can hold several facts (e.g. a need and a closure_report). "No, we want to travel with others, is anyone near me?" is a reject AND a question (topic others).
- If a word looks garbled or autocorrected (e.g. "we need a Welch's"), don't drop it or guess: ask about it in clarifying_question.
- If the facts are ambiguous or something essential is missing (a need with no head count, a closure with no street name), set clarifying_question to ONE short, plain question. Otherwise leave it null.
- confidence reflects how certain you are of the facts, not how urgent they are."""


# ---------- the call ----------
LLM = Callable[[str, str], Awaitable[Extraction]]  # (system, user) → Extraction


def make_llm(api_key: str, model: str = MODEL, effort: str = EFFORT, timeout_s: float = 30.0) -> LLM:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=2)

    async def call(system: str, user: str) -> Extraction:
        resp = await client.beta.messages.parse(
            model=model, max_tokens=4000, system=system,
            messages=[{"role": "user", "content": user}],
            output_format=Extraction, output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise ExtractionFailed(f"model returned no extraction (stop_reason={resp.stop_reason})")
        return resp.parsed_output

    return call


class ExtractionFailed(RuntimeError):
    pass


def build_prompt(text: str, role: str, record: dict, last_outbound: str | None, pending: dict | None) -> str:
    ctx: dict[str, Any] = {"sender_role": role, "record": record}
    if last_outbound:
        ctx["last_message_we_sent"] = last_outbound
    if pending:
        ctx["waiting_on_answer_for"] = pending
    return f"Context:\n{json.dumps(ctx, indent=1)}\n\nMessage:\n{text}"


# ---------- deterministic post-processing ----------
@dataclass
class Outcome:
    """What the backend does with one message."""
    reports: list[dict] = field(default_factory=list)  # ready for planner.submit_report (no id/observed_at yet)
    question: str | None = None                        # send back, one per message at most
    question_is_missing_info: bool = False             # True: a fact was incomplete; False: the model's own prompt
    pending: dict | None = None                        # partial need to remember for the next reply
    clear_pending: bool = False
    location: dict | None = None                       # {"address", "cross_street"}: where they say they are
    topics: list[str] = field(default_factory=list)    # question topics, answered from the plan (briefing.py)
    follow_up: str | None = None                       # the model's own question next to a need ("Did you mean…?")
    step_done: bool = False                            # they finished the step we last asked for


RoadResolver = Callable[[str, str | None, int | None], list[int]]  # (road_hint, cross_street, household_id) → edge ids


NEED_FIELDS = ("people", "mobility", "accessible_vehicle", "medical")


def to_outcome(ex: Extraction, *, role: str, thread: dict, text: str, pending: dict | None,
               resolve_road: RoadResolver, last_assignment_id: str | None, known_needs: dict | None = None) -> Outcome:
    """`known_needs` = the household's needs as the planner currently has them. A need report replaces
    them wholesale in the engine, so fields this message doesn't state keep their known values
    ("Yes, 2 people" after "my mom uses a wheelchair" must not drop the wheelchair)."""
    out = Outcome()
    hid = thread.get("household_id")
    fid = thread.get("facility_id")
    source = "resident" if role == "resident" else "operator"
    if ex.confidence < CONFIDENCE_MIN:
        out.question = ex.clarifying_question or "Sorry, could you say that another way?"
        return out
    asked: list[str] = []
    for f in ex.facts:
        if f.kind == "need" and hid is not None:
            fields = {k: getattr(f, k) for k in NEED_FIELDS}
            if pending and pending.get("kind") == "need":  # the reply completes what we were waiting on
                fields = {k: (fields[k] if fields[k] is not None else pending.get(k)) for k in fields}
                out.clear_pending = True
            if isinstance(known_needs, dict):                # stated now > pending > already known
                fields = {k: (fields[k] if fields[k] is not None else known_needs.get(k)) for k in fields}
            if not fields["people"] or fields["people"] < 1:
                out.pending = {"kind": "need", **{k: v for k, v in fields.items() if v is not None}}
                asked.append("How many people need to be picked up, including you?")
                continue
            payload = {k: v for k, v in fields.items() if v is not None}
            out.reports.append({"source": source, "kind": "need", "household_id": hid, "payload": payload,
                                "confidence": ex.confidence, "text": text})
        elif f.kind == "closure_report":
            if not f.road_hint:
                asked.append("Which street is blocked, and near which cross street?")
                continue
            edges = resolve_road(f.road_hint, f.cross_street, hid)
            if not edges:
                asked.append(f"We couldn't place \"{f.road_hint}\" on our map. Which cross street is it near?")
                continue
            out.reports.append({"source": source, "kind": "closure_report", "confidence": ex.confidence, "text": text,
                                "payload": {"edge_ids": edges, "road_hint": f.road_hint,
                                            **({"cross_street": f.cross_street} if f.cross_street else {})}})
        elif f.kind == "facility_status" and fid is not None:
            fields: dict[str, Any] = {}
            if f.endurance_min is not None and f.endurance_min >= 0:
                fields["backup_endurance_s"] = round(f.endurance_min * 60)
            if f.facility_state is not None:
                fields["state"] = f.facility_state
            if not fields:
                asked.append("How many hours of backup power do you have left?")
                continue
            out.reports.append({"source": "operator", "kind": "facility_status", "facility_id": fid, "payload": {"set": fields},
                                "confidence": ex.confidence, "text": text})
        elif f.kind in ("confirm", "reject"):
            if last_assignment_id is None:  # nothing was offered on this thread: it's just chatter
                continue
            out.reports.append({"source": source, "kind": f.kind, "assignment_id": last_assignment_id,
                                **({"household_id": hid} if hid is not None else {}),
                                **({"facility_id": fid} if fid is not None else {}),
                                "confidence": ex.confidence, "text": text})
        elif f.kind == "location" and f.address:
            out.location = {"address": f.address, "cross_street": f.cross_street}
        elif f.kind == "done":
            out.step_done = True
        elif f.kind == "question":
            out.topics.append(f.question_topic or "other")
            out.reports.append({"source": source, "kind": "question", "confidence": ex.confidence, "text": text,
                                **({"household_id": hid} if hid is not None else {}),
                                **({"facility_id": fid} if fid is not None else {})})
    if asked:
        out.question = ex.clarifying_question if (ex.clarifying_question and len(asked) > 1) else asked[0]
        out.question_is_missing_info = True
    elif ex.clarifying_question and not out.reports:
        out.question = ex.clarifying_question
    elif ex.clarifying_question and any(r["kind"] == "need" for r in out.reports):
        out.follow_up = ex.clarifying_question  # e.g. "we need a Welch's": plan on what's clear, ask about the rest
    return out


async def extract(llm: LLM, text: str, *, role: str, thread: dict, record: dict, last_outbound: str | None,
                  pending: dict | None, resolve_road: RoadResolver, last_assignment_id: str | None) -> Outcome:
    ex = await llm(SYSTEM, build_prompt(text, role, record, last_outbound, pending))
    log.info("extracted %s (confidence %.2f) from %r", [f.kind for f in ex.facts], ex.confidence, text[:80])
    return to_outcome(ex, role=role, thread=thread, text=text, pending=pending, resolve_road=resolve_road,
                      last_assignment_id=last_assignment_id, known_needs=record.get("needs"))
