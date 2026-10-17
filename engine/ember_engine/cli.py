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
# The team's shared world (D29): committed so every machine, scenario and Daytona snapshot uses the same ids.
CANONICAL_TOWN = Path(__file__).resolve().parents[1] / "data" / "town.json.gz"


def _ensure_town() -> Path:
    """data/town.json, unpacked from the committed canonical copy when missing. Warns if a local
    rebuild differs from the canonical one (ids in scenarios may not match)."""
    import gzip
    if not TOWN.exists() and TOWN == DATA / "town.json" and CANONICAL_TOWN.exists():
        DATA.mkdir(exist_ok=True)
        TOWN.write_bytes(gzip.decompress(CANONICAL_TOWN.read_bytes()))
        print(f"[town] unpacked the shared {CANONICAL_TOWN.relative_to(ROOT)} → {TOWN.relative_to(ROOT)}")
    elif TOWN.exists() and CANONICAL_TOWN.exists() and TOWN == DATA / "town.json":
        if TOWN.read_bytes() != gzip.decompress(CANONICAL_TOWN.read_bytes()):
            print(f"[town] warning: {TOWN.relative_to(ROOT)} differs from the shared {CANONICAL_TOWN.relative_to(ROOT)}; "
                  "scenario ids may not match. Delete it to use the shared one, or `ember pin-town` to share yours.")
    if not TOWN.exists():
        sys.exit(f"{TOWN} not found. Run `uv run ember build` first.")
    return TOWN


def _load_world():
    from .world import World
    _ensure_town()
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


def _ws_examples(state: dict, points: list) -> list:
    """One example envelope per WS event type (contracts/ws-events.schema.json), built from the other fixtures."""
    t = state["t_s"]
    plan = state["plan"]
    a = plan["assignments"][0]
    ev = [("state", state), ("plan", plan),
          ("assignment", {"plan_version": plan["version"], "change": "added", "assignment_id": a["id"], "assignment": a}),
          ("assignment", {"plan_version": plan["version"], "change": "removed", "assignment_id": "a-example-removed", "assignment": None}),
          ("metrics", state["metrics"])]
    if state["messages"]:
        ev.append(("message", state["messages"][0]))
    if state["reports"]:
        ev.append(("report", state["reports"][0]))
    ev += [("scatter_point", p) for p in points]
    return [{"type": k, "seq": i, "t_s": t, "data": d} for i, (k, d) in enumerate(ev)]


def cmd_fixtures(a):
    """Write small fixtures into contracts/fixtures from the current data/."""
    import copy
    fx = ROOT / "contracts" / "fixtures"; fx.mkdir(parents=True, exist_ok=True)
    town = json.loads(_ensure_town().read_text())
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
    from .state import example_state
    scn = example_scenario(town)
    (fx / "scenario.fixture.json").write_text(json.dumps(scn, indent=1))
    (fx / "state.fixture.json").write_text(json.dumps(example_state(town, scn), indent=1))
    from .compare import compare, scatter_points
    cmp_ = compare(World.from_dict(town), scn, seeds=3)
    (fx / "comparison.fixture.json").write_text(json.dumps(cmp_, indent=1))
    (fx / "ws-events.fixture.json").write_text(json.dumps(_ws_examples(json.loads((fx / "state.fixture.json").read_text()),
                                                                       scatter_points(cmp_)[:2]), separators=(",", ":")))
    print(f"[fixtures] wrote to {fx}")


def cmd_pin_town(a):
    """Share the local data/town.json with the team: write it (gzip, deterministic) to engine/data/town.json.gz."""
    import gzip
    import io
    if not TOWN.exists():
        sys.exit(f"{TOWN} not found. Run `uv run ember build` first.")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9, filename="") as g:
        g.write(TOWN.read_bytes())
    CANONICAL_TOWN.parent.mkdir(parents=True, exist_ok=True)
    CANONICAL_TOWN.write_bytes(buf.getvalue())
    c = json.loads(TOWN.read_text())["meta"]["counts"]
    print(f"[pin-town] wrote {CANONICAL_TOWN.relative_to(ROOT)} ({len(buf.getvalue())/1e3:.0f} KB; {c}). "
          "Commit it, then re-run `ember fixtures` and re-validate scenarios: ids may have changed.")


