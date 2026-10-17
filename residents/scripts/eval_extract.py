"""Live accuracy of the one LLM call on tests/samples.json (calls the real API; ~20 requests).

    cd residents && uv run python scripts/eval_extract.py [--model claude-opus-5-5] [--effort low]

A sample passes when the fact kinds match in order and every expected field matches on the fact of
that kind (`road_hint`/`cross_street` compared after street normalization; `question: true` = the
model asked a clarifying question). Prints per-sample results, accuracy and latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from residents.config import Settings  # noqa: E402
from residents.engine_bridge import normalize_street  # noqa: E402
from residents.extract import EFFORT, MODEL, SYSTEM, build_prompt, make_llm  # noqa: E402

RECORDS = {"resident": {"household_id": 10296, "label": "the judge's household", "needs": "unknown", "status": "unknown"},
           "operator": {"id": "mt-auburn", "name": "Mount Auburn Hospital", "type": "hospital", "state": "backup"}}


def check(sample: dict, ex) -> list[str]:
    exp = sample["expect"]
    kinds = [f.kind for f in ex.facts]
    errs = [] if kinds == exp["kinds"] else [f"kinds {kinds} != {exp['kinds']}"]
    for key, want in exp.items():
        if key in ("kinds", "question"):
            continue
        facts = [f for f in ex.facts if getattr(f, key, None) is not None] or ex.facts
        got = getattr(facts[0], key, None) if facts else None
        if key in ("road_hint", "cross_street", "address") and got is not None and want is not None:
            ok = normalize_street(want) in normalize_street(got) or normalize_street(got) in normalize_street(want)
        elif isinstance(want, float) or key == "endurance_min":
            ok = got is not None and abs(float(got) - float(want)) < 0.5
        else:
            ok = got == want
        if not ok:
            errs.append(f"{key}={got!r} (want {want!r})")
    if exp.get("question") and not ex.clarifying_question:
        errs.append("expected a clarifying question")
    return errs


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--effort", default=EFFORT)
    a = ap.parse_args()
    key = Settings().anthropic_api_key
    if not key:
        print("ANTHROPIC_API_KEY is not set (residents/.env)")
        return 2
    llm = make_llm(key, model=a.model, effort=a.effort)
    samples = json.loads((ROOT / "tests" / "samples.json").read_text())["samples"]
    passed, lat = 0, []
    for i, s in enumerate(samples, 1):
        ctx = s.get("context", {})
        prompt = build_prompt(s["text"], s["role"], RECORDS[s["role"]], ctx.get("last_outbound"), ctx.get("pending"),
                              ctx.get("history"))
        t0 = time.time()
        try:
            ex = await llm(SYSTEM, prompt)
        except Exception as e:  # noqa: BLE001
            print(f"{i:2d} ERROR {s['text']!r}: {e!r}")
            continue
        lat.append(time.time() - t0)
        errs = check(s, ex)
        passed += not errs
        facts = "; ".join(f"{f.kind}" + "".join(f" {k}={v}" for k, v in f.model_dump().items() if v is not None and k != "kind") for f in ex.facts)
        print(f"{i:2d} {'PASS' if not errs else 'FAIL'} {lat[-1]:4.1f}s  {s['text']!r}\n      → {facts}  conf={ex.confidence:.2f}"
              + (f"  ask={ex.clarifying_question!r}" if ex.clarifying_question else "") + (f"\n      ✗ {', '.join(errs)}" if errs else ""))
    print(f"\n{passed}/{len(samples)} correct ({100 * passed / len(samples):.0f}%) · model {a.model} effort {a.effort} · "
          f"latency median {statistics.median(lat):.1f}s, max {max(lat):.1f}s")
    return 0 if passed >= len(samples) - 3 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
