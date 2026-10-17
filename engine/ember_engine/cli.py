"""`ember` CLI: build · smoke · render · gate-a · fixtures · export"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
TOWN = Path(__import__("os").environ.get("EMBER_TOWN", DATA / "town.json"))


def _load_world():
    from .world import World
    if not TOWN.exists():
        sys.exit(f"{TOWN} not found. Run `uv run ember build` first.")
    t0 = time.time()
    w = World.load(TOWN)
    print(f"[world] {w.n_nodes} nodes, {w.n_edges} edges, {len(w.hh_id)} households, {len(w.exits)} exits ({time.time()-t0:.2f}s)")
    return w


def cmd_build(a):
    from .build_town import build
    build(dist_m=a.dist, out=TOWN, seed=a.seed, with_walk=not a.no_walk)


def cmd_smoke(a):
    from .run_job import default_job, run_job
    w = _load_world()
    job = default_job(w, heading_deg=a.heading, speed_mps=a.speed, compliance=a.compliance, staged=a.staged, T_s=a.T)
    m = run_job(w, job, with_trajectories=True)
    traj = m.pop("_trajectories"); snaps = m.pop("_snapshots")
    print(json.dumps({k: v for k, v in m.items() if k != "closure_order"}, indent=2))
    print("first closures:", [f"{c[2]}@{c[1]:.0f}s" for c in m["closure_order"][:8]])
    DATA.mkdir(exist_ok=True)
    (DATA / "metrics.json").write_text(json.dumps(m, indent=2))
    (DATA / "trajectories.json").write_text(json.dumps({"version": "0.1", "t0_label": "sim start", "trips": traj}))
    # last snapshot for render
    last = snaps[-1]
    import numpy as np
    np.save(DATA / "last_occupancy.npy", last["occupancy"])
    np.save(DATA / "last_closed.npy", last["closed"])
    (DATA / "last_t.json").write_text(json.dumps({"t_s": last["t_s"], "counts": last["counts"], "job": job}))
    print(f"[smoke] wrote data/metrics.json, data/trajectories.json ({len(traj)} trips)")


def cmd_render(a):
    import numpy as np
    from .hazards import hazard_from_scenario
    from .render_png import render
    w = _load_world()
    hazard, closed, occ, t = None, None, None, a.t
    lt = DATA / "last_t.json"
    if lt.exists() and not a.plain:
        info = json.loads(lt.read_text())
        hazard = hazard_from_scenario(w, info["job"]["scenario"])
        closed = np.zeros(w.n_edges, dtype=bool); closed[np.load(DATA / "last_closed.npy")] = True
        occ = np.load(DATA / "last_occupancy.npy")
        t = info["t_s"] if a.t is None else a.t
        if a.t is not None:
            closed = hazard.closed_mask_at(t, w); occ = None
    out = render(w, DATA / "town.png", hazard=hazard, t_s=t or 0.0, closed=closed, occupancy=occ)
    print(f"[render] wrote {out}")


def cmd_gate_a(a):
    """Rotate the hazard heading by 90°: the first exit to close and the closure order must change.

    Edges closed at ignition (t = start) are identical for every heading by construction, so the
    closure comparison starts after the ignition tick."""
    from .run_job import default_job, run_job
    w = _load_world()
    res = {}
    for h in (a.heading, (a.heading + 90) % 360):
        m = run_job(w, default_job(w, heading_deg=h, speed_mps=a.speed, T_s=a.T))
        t_ign = m["closure_order"][0][1] if m["closure_order"] else 0.0
        later = [c[2] for c in m["closure_order"] if c[1] > t_ign]
        exits = m["exit_closure_order"]
        res[h] = (later[:6], [x[0] for x in exits[:3]])
        print(f"heading {h:>5.0f}: exposed={m['exposed_vehicles']:>5} exited={m['exited']:>5} clearance95={m['clearance_s_95']}"
              f"\n    first exits closed={[f'{w.exit_label(x[0])} t={x[1]:.0f}s' for x in exits[:3]]}\n    first closures after ignition={later[:4]}")
    (c1, x1), (c2, x2) = res.values()
    exit_diff = bool(x1 and x2 and x1[0] != x2[0])
    order_diff = c1[:3] != c2[:3]
    ok = exit_diff and order_diff
    print(f"GATE A: {'PASS' if ok else 'FAIL'} (first exit differs: {exit_diff}; closure order differs: {order_diff})")
    if not ok:
        sys.exit(1)


def cmd_fixtures(a):
    """Write small fixtures into contracts/fixtures from the current data/."""
    import copy
    fx = ROOT / "contracts" / "fixtures"; fx.mkdir(parents=True, exist_ok=True)
    town = json.loads(TOWN.read_text())
    # full road network (so trajectories line up) + every 12th household + a slice of footways; < 1 MB
    small = copy.deepcopy(town)
    small["households"] = town["households"][::12]
    small["paths"] = town["paths"][:300]
    small["meta"]["counts"] = {k: len(small[k]) for k in ("nodes", "edges", "paths", "households", "assets", "exits", "zones")}
    small["meta"]["fixture"] = f"households sampled 1 in 12 from {len(town['households'])}; paths truncated to 300"
    (fx / "town.fixture.json").write_text(json.dumps(small, separators=(",", ":")))
    if (DATA / "trajectories.json").exists():
        tr = json.loads((DATA / "trajectories.json").read_text()); tr["trips"] = tr["trips"][:200]
        (fx / "trajectories.fixture.json").write_text(json.dumps(tr, separators=(",", ":")))
    if (DATA / "metrics.json").exists():
        (fx / "metrics.fixture.json").write_text((DATA / "metrics.json").read_text())
    from .run_job import default_job
    from .world import World
    w = World.from_dict(town)
    j = default_job(w, staged=True)
    (fx / "job.fixture.json").write_text(json.dumps(j, indent=2))
    (fx / "plan.fixture.json").write_text(json.dumps(j["plan"], indent=2))
    from .scenario import example_scenario
    (fx / "scenario.fixture.json").write_text(json.dumps(example_scenario(town), indent=1))
    print(f"[fixtures] wrote to {fx}")


def cmd_validate_scenario(a):
    """Schema + referential checks against town.json; one-line summary; exit 1 on errors."""
    from .scenario import load_scenario, validate
    town_path = Path(a.town) if a.town else TOWN
    if not town_path.exists():
        sys.exit(f"{town_path} not found. Run `uv run --project engine ember build` first (or pass --town).")
    scn = load_scenario(a.path)
    rep = validate(scn, json.loads(town_path.read_text()))
    for e in rep.errors:
        print(f"ERROR   {e}")
    for w in rep.warnings:
        print(f"warning {w}")
    if a.deadlines and rep.deadlines:
        for hid, d in sorted(rep.deadlines["households"].items(), key=lambda kv: (kv[1] is None, kv[1] or 0)):
            print(f"  household {hid:>6}: deadline {'-' if d is None else f'{d/60:5.0f} min'}")
        for fid, d in rep.deadlines["facilities"].items():
            print(f"  facility {fid:>14}: flooded {'never' if d is None else f'at {d/60:.0f} min'}")
    print(rep.summary)
    sys.exit(0 if rep.ok else 1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="ember")
    sp = p.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build"); b.add_argument("--dist", type=int, default=1200); b.add_argument("--seed", type=int, default=7); b.add_argument("--no-walk", action="store_true"); b.set_defaults(f=cmd_build)
    s = sp.add_parser("smoke"); s.add_argument("--heading", type=float, default=90.0); s.add_argument("--speed", type=float, default=0.6)
    s.add_argument("--compliance", type=float, default=1.0); s.add_argument("--staged", action="store_true"); s.add_argument("--T", type=float, default=3600.0); s.set_defaults(f=cmd_smoke)
    r = sp.add_parser("render"); r.add_argument("--t", type=float, default=None); r.add_argument("--plain", action="store_true"); r.set_defaults(f=cmd_render)
    g = sp.add_parser("gate-a"); g.add_argument("--heading", type=float, default=90.0); g.add_argument("--speed", type=float, default=0.6); g.add_argument("--T", type=float, default=7200.0); g.set_defaults(f=cmd_gate_a)
    f = sp.add_parser("fixtures"); f.set_defaults(f=cmd_fixtures)
    v = sp.add_parser("validate-scenario", help="check a scenario.json against the schema and town.json")
    v.add_argument("path"); v.add_argument("--town", default=None, help="town.json to check ids against (default data/town.json)")
    v.add_argument("--deadlines", action="store_true", help="also print per-household deadlines")
    v.set_defaults(f=cmd_validate_scenario)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
