"""Robustness jobs: one candidate plan × one perturbed world → one scatter point (ws-events `scatter_point`).

The same code runs in a Daytona sandbox, a local process pool, or in-process:
  WORKER_PRELUDE  once per worker: load the baked town into memory
  batch_setup()   once per worker per batch: register the scenario, reports and candidate plans
  job_code()      once per chunk of jobs: run them, print one JSON line each (results come back as the
                  run_code return value, because Tier 1/2 sandboxes cannot call out)
Pure: no I/O beyond reading the town, no network, deterministic per (plan, seed).
"""

from __future__ import annotations

import json
import random
import time

# perturbation factors (TECHNICAL.md §3.7; synthetic stress ranges, labeled)
RANGES = {"travel_time_mult": (0.8, 1.6), "endurance_scale": (0.7, 1.3), "storage_scale": (0.7, 1.3), "inflow_scale": (0.85, 1.15)}
P_FAILURE, P_CLOSURE, P_DELAY = 0.4, 0.3, 0.4


def sample_perturbation(seed: int, scn: dict, n_edges: int) -> dict:
    """Seed 0 = nominal. Otherwise: the four factors, plus sometimes one resource failure, one extra road
    closure, and delayed reports. Deterministic per (seed, scenario, town)."""
    if seed == 0:
        return {}
    rng = random.Random(f"{scn.get('scenario_id')}:{seed}")
    p = {k: round(rng.uniform(lo, hi), 3) for k, (lo, hi) in RANGES.items()}
    horizon = float(scn["t_end_s"])
    if rng.random() < P_FAILURE:
        rid = rng.choice(sorted(r["id"] for r in scn["resources"]))
        p["resource_failure"] = {"resource_id": rid, "t_s": round(rng.uniform(0.15, 0.6) * horizon / 60) * 60.0}
    if rng.random() < P_CLOSURE and n_edges:
        p["extra_closures"] = [[round(rng.uniform(0.1, 0.5) * horizon / 60) * 60.0, [rng.randrange(n_edges)]]]
    if rng.random() < P_DELAY:
        p["report_delay_s"] = round(rng.uniform(0, 600) / 60) * 60.0
    return p


def make_jobs(batch_id: str, candidates: list[str], seeds: list[int], scn: dict, n_edges: int) -> list[dict]:
    """Every candidate × every seed (paired: the same seed is the same world for every candidate)."""
    return [{"run_id": f"{batch_id}/{c}/s{s}", "batch_id": batch_id, "candidate": c, "seed": s,
             "perturbation": sample_perturbation(s, scn, n_edges)} for s in seeds for c in candidates]


def run_job(world, scn: dict, plans: dict, reports: list, job: dict, worker: str = "local") -> dict:
    """→ a scatter_point (contracts/ws-events.schema.json $defs/scatter_point)."""
    from ..allocator.search import objective
    from ..sim import simulate
    t0 = time.time()
    m = simulate(world, scn, plans[job["candidate"]], reports=reports, perturbation=job["perturbation"], record=False).metrics
    return {"run_id": job["run_id"], "batch_id": job["batch_id"], "candidate": job["candidate"], "seed": job["seed"],
            "perturbation": job["perturbation"], "metrics": m, "objective": [float(x) for x in objective(m)],
            "worker": worker, "wall_s": round(time.time() - t0, 4)}


# ---------- the code a remote worker executes (Daytona code_interpreter keeps these globals between calls) ----------
REMOTE_ENGINE_DIR = "/home/daytona/engine"          # contains ember_engine/ (baked into the snapshot)
REMOTE_TOWN = "/home/daytona/town.json.gz"


def worker_prelude(engine_dir: str = REMOTE_ENGINE_DIR, town_path: str = REMOTE_TOWN) -> str:
    return (
        "import gzip, json, sys\n"
        f"sys.path.insert(0, {engine_dir!r})\n"
        "from ember_engine.world import World\n"
        "from ember_engine.daytona.jobs import run_job as _ember_run_job\n"
        f"_EMBER_W = World.from_dict(json.loads(gzip.decompress(open({town_path!r}, 'rb').read())))\n"
        "_EMBER_B = {}\n"
        "print(json.dumps({'ok': True, 'nodes': _EMBER_W.n_nodes, 'edges': _EMBER_W.n_edges}))\n"
    )


def batch_setup(batch_id: str, scn: dict, plans: dict, reports: list) -> str:
    payload = json.dumps({"scenario": scn, "plans": plans, "reports": reports}, separators=(",", ":"))
    return f"_EMBER_B[{batch_id!r}] = json.loads({payload!r})\nprint(json.dumps({{'ok': True, 'batch': {batch_id!r}}}))\n"


def job_code(jobs: list[dict], worker: str) -> str:
    j = json.dumps(jobs, separators=(",", ":"))
    return (f"for _j in json.loads({j!r}):\n"
            f"    _b = _EMBER_B[_j['batch_id']]\n"
            f"    print(json.dumps(_ember_run_job(_EMBER_W, _b['scenario'], _b['plans'], _b['reports'], _j, {worker!r})))\n")


def parse_points(stdout: str, n: int) -> list[dict]:
    lines = [ln for ln in (stdout or "").strip().splitlines() if ln.strip().startswith("{")]
    if len(lines) != n:
        raise ValueError(f"{len(lines)} of {n} results in worker output: {(stdout or '')[-300:]!r}")
    return [json.loads(ln) for ln in lines]
