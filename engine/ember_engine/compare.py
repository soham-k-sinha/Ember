"""Baseline vs EMBER on paired perturbation seeds → comparison.json (TECHNICAL.md §3.6, task 8).

Both plans are made once on the nominal scenario (EMBER: initial plan + a replan at every report;
baseline: alerts in arrival order) and then scored on the same N perturbed worlds. Per metric:
A = baseline mean, B = EMBER mean, B−A mean and range across seeds, and how many seeds EMBER wins,
ties, loses. Sentences say plainly when EMBER is worse.
"""

from __future__ import annotations

import random
import time

from .allocator.rolling import run_ember
from .baseline import baseline_plan
from .sim import simulate

METRICS = [   # (key, label, better, unit)
    ("people_reached_before_deadline", "people reached before their deadline", "higher", "people"),
    ("people_unreached", "people not reached before their deadline", "lower", "people"),
    ("hospital_outage_s", "hospital outage", "lower", "s"),
    ("service_outage_s_total", "critical-service outage", "lower", "s"),
    ("overflow_m3", "untreated wastewater overflow to the Charles", "lower", "m³"),
    ("unresolved_needs", "unresolved needs", "lower", "needs"),
    ("infeasible_assignments", "infeasible assignments", "lower", "assignments"),
    ("vehicle_km", "vehicle-km driven", "lower", "km"),
    ("fuel_l", "fuel used", "lower", "l"),
    ("reserve_remaining", "resources left in reserve", "higher", "resources"),
]
RANGES = {"travel_time_mult": (0.8, 1.6), "endurance_scale": (0.7, 1.3), "storage_scale": (0.7, 1.3), "inflow_scale": (0.85, 1.15)}


def perturbation(seed: int) -> dict:
    """Seed 0 = nominal; others draw each factor uniformly from RANGES (synthetic, labeled)."""
    if seed == 0:
        return {}
    rng = random.Random(seed)
    return {k: round(rng.uniform(lo, hi), 3) for k, (lo, hi) in RANGES.items()}


def _num(v: float, unit: str, signed: bool = False) -> str:
    x = v / 60 if unit == "s" else v
    txt = f"{abs(x):,.0f}" if unit == "s" or abs(x) >= 100 else f"{abs(x):,.1f}".rstrip("0").rstrip(".")
    sign = ("+" if x > 0 else "−" if x < 0 else "±") if signed else ("−" if x < 0 else "")
    return sign + txt


def _fmt(v: float, unit: str, signed: bool = False) -> str:
    return f"{_num(v, unit, signed)} {'min' if unit == 's' else unit}"


def compare(world, scn: dict, seeds: int = 5, reports=(), seed: int = 0) -> dict:
    t0 = time.time()
    reports = list(reports)
    base = baseline_plan(world, scn, reports)
    ember, versions = run_ember(world, scn, reports, seed=seed)
    per_seed = []
    for s in range(1, seeds + 1):
        p = perturbation(s)
        a = simulate(world, scn, base, reports=reports, perturbation=p, record=False).metrics
        b = simulate(world, scn, ember, reports=reports, perturbation=p, record=False).metrics
        per_seed.append({"seed": s, "perturbation": p, "baseline": a, "ember": b})
    nominal = {"baseline": simulate(world, scn, base, reports=reports, record=False).metrics,
               "ember": simulate(world, scn, ember, reports=reports, record=False).metrics}

    rows, headline = [], []
    for key, label, better, unit in METRICS:
        A = [r["baseline"][key] for r in per_seed]
        B = [r["ember"][key] for r in per_seed]
        D = [b - a for a, b in zip(A, B)]
        sign = 1 if better == "higher" else -1
        wins = sum(1 for d in D if sign * d > 1e-9)
        losses = sum(1 for d in D if sign * d < -1e-9)
        mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
        dm = mean(D)
        cap = label[0].upper() + label[1:]
        if wins == losses == 0:
            sentence = f"{cap}: no difference ({_fmt(mean(B), unit)} for both) on all {len(D)} seeds."
        else:
            verdict = "better" if sign * dm > 0 else "worse"
            sentence = (f"{cap}: EMBER {_fmt(mean(B), unit)} vs baseline {_fmt(mean(A), unit)} "
                        f"({_fmt(dm, unit, True)} on average; range {_num(min(D), unit, True)} to {_fmt(max(D), unit, True)} across seeds). "
                        f"EMBER is {verdict}: better on {wins}/{len(D)} seeds, worse on {losses}.")
        rows.append({"metric": key, "label": label, "better": better, "unit": unit, "baseline_mean": round(mean(A), 3),
                     "ember_mean": round(mean(B), 3), "diff_mean": round(dm, 3), "diff_min": round(min(D), 3),
                     "diff_max": round(max(D), 3), "ember_better_seeds": wins, "ember_worse_seeds": losses,
                     "ties": len(D) - wins - losses, "sentence": sentence})
        if key in ("people_reached_before_deadline", "people_unreached", "hospital_outage_s", "overflow_m3", "vehicle_km") and (wins or losses):
            headline.append(sentence)

    return {
        "version": "0.1", "scenario_id": scn["scenario_id"], "seeds": list(range(1, seeds + 1)),
        "perturbation_ranges": {k: list(v) for k, v in RANGES.items()},
        "plans": {"baseline": {"planner": "baseline", "assignments": len(base["assignments"]), "rule": base["trigger"]},
                  "ember": {"planner": "ember", "assignments": len([a for a in ember["assignments"] if a.get("status") != "cancelled"]),
                            "versions": [{"version": v["version"], "t_s": v["created_at_t_s"], "trigger": v["trigger"],
                                          "changes": len(v["changes"]), "wall_s": v["search"]["wall_s"]} for v in versions]}},
        "nominal": nominal, "per_seed": per_seed, "metrics": rows, "headline": headline,
        "notes": ["Same scenario, same fleet, same reports and the same perturbed worlds for both planners (paired seeds).",
                  "Perturbation ranges are synthetic stress factors, not calibrated distributions.",
                  "Plans are made on the nominal scenario and not re-optimised per seed: this measures robustness, not hindsight."],
        "wall_s": round(time.time() - t0, 2),
    }
