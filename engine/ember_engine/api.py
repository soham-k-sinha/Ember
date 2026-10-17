"""The backend's entry point into the engine: one session object, one call per endpoint.

    from ember_engine.api import EngineSession
    eng = EngineSession("scenarios/allston_flood_v1/scenario.json")
    state = eng.start()                                   # plan v1 + state at t=0     (seed the DB)
    out = eng.add_report(report)                          # POST /reports              → replan (~0.5 s)
    out = eng.close_road(edge_ids, t_now=3600)            # POST /disruption           → replan
    state = eng.state_at(t)                               # GET /state at any sim clock
    cmp_ = eng.compare(seeds=5)                           # GET /comparison
    out = eng.optimize(on_point=broadcast, t_now=t)       # POST /optimize (Daytona or local; streams scatter_point)

`out` = {"plan": plan, "assignment_events": [...], "state": state}: broadcast `plan`, then one WS
`assignment` event per entry (contracts/ws-events.schema.json), then `state` (or let clients re-fetch).
Every call is CPU-bound and synchronous: run it in a threadpool (FastAPI `run_in_threadpool`), one at a
time per session (a lock). Reports follow contracts/report.schema.json; they apply at observed_at_t_s.
States carry `messages: []` — the backend merges its own threads.
"""

from __future__ import annotations

import itertools
import json
import threading
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = REPO / "scenarios" / "allston_flood_v1" / "scenario.json"


def assignment_events(plan: dict) -> list[dict]:
    """plan.changes → WS `assignment` payloads ({plan_version, change, assignment_id, assignment|null, note})."""
    by_id = {a["id"]: a for a in plan.get("assignments", [])}
    out = []
    for c in plan.get("changes", []):
        a = by_id.get(c["assignment_id"])
        removed = c["change"] == "removed"
        ev = {"plan_version": plan["version"], "change": c["change"], "assignment_id": c["assignment_id"],
              "assignment": None if removed or a is None else a}
        if c.get("note"):
            ev["note"] = c["note"]
        out.append(ev)
    return out


