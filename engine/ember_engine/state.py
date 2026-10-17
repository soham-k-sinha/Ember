"""Shared-state snapshot (contracts/state.schema.json): the example fixture and a validator.

`example_state` = the example planner's plan, run through the plan simulator, snapshotted at t_s,
plus the outbound messages the backend would have sent. Everything in it is computed;
`plan.planner = "example"` until the allocator lands.
"""

from __future__ import annotations

import json
from pathlib import Path

from .scenario import CONTRACTS


def example_state(town: dict, scn: dict, t_s: float = 4800.0) -> dict:
    from .sim import example_plan, simulate
    from .world import World

    w = World.from_dict(town)
    plan = example_plan(w, scn)
    st = simulate(w, scn, plan).state_at(t_s)
    st["source"] = "engine-example"
    st["synthetic"] = ["plan from the example planner (dependency-first protect + deadline-ordered greedy), not the allocator",
                       "messages are examples of what the backend sends"] + st["synthetic"]
    judge = next(h for h in st["households"] if h["judge"])
    st["messages"] = [{"id": "m-1", "thread": {"household_id": judge["household_id"]}, "direction": "out", "t_s": 60.0,
                       "plan_version": st["plan_version"], "assignment_id": None, "report_id": None,
                       "text": "[EMBER drill] Flood warning for your street. How many people are with you, and does anyone "
                               "need a wheelchair-accessible vehicle? Reply here."}]
    hosp = [f for f in st["facilities"] if f["type"] == "hospital"]
    if hosp:
        st["messages"].append({"id": "m-2", "thread": {"facility_id": hosp[0]["id"]}, "direction": "out", "t_s": 60.0,
                               "plan_version": st["plan_version"], "assignment_id": None, "report_id": None,
                               "text": "[EMBER drill] Flood expected near your site. How many hours of backup fuel do you have right now?"})
    return st


# ---------- validation ----------
def validate_state(state: dict, scn: dict | None, town: dict) -> list[str]:
    """Schema errors + references (edge / household / facility / resource / assignment ids)."""
    import jsonschema
    from referencing import Registry, Resource

    reg = Registry()
    for p in CONTRACTS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        reg = reg.with_resource(s["$id"], Resource.from_contents(s))
    schema = json.loads((CONTRACTS / "state.schema.json").read_text())
    errs = [f"schema: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:300]}"
            for e in jsonschema.Draft202012Validator(schema, registry=reg).iter_errors(state)]
    if errs:
        return errs
    E = errs.append
    n_edges = len(town["edges"])
    hh_ids = {h["id"] for h in town["households"]}
    fac_ids = {f["id"] for f in state["facilities"]}
    res_ids = {r["id"] for r in state["resources"]}
    asg_ids = {a["id"] for a in (state["plan"] or {}).get("assignments", [])}
    for c in state["closures"]:
        if not 0 <= c["edge_id"] < n_edges:
            E(f"closures: edge {c['edge_id']} not in town.json")
    for h in state["households"]:
        if h["household_id"] not in hh_ids:
            E(f"households: {h['household_id']} not in town.json")
        if h["assignment_id"] and h["assignment_id"] not in asg_ids:
            E(f"households: {h['household_id']} points at unknown assignment {h['assignment_id']}")
    for f in state["facilities"]:
        for d in f.get("depends_on", []):
            if d not in fac_ids:
                E(f"facility {f['id']}: depends_on {d} unknown")
        if f.get("powered_by") and f["powered_by"] not in res_ids:
            E(f"facility {f['id']}: powered_by {f['powered_by']} is not a resource")
    for r in state["resources"]:
        if r["assignment_id"] and r["assignment_id"] not in asg_ids:
            E(f"resource {r['id']}: unknown assignment {r['assignment_id']}")
    assisted = {h["household_id"] for h in state["households"]}
    for a in (state["plan"] or {}).get("assignments", []):
        if a["resource_id"] not in res_ids:
            E(f"assignment {a['id']}: resource {a['resource_id']} unknown")
        t = a["target"]
        if "household_id" in t and t["household_id"] not in assisted:
            E(f"assignment {a['id']}: household {t['household_id']} is not assisted")
        if "facility_id" in t and t["facility_id"] not in fac_ids:
            E(f"assignment {a['id']}: facility {t['facility_id']} unknown")
        if any(not 0 <= e < n_edges for e in a.get("route_edges", [])):
            E(f"assignment {a['id']}: route edge not in town.json")
    if scn is not None:
        if state["scenario_id"] != scn["scenario_id"]:
            E(f"scenario_id {state['scenario_id']} != {scn['scenario_id']}")
        want = {h["household_id"] for h in scn["households"]}
        if assisted != want:
            E(f"households: state has {len(assisted)}, scenario has {len(want)} (mismatch: {sorted(assisted ^ want)[:5]})")
    return errs


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())
