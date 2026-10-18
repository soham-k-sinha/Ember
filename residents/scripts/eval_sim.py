"""Simulator-graded eval of the text → fact step (D83): does a misread change who gets out in time?

    cd residents && uv run python scripts/eval_sim.py [--extractor fallback|llm] [--limit N] [--moves M]

For each message in tests/samples.json the same deterministic code (`to_outcome`) turns two extractions into
reports: the GOLD one (`gold`, else derived from `expect`) and the extractor's. Starting from a fixed seeded plan
(v1, plus the judge's household known as 3 people at t = 10 min, which the samples' conversations assume), the
planner replans on each, and both plans are simulated in the gold world. Scored per message:
- reached: the judge's household is picked up before its deadline under the extracted plan whenever the gold plan
  manages it (the simulator only boards a wheelchair user on an accessible vehicle);
- regret = extracted − gold in people unreached, hospital outage and sewage overflow;
- ASK: the extractor's facts left something to ask instead of a guess (or it read nothing): safe, not a pass.
--extractor fallback is the D75 keyword parser (no network); llm calls the real model.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ember_engine.sim import simulate  # noqa: E402
from residents import fallback  # noqa: E402
from residents.engine_bridge import FACT_KINDS, EngineBridge  # noqa: E402
from residents.extract import NEED_FIELDS, SYSTEM, Extraction, Fact, build_prompt, to_outcome  # noqa: E402

SCENARIO = ROOT.parent / "scenarios" / "allston_flood_v1" / "scenario.json"
JUDGE, HOSPITAL, T_NOW = 10296, "mt-auburn", 600.0
KNOWN = {"people": 3}
FIELDS = {"need": NEED_FIELDS, "closure_report": ("road_hint", "cross_street"), "location": ("address", "cross_street"),
          "facility_status": ("endurance_min", "facility_state"), "question": ("question_topic", "road_hint")}
REGRET = (("people_unreached", 1), ("hospital_outage_s", 60), ("overflow_m3", 1))  # (metric, smallest regret that counts)


def gold(sample: dict) -> Extraction:
    exp = sample["expect"]
    facts = sample.get("gold") or [{"kind": k, **{f: exp[f] for f in FIELDS.get(k, ()) if f in exp}} for k in exp["kinds"]]
    return Extraction(facts=[Fact(**{f: None for f in Fact.model_fields} | x) for x in facts], confidence=1.0,
                      clarifying_question="?" if exp.get("question") else None)


class Eval:
    def __init__(self, bridge: EngineBridge):
        self.b = bridge
        v1 = bridge.plan([], 0.0, None, None)
        self.base_reports = [{"id": "base-need", "source": "resident", "kind": "need", "household_id": JUDGE,
                              "observed_at_t_s": T_NOW, "payload": KNOWN}]
        self.base = {"resident": bridge.plan(self.base_reports, T_NOW, v1, []), "operator": v1}
        self._plans: dict[str, dict] = {}

    def offered(self, role: str) -> str | None:
        target = {"household_id": JUDGE} if role == "resident" else {"facility_id": HOSPITAL}
        return next((a["id"] for a in self.base[role]["assignments"] if a["target"] == target), None)

    def before(self, role: str) -> list[dict]:
        return self.base_reports if role == "resident" else []

    def reports(self, role: str, out, tag: str) -> tuple[list[dict], bool]:
        new = [{"id": f"{tag}-{i}", "observed_at_t_s": T_NOW, **r} for i, r in enumerate(out.reports) if r["kind"] in FACT_KINDS]
        return self.before(role) + new, any(r["kind"] == "reject" for r in out.reports)

    def plan(self, role: str, reports: list[dict], rejected: bool) -> dict:
        key = json.dumps([role, rejected, [(r["kind"], r.get("household_id"), r.get("facility_id"), r.get("payload")) for r in reports]])
        if key not in self._plans:
            prev, before = self.base[role], self.before(role)
            if rejected:
                prev = copy.deepcopy(prev)
                next(a for a in prev["assignments"] if a["id"] == self.offered(role))["status"] = "rejected"
            self._plans[key] = prev if len(reports) == len(before) and not rejected else self.b.plan(reports, T_NOW, prev, before)
        return self._plans[key]

    def score(self, plan: dict, truth: list[dict]) -> tuple[dict, bool, str]:
        """Simulate `plan` in the gold world → (metrics, judge picked up before the deadline, the judge's vehicle)."""
        res = simulate(self.b.world, self.b.scenario, plan, reports=truth, record=False)
        mine = [o for o in res.outcomes if o["task"] == "rescue" and o["target"].get("household_id") == JUDGE]
        reached = any(o["pickup_t"] is not None and o["met_deadline"] for o in mine)
        ride = next((o for o in mine if o["pickup_t"] is not None), mine[-1] if mine else None)
        return res.metrics, reached, ride["resource_id"] if ride else "-"


async def run(ev: Eval, samples: list[dict], read) -> list[dict]:
    rows = []
    for i, s in enumerate(samples, 1):
        role, ctx = s["role"], s.get("context", {})
        thread = {"household_id": JUDGE} if role == "resident" else {"facility_id": HOSPITAL}
        last = ev.offered(role) if ctx.get("last_outbound") else None

        def outcome(e: Extraction):
            return to_outcome(e, role=role, thread=thread, text=s["text"], pending=ctx.get("pending"),
                              resolve_road=ev.b.resolve_road, last_assignment_id=last,
                              known_needs=KNOWN if role == "resident" else None)

        ex = await read(s)  # None: nothing readable → the backend asks the plan's open question, no report
        x = outcome(ex or Extraction(facts=[], confidence=1.0, clarifying_question=None))
        truth, g_rej = ev.reports(role, outcome(gold(s)), "g")
        m_g, reached_g, _ = ev.score(ev.plan(role, truth, g_rej), truth)
        m_x, reached_x, vehicle = ev.score(ev.plan(role, *ev.reports(role, x, "x")), truth)
        regret = {k: m_x[k] - m_g[k] for k, _ in REGRET}
        ok = (reached_x or not reached_g or g_rej) and all(regret[k] < eps for k, eps in REGRET)
        asked = ex is None or bool(x.question or x.follow_up)
        rows.append({"i": i, "role": role, "text": s["text"], "facts": [f.kind for f in ex.facts] if ex else [],
                     "vehicle": vehicle, "reached": None if role == "operator" or g_rej else reached_x, "regret": regret,
                     "result": "PASS" if ok and ex else "ASK" if asked else "FAIL"})
    return rows


def table(rows: list[dict]) -> str:
    out = [" #  role      message                                   extracted                 vehicle  reached  Δunreached  Δoutage_min  Δoverflow_m3  result"]
    for r in rows:
        text = r["text"] if len(r["text"]) <= 40 else r["text"][:39] + "…"
        reached = "-" if r["reached"] is None else "yes" if r["reached"] else "NO"
        g = r["regret"]
        out.append(f"{r['i']:2d}  {r['role']:8s}  {text:40s}  {','.join(r['facts']) or '(none)':24s}  {r['vehicle']:7s}  "
                   f"{reached:7s}  {g['people_unreached']:+10d}  {g['hospital_outage_s'] / 60:+11.0f}  {g['overflow_m3']:+12.0f}  {r['result']}")
    n = {k: sum(r["result"] == k for r in rows) for k in ("PASS", "ASK", "FAIL")}
    out.append(f"\n{n['PASS']}/{len(rows)} pass ({100 * n['PASS'] / len(rows):.0f}%), {n['ASK']} asked instead of guessing, "
               f"{n['FAIL']} fail · safe (pass or ask) {100 * (n['PASS'] + n['ASK']) / len(rows):.0f}%")
    return "\n".join(out)


async def parse_fallback(s: dict) -> Extraction | None:
    return fallback.parse(s["text"], s["role"])


def llm_reader():
    from residents.config import Settings
    from residents.extract import make_llm
    llm = make_llm(Settings().anthropic_api_key)
    records = {"resident": {"household_id": JUDGE, "label": "the judge's household", "needs": KNOWN, "status": "assigned"},
               "operator": {"id": HOSPITAL, "name": "Mount Auburn Hospital", "type": "hospital", "state": "backup"}}

    async def read(s: dict) -> Extraction | None:
        ctx = s.get("context", {})
        return await llm(SYSTEM, build_prompt(s["text"], s["role"], records[s["role"]], ctx.get("last_outbound"),
                                              ctx.get("pending"), ctx.get("history")))

    return read


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", choices=("fallback", "llm"), default="fallback")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--moves", type=int, help="allocator search budget per replan (default: the engine's)")
    a = ap.parse_args()
    samples = json.loads((ROOT / "tests" / "samples.json").read_text())["samples"][:a.limit]
    rows = asyncio.run(run(Eval(EngineBridge(SCENARIO, seed=0, moves=a.moves)), samples,
                           llm_reader() if a.extractor == "llm" else parse_fallback))
    print(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