def _read_reports(paths) -> list:
    return [r for p in (paths or []) for r in (lambda d: d if isinstance(d, list) else [d])(json.loads(Path(p).read_text()))]


def _make_plan(w, scn, which: str, reports: list) -> dict:
    from .allocator.rolling import run_ember
    from .baseline import baseline_plan
    from .sim import example_plan
    if which == "example":
        return example_plan(w, scn)
    if which == "baseline":
        return baseline_plan(w, scn, reports)
    if which == "ember":
        return run_ember(w, scn, reports)[0]
    return json.loads(Path(which).read_text())


def cmd_allocate(a):
    """EMBER plan: initial allocation + a replan at every report (scripted and --report)."""
    from .allocator.rolling import run_ember
    from .scenario import load_scenario
    w = _load_world()
    scn = load_scenario(a.scenario)
    reports = _read_reports(a.report)
    t0 = time.time()
    plan, versions = run_ember(w, scn, reports, seed=a.seed)
    print(f"[allocate] {scn['scenario_id']}: {len(versions)} plan version(s) in {time.time()-t0:.2f}s")
    for v in versions:
        print(f"  v{v['version']} @ {v['created_at_t_s']/60:5.1f} min  {v['search']['wall_s']:.2f}s  {len(v['changes']):>2} change(s)  "
              f"[{v['search']['policy']}]  {v['trigger']}")
    m = plan["metrics"]
    print(f"[allocate] reached {m['people_reached_before_deadline']} people before deadline, {m['people_unreached']} not; "
          f"hospital outage {m['hospital_outage_s']/60:.0f} min; overflow {m['overflow_m3']:,.0f} m³; {m['vehicle_km']:.0f} vehicle-km")
    for x in plan["assignments"]:
        if x["task"] == "protect":
            print(f"  {x.get('status', ''):>9}  {x['rationale']}")
    for u in plan["unresolved"]:
        print(f"  unresolved {u['target']}: {u['need']} — {u['blocked_by']}")
    out = Path(a.out or DATA / "plan.json")
    out.write_text(json.dumps(plan, indent=1))
    if a.versions_out:
        Path(a.versions_out).write_text(json.dumps(versions, indent=1))
    print(f"[allocate] wrote {out}")


def cmd_replan(a):
    """One replan: previous plan + new report(s) at --at seconds."""
    from .allocator import allocate
    from .scenario import load_scenario
    w = _load_world()
    scn = load_scenario(a.scenario)
    prev = json.loads(Path(a.plan).read_text())
    old = _read_reports(a.prev_report)
    new = _read_reports(a.report)
    plan = allocate(w, scn, reports=old + new, t_now=a.at, prev=prev, prev_reports=old, seed=a.seed,
                    trigger="; ".join(f"{r.get('source', 'resident')} report {r['id']}: {r['kind']}" for r in new) or None)
    print(f"[replan] v{prev.get('version')} → v{plan['version']} at {a.at/60:.0f} min in {plan['search']['wall_s']:.2f}s "
          f"[{plan['search']['policy']}]")
    for c in plan["changes"]:
        print(f"  {c['change']:>16}  {c['assignment_id']}  {c.get('note', '')}")
    out = Path(a.out or DATA / "plan.json")
    out.write_text(json.dumps(plan, indent=1))
    print(f"[replan] wrote {out}")


def cmd_compare(a):
    """Baseline vs EMBER on paired perturbation seeds → comparison.json."""
    from .compare import compare
    from .scenario import load_scenario
    w = _load_world()
    scn = load_scenario(a.scenario)
    c = compare(w, scn, seeds=a.seeds, reports=_read_reports(a.report), seed=a.seed)
    for r in c["metrics"]:
        print(f"  {r['sentence']}")
    out = Path(a.out or DATA / "comparison.json")
    out.write_text(json.dumps(c, indent=1))
    print(f"[compare] {a.seeds} paired seeds in {c['wall_s']:.1f}s → {out}")