class EngineSession:
    def __init__(self, scenario_path: str | Path = DEFAULT_SCENARIO, world=None, seed: int = 0,
                 moves: int | None = None):
        from .daytona.pool import _load_world
        from .scenario import load_scenario
        self.scenario_path = Path(scenario_path)
        self.scn = load_scenario(self.scenario_path)
        self.world = world if world is not None else _load_world()
        self.seed = seed
        self.moves = moves                 # local-search budget per (re)plan; None = the allocator's default
        self.reports: list[dict] = []      # every report the engine has seen, in arrival order
        self.plan: dict | None = None
        self.versions: list[dict] = []
        self.lock = threading.Lock()
        self._ids = itertools.count(1)

    # ---------- lifecycle ----------
    def start(self) -> dict:
        """Plan v1 at t=0 (initial allocation) → state at t=0. Use it as the backend's seed."""
        from .allocator import allocate
        with self.lock:
            self.reports = []
            self.plan = allocate(self.world, self.scn, seed=self.seed, moves=self.moves)
            self.versions = [self.plan]
            return self._state(0.0)

    def resume(self, plan: dict, reports: list[dict]) -> None:
        """Rebuild the session after a backend restart from the DB's current plan and reports."""
        with self.lock:
            self.plan, self.reports, self.versions = plan, list(reports), [plan]

    # ---------- reports → replan ----------
    def add_report(self, report: dict, t_now: float | None = None) -> dict:
        return self.add_reports([report], t_now)

    def add_reports(self, reports: list[dict], t_now: float | None = None) -> dict:
        """New facts at sim time t_now (default: the latest observed_at) → plan v+1 + events + state."""
        from .allocator import allocate
        with self.lock:
            self._need_plan()
            t = float(t_now if t_now is not None else max(float(r["observed_at_t_s"]) for r in reports))
            before = [r for r in self.reports if float(r["observed_at_t_s"]) <= t]
            self.reports += [dict(r) for r in reports]
            known = [r for r in self.reports if float(r["observed_at_t_s"]) <= t]
            trigger = "; ".join(f"{r.get('source', 'resident')} report {r['id']}: {r['kind']}" for r in reports)
            self.plan = allocate(self.world, self.scn, reports=known, t_now=t, prev=self.plan, prev_reports=before,
                                 seed=self.seed, moves=self.moves, trigger=trigger)
            self.versions.append(self.plan)
            return {"plan": self.plan, "assignment_events": assignment_events(self.plan), "state": self._state(t)}

    def close_road(self, edge_ids: list[int], t_now: float, source: str = "judge", household_id: int | None = None,
                   text: str | None = None) -> dict:
        """POST /disruption: a reported closure (judge on the map, or a resident's text) → replan."""
        return self.add_report(self.make_report("closure_report", t_now, source=source, household_id=household_id,
                                                payload={"edge_ids": [int(e) for e in edge_ids]}, text=text), t_now)

    def make_report(self, kind: str, t_now: float, source: str = "resident", household_id: int | None = None,
                    facility_id: str | None = None, payload: dict | None = None, text: str | None = None,
                    confidence: float = 1.0) -> dict:
        """A report.schema.json object (e.g. from the LLM extraction's structured output)."""
        r = {"id": f"r-{source}-{next(self._ids)}-{int(t_now)}", "source": source, "kind": kind, "observed_at_t_s": float(t_now),
             "confidence": float(confidence), "resolved": False}
        if household_id is not None:
            r["household_id"] = int(household_id)
        if facility_id is not None:
            r["facility_id"] = facility_id
        if payload:
            r["payload"] = payload
        if text:
            r["text"] = text
        return r

    # ---------- reads ----------
    def state_at(self, t_s: float) -> dict:
        with self.lock:
            self._need_plan()
            return self._state(t_s)

    def playback(self, planner: str = "ember") -> dict:
        """GET /playback: the current plan ("ember") or the incident-by-incident baseline on the same
        reports, simulated over the whole horizon as contracts/playback.schema.json (map replay, D51)."""
        from .baseline import baseline_plan
        from .playback import playback
        from .sim import simulate
        if planner not in ("ember", "baseline"):
            raise ValueError("planner must be ember or baseline")
        with self.lock:
            self._need_plan()
            plan = self.plan if planner == "ember" else baseline_plan(self.world, self.scn, list(self.reports))
            return playback(simulate(self.world, self.scn, plan, reports=self.reports), planner)

    def compare(self, seeds: int = 5) -> dict:
        from .compare import compare
        with self.lock:
            return compare(self.world, self.scn, seeds=seeds, reports=list(self.reports), seed=self.seed)

    def optimize(self, on_point=None, t_now: float = 0.0, seeds: int = 20, k: int = 4, pool=None) -> dict:
        """POST /optimize: robust replan — top candidates × perturbed worlds on Daytona (local fallback).
        Streams every run to on_point (broadcast as WS scatter_point). Tier 1: ~100 runs ≈ 1–2 min."""
        from .daytona.robust import robust_plan
        with self.lock:
            known = [r for r in self.reports if float(r["observed_at_t_s"]) <= t_now]
            fresh = self.plan is not None and t_now <= 0
            plan, _ = robust_plan(self.world, self.scn, known, t_now=t_now, prev=self.plan if t_now > 0 else None,
                                  prev_reports=known, k=k, seeds=seeds, pool=pool, on_point=on_point, seed=self.seed,
                                  moves=self.moves, trigger="robust optimization",
                                  version=self.plan["version"] + 1 if fresh else None)
            if fresh:
                plan["parent_version"] = self.plan["version"]
            self.plan = plan
            self.versions.append(plan)
            return {"plan": plan, "assignment_events": assignment_events(plan), "state": self._state(t_now)}

    # ---------- helpers for turning words into edge ids ----------
    def edges_at_household(self, household_id: int) -> list[int]:
        """Edges touching the household's pickup node ('my street is blocked')."""
        rows = {int(h): i for i, h in enumerate(self.world.hh_id)}
        n = int(self.world.hh_node[rows[int(household_id)]])
        return [int(self.world.edge_id[e]) for e in np.where((self.world.edge_u == n) | (self.world.edge_v == n))[0]]

    def edges_by_name(self, name: str, near_household: int | None = None, radius_m: float = 300.0) -> list[int]:
        """Edges whose OSM name contains `name` (case-insensitive), optionally within radius of a household."""
        w = self.world
        hit = [e for e in range(w.n_edges) if name.lower() in (w.edge_name[e] or "").lower()]
        if near_household is not None:
            rows = {int(h): i for i, h in enumerate(w.hh_id)}
            n = int(w.hh_node[rows[int(near_household)]])
            mid = w.geom_start + w.geom_count // 2
            d = np.hypot(w.geom_x[mid] - w.node_x[n], w.geom_y[mid] - w.node_y[n])
            hit = [e for e in hit if d[e] <= radius_m]
        return [int(w.edge_id[e]) for e in hit]

    # ---------- internals ----------
    def _need_plan(self):
        if self.plan is None:
            raise RuntimeError("call start() (or resume()) first")

    def _state(self, t: float) -> dict:
        from .sim import simulate
        st = simulate(self.world, self.scn, self.plan, reports=self.reports).state_at(t)
        st["plan_version"] = self.plan["version"]
        return st


def write_seed(scenario_path: str | Path, out: str | Path) -> dict:
    """`ember seed-state`: the backend's starting state (plan v1 at t=0) for a scenario."""
    st = EngineSession(scenario_path).start()
    Path(out).write_text(json.dumps(st, separators=(",", ":")))
    return st