def cmd_robust(a):
    """Top allocator candidates × perturbed worlds on Daytona (or local processes) → the most robust plan."""
    import os

    from .daytona.pool import get_pool
    from .daytona.robust import robust_plan
    from .scenario import load_scenario
    if a.pool == "local":
        os.environ["EMBER_LOCAL_POOL"] = "1"
    w = _load_world()
    scn = load_scenario(a.scenario)
    pool = get_pool("local" if a.pool == "local" else "auto", workers=a.workers, world=w)
    pts_out = open(a.points_out, "w") if a.points_out else None
    seen = [0]

    def on_point(p):
        seen[0] += 1
        if pts_out:
            pts_out.write(json.dumps(p) + "\n")
        if seen[0] % max(1, p["n_total"] // 10) == 0 or seen[0] == p["n_total"]:
            print(f"  {seen[0]:>4}/{p['n_total']} runs back (last: {p['candidate']} seed {p['seed']} on {p['worker']})")
    print(f"[robust] pool={pool.kind} workers={getattr(pool, 'n', None) or getattr(pool, 'workers', None)}")
    try:
        plan, points = robust_plan(w, scn, _read_reports(a.report), k=a.candidates, seeds=a.seeds, pool=pool, on_point=on_point)
    finally:
        pool.close()
        if pts_out:
            pts_out.close()
    r = plan["search"]["robust"]
    for line in getattr(pool, "log", [])[:5]:
        print(f"[robust] note: {line}")
    print(f"[robust] {r['jobs']} runs in {r['fanout_wall_s']:.1f}s · rule: {r['rule']}")
    for row in r["ranking"]:
        mark = "→" if row["candidate"] == r["chosen"] else " "
        print(f"  {mark} {row['candidate']:>8}  worst-20% unreached {row['worst20_people_unreached']:>6}  overflow {row['worst20_overflow_m3']:>8,.0f} m³"
              f"   mean unreached {row['mean_people_unreached']:>6}")
    if r["chosen"] != r["nominal_best"]:
        print(f"[robust] chose {r['chosen']} over the nominal best {r['nominal_best']}: better in the worst 20% of worlds")
    out = Path(a.out or DATA / "plan.json")
    out.write_text(json.dumps(plan, indent=1))
    print(f"[robust] wrote {out}" + (f" and {a.points_out}" if a.points_out else ""))


def cmd_seed_state(a):
    """The backend's starting state for a scenario (plan v1 at t=0): point residents' SEED_STATE at it."""
    from .api import write_seed
    from .state import validate_state
    from .scenario import load_scenario
    t0 = time.time()
    st = write_seed(a.scenario, a.out)
    errs = validate_state(st, load_scenario(a.scenario), json.loads(_ensure_town().read_text()))
    print(f"[seed-state] {st['scenario_id']} plan v{st['plan_version']} at t=0 → {a.out} ({time.time()-t0:.1f}s); "
          f"{len(st['plan']['assignments'])} assignments, projected {st['plan']['metrics']['people_reached_before_deadline']} "
          f"people reached; {'valid' if not errs else 'INVALID: ' + errs[0]}")
    if errs:
        sys.exit(1)


def cmd_daytona_snapshot(a):
    from .daytona.pool import build_snapshot
    build_snapshot()


def cmd_simulate(a):
    """Run a plan on a scenario with the plan simulator; print metrics, outcomes and key events."""
    import collections

    from .scenario import load_scenario
    from .sim import example_plan, simulate
    w = _load_world()
    scn = load_scenario(a.scenario)
    reports = _read_reports(a.report)
    plan = _make_plan(w, scn, a.plan, reports)
    t0 = time.time()
    res = simulate(w, scn, plan, reports=reports)
    wall = time.time() - t0
    print(f"[simulate] {scn['scenario_id']} · plan {plan.get('planner', '?')} v{plan.get('version', 1)} · "
          f"{len(plan.get('assignments', []))} assignments · {len(reports)} report(s) · {wall:.2f}s")
    print(json.dumps(res.metrics, indent=2))
    print("outcomes:", dict(collections.Counter(f"{o['task']}:{o['status']}" for o in res.outcomes)))
    why = collections.Counter(o["reason"] for o in res.outcomes if o["status"] != "done")
    for r, n in why.most_common(5):
        print(f"   {n:>3} × {r}")
    for e in res.events:
        if e["kind"] in ("generator_connected", "overflow_started", "facility_state", "resource_failed", "road_cleared"):
            print(f"  t={e['t_s']/60:6.1f} min  {e['kind']}  " + " ".join(f"{k}={v}" for k, v in e.items() if k not in ("t_s", "kind")))
    if a.out:
        Path(a.out).write_text(json.dumps({"metrics": res.metrics, "outcomes": res.outcomes, "events": res.events,
                                           "timeline": res.timeline}, separators=(",", ":")))
        print(f"[simulate] wrote {a.out}")
    if a.state_at is not None:
        out = Path(a.state_out or DATA / "state.json")
        out.write_text(json.dumps(res.state_at(a.state_at), indent=1))
        print(f"[simulate] state at {a.state_at/60:.0f} min → {out}")


def cmd_playback(a):
    """A plan simulated over the whole horizon as contracts/playback.schema.json (the map's replay).
    --fixtures writes EMBER and baseline for allston_flood_v1 into contracts/fixtures/."""
    from .playback import playback
    from .scenario import load_scenario
    from .sim import simulate
    w = _load_world()
    if a.fixtures:
        fx = ROOT / "contracts" / "fixtures"
        scn = load_scenario(ROOT / "scenarios" / "allston_flood_v1" / "scenario.json")
        for which, name in (("ember", "playback.fixture.json"), ("baseline", "playback.baseline.fixture.json")):
            pb = playback(simulate(w, scn, _make_plan(w, scn, which, [])), which)
            (fx / name).write_text(json.dumps(pb, separators=(",", ":")))
            print(f"[playback] {which}: {len(pb['tracks'])} tracks, overflow {pb['metrics'].get('overflow_m3')} m³ → {fx / name}")
        return
    if not a.scenario:
        raise SystemExit("--scenario is required (or --fixtures)")
    scn = load_scenario(a.scenario)
    reports = _read_reports(a.report)
    pb = playback(simulate(w, scn, _make_plan(w, scn, a.plan, reports), reports=reports), a.plan)
    out = Path(a.out or DATA / f"playback.{a.plan}.json")
    out.write_text(json.dumps(pb, separators=(",", ":")))
    print(f"[playback] {a.plan}: {sum(len(t['path']) for t in pb['tracks'])} track points → {out}")


def cmd_validate_state(a):
    """Check a state snapshot (e.g. the backend's GET /state) against state.schema.json and town ids."""
    from .scenario import load_scenario
    from .state import load, validate_state
    town = json.loads((Path(a.town) if a.town else _ensure_town()).read_text())
    st = load(a.path)
    errs = validate_state(st, load_scenario(a.scenario) if a.scenario else None, town)
    for e in errs:
        print(f"ERROR   {e}")
    p = st.get("plan") or {}
    print(f"{'FAIL' if errs else 'OK'} state t={st.get('t_s', 0)/60:.0f} min plan v{st.get('plan_version')}: "
          f"{len(st.get('households', []))} households, {len(st.get('resources', []))} resources, {len(p.get('assignments', []))} assignments, "
          f"{len(p.get('unresolved', []))} unresolved, {len(st.get('closures', []))} closed edges"
          + (f"; {len(errs)} error(s)" if errs else ""))
    sys.exit(1 if errs else 0)


def cmd_validate_scenario(a):
    """Schema + referential checks against town.json; one-line summary; exit 1 on errors."""
    from .scenario import load_scenario, validate
    town_path = Path(a.town) if a.town else _ensure_town()
    if not town_path.exists():
        sys.exit(f"{town_path} not found.")
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
    pt = sp.add_parser("pin-town", help="share data/town.json as the committed engine/data/town.json.gz"); pt.set_defaults(f=cmd_pin_town)
    v = sp.add_parser("validate-scenario", help="check a scenario.json against the schema and town.json")
    v.add_argument("path"); v.add_argument("--town", default=None, help="town.json to check ids against (default data/town.json)")
    v.add_argument("--deadlines", action="store_true", help="also print per-household deadlines")
    v.set_defaults(f=cmd_validate_scenario)
    sm = sp.add_parser("simulate", help="run a plan on a scenario (plan simulator)")
    sm.add_argument("--scenario", required=True)
    sm.add_argument("--plan", default="ember", help="ember | baseline | example | a plan JSON file")
    sm.add_argument("--report", action="append", help="report JSON (object or list); repeatable")
    sm.add_argument("--out", default=None, help="write metrics + outcomes + events + timeline JSON here")
    sm.add_argument("--state-at", type=float, default=None, help="also write a state snapshot at this sim time (s)")
    sm.add_argument("--state-out", default=None)
    sm.set_defaults(f=cmd_simulate)
    pb = sp.add_parser("playback", help="simulate a plan and write the map replay (contracts/playback.schema.json)")
    pb.add_argument("--scenario", default=None); pb.add_argument("--plan", default="ember", help="ember | baseline | example | a plan JSON file")
    pb.add_argument("--report", action="append"); pb.add_argument("--out", default=None)
    pb.add_argument("--fixtures", action="store_true", help="write contracts/fixtures/playback{,.baseline}.fixture.json for allston_flood_v1")
    pb.set_defaults(f=cmd_playback)
    al = sp.add_parser("allocate", help="EMBER plan (initial + replan at every report)")
    al.add_argument("--scenario", required=True); al.add_argument("--report", action="append"); al.add_argument("--seed", type=int, default=0)
    al.add_argument("--out", default=None); al.add_argument("--versions-out", default=None); al.set_defaults(f=cmd_allocate)
    rp = sp.add_parser("replan", help="replan a previous plan with new report(s) at --at")
    rp.add_argument("--scenario", required=True); rp.add_argument("--plan", required=True); rp.add_argument("--at", type=float, required=True)
    rp.add_argument("--report", action="append", required=True); rp.add_argument("--prev-report", action="append")
    rp.add_argument("--seed", type=int, default=0); rp.add_argument("--out", default=None); rp.set_defaults(f=cmd_replan)
    cp = sp.add_parser("compare", help="baseline vs EMBER on paired perturbation seeds")
    cp.add_argument("--scenario", required=True); cp.add_argument("--seeds", type=int, default=5); cp.add_argument("--report", action="append")
    cp.add_argument("--seed", type=int, default=0); cp.add_argument("--out", default=None); cp.set_defaults(f=cmd_compare)
    rb = sp.add_parser("robust", help="robust plan: top candidates × perturbed worlds on Daytona or local processes")
    rb.add_argument("--scenario", required=True); rb.add_argument("--report", action="append")
    rb.add_argument("--candidates", type=int, default=4); rb.add_argument("--seeds", type=int, default=20)
    rb.add_argument("--pool", choices=["auto", "local", "daytona"], default="auto"); rb.add_argument("--workers", type=int, default=None)
    rb.add_argument("--out", default=None); rb.add_argument("--points-out", default=None, help="write scatter points as JSON lines")
    rb.set_defaults(f=cmd_robust)
    ss = sp.add_parser("seed-state", help="backend seed: plan v1 + state at t=0 for a scenario")
    ss.add_argument("--scenario", default=str(ROOT / "scenarios" / "allston_flood_v1" / "scenario.json"))
    ss.add_argument("--out", default=str(ROOT / "engine" / "data" / "allston_flood_v1.seed_state.json"))
    ss.set_defaults(f=cmd_seed_state)
    ds = sp.add_parser("daytona-snapshot", help="build the Daytona snapshot for the current engine + town (needs DAYTONA_API_KEY)")
    ds.set_defaults(f=cmd_daytona_snapshot)
    vs = sp.add_parser("validate-state", help="check a state snapshot against state.schema.json and town/scenario ids")
    vs.add_argument("path"); vs.add_argument("--scenario", default=None); vs.add_argument("--town", default=None)
    vs.set_defaults(f=cmd_validate_state)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
