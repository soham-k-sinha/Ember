"""The one place the backend calls ember_engine, through engine's `ember_engine.api.EngineSession` (D42).
Nothing else in residents/ imports ember_engine (except tests' contract checks).

All calls are synchronous CPU work (allocate ≈ 0.5–2 s): callers run them in a worker thread, and the
lock keeps two of them from touching the World's caches at once.
"""

from __future__ import annotations

import gzip
import json
import threading
from pathlib import Path

from .config import REPO_ROOT

CANONICAL_TOWN = REPO_ROOT / "engine" / "data" / "town.json.gz"
FACT_KINDS = ("need", "closure_report", "facility_status")  # what the allocator/simulator act on


class EngineBridge:
    def __init__(self, scenario_path: Path | str, town_path: Path | str | None = None, seed: int = 0,
                 moves: int | None = None):
        from ember_engine.scenario import load_scenario
        from ember_engine.world import World

        self.scenario_path = Path(scenario_path)
        self.scenario = load_scenario(self.scenario_path)
        town_file = Path(town_path) if town_path else self._unpacked_town()
        self.town = json.loads(town_file.read_text())
        self.town_file = town_file
        self.world = World.load(town_file)
        self.seed = seed
        from ember_engine.api import EngineSession
        # moves = allocator local-search budget per (re)plan; None = engine's default (production)
        self.session = EngineSession(self.scenario_path, world=self.world, seed=seed, moves=moves)
        self.moves = moves
        self._lock = threading.Lock()
        self._opt_session = None
        self._opt_lock = threading.Lock()
        self._edges = {e["id"]: e for e in self.town["edges"]}
        self._reverse = {(e["u"], e["v"]): e["id"] for e in self.town["edges"]}
        self._facility_ids = {f["id"] for f in self.scenario["facilities"]}
        self._household_ids = {h["household_id"] for h in self.scenario["households"]}

    @staticmethod
    def _unpacked_town() -> Path:
        """The team's shared town (D29), unpacked once next to the backend's DB."""
        out = REPO_ROOT / "data" / "town.json"
        if not out.exists():
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(gzip.decompress(CANONICAL_TOWN.read_bytes()))
        return out

    @property
    def scenario_id(self) -> str:
        return self.scenario["scenario_id"]

    @property
    def t_end_s(self) -> float:
        return float(self.scenario["t_end_s"])

    @staticmethod
    def engine_reports(reports: list[dict]) -> list[dict]:
        """Only facts go to the engine; confirm/reject/question/other are the backend's business."""
        return [r for r in reports if r["kind"] in FACT_KINDS]

    # ---------- planning (all through engine's EngineSession, D42) ----------
    # The backend's DB is the source of truth: before every call the session is resumed from the stored
    # plan + reports, so a backend restart needs nothing special and the session never drifts from the DB.
    def plan(self, reports: list[dict], t_now: float, prev: dict | None, prev_reports: list[dict] | None,
             trigger: str | None = None) -> dict:
        with self._lock:
            if prev is None:
                self.session.start()
                plan = self.session.plan
            else:
                before = self.engine_reports(prev_reports or [])
                seen = {r["id"] for r in before}
                self.session.resume(prev, before)
                new = [r for r in self.engine_reports(reports) if r["id"] not in seen]
                plan = self.session.add_reports(new, t_now)["plan"]
            if trigger:
                plan["trigger"] = trigger
            return plan

    def state_at(self, plan: dict, reports: list[dict], t_s: float) -> dict:
        """Simulate the current plan with every report known so far → state contract at t_s."""
        with self._lock:
            self.session.resume(plan, self.engine_reports(reports))
            return self.session.state_at(min(max(t_s, 0.0), self.t_end_s))

    def optimize(self, reports: list[dict], t_now: float, prev: dict | None, on_point, seeds: int = 20, k: int = 4) -> dict:
        """Robust fan-out (Daytona if engine/.env has a key, else local processes). Runs on its own
        EngineSession and lock, so replans / state_at (the main session) aren't blocked for its duration."""
        from ember_engine.api import EngineSession
        from ember_engine.world import World
        with self._opt_lock:
            if self._opt_session is None:
                # its own World: World's routing caches are plain dicts that get cleared when they grow, so
                # sharing one World between this thread and replans/state_at could raise KeyError mid-read
                self._opt_session = EngineSession(self.scenario_path, world=World.load(self.town_file),
                                                  seed=self.seed, moves=self.moves)
            self._opt_session.resume(prev, self.engine_reports(reports))
            return self._opt_session.optimize(on_point=on_point, t_now=t_now, seeds=seeds, k=k)["plan"]

    def simulate(self, planner: str, plan: dict | None, reports: list[dict]) -> dict:
        """Projected metrics over the whole horizon for `planner` = "ember" (the current plan) or
        "baseline" (incident-by-incident dispatch on the same reports)."""
        from ember_engine.baseline import baseline_plan
        from ember_engine.sim import simulate
        rep = self.engine_reports(reports)
        with self._lock:
            p = plan if planner == "ember" else baseline_plan(self.world, self.scenario, rep)
            metrics = dict(simulate(self.world, self.scenario, p, reports=rep, record=False).metrics)
        metrics["projected"] = True
        return metrics

    def compare(self, reports: list[dict], seeds: int = 5) -> dict:
        with self._lock:
            self.session.reports = self.engine_reports(reports)  # compare() reads reports only, not the plan
            return self.session.compare(seeds=seeds)

    # ---------- lookups for validating disruptions ----------
    def both_directions(self, edge_ids: list[int]) -> list[int]:
        """A road closure closes both directions: add each edge's reverse twin if the town has one."""
        out: list[int] = []
        for eid in edge_ids:
            e = self._edges[eid]
            for x in (eid, self._reverse.get((e["v"], e["u"]))):
                if x is not None and x not in out:
                    out.append(x)
        return out

    def has_edge(self, eid: int) -> bool:
        return eid in self._edges

    def has_facility(self, fid: str) -> bool:
        return fid in self._facility_ids

    def has_household(self, hid: int) -> bool:
        return hid in self._household_ids

    def edge_name(self, eid: int) -> str:
        return self._edges[eid].get("name") or f"edge {eid}"

    # ---------- street name → edges (for closure reports from texts) ----------
    NEAR_HOUSEHOLD_M = 150.0  # same radius as engine's tested demo beat (edges_by_name, near_household=…)

    def resolve_road(self, road_hint: str, cross_street: str | None, household_id: int | None) -> list[int]:
        """Deterministic: edges of the named street ('River St' → 'River Street'), at the cross street's
        intersection if one is given, else within 150 m of the household (engine's EngineSession.edges_by_name).
        Both directions. [] = can't place it (ask, don't guess). A wider radius closes whole streets and
        can cut a household off entirely (seen live)."""
        named = [e for e in self.town["edges"] if street_matches(e.get("name"), road_hint)]
        if not named:
            return []
        if cross_street:
            cross_nodes = {n for e in self.town["edges"] if street_matches(e.get("name"), cross_street) for n in (e["u"], e["v"])}
            at = [e["id"] for e in named if e["u"] in cross_nodes or e["v"] in cross_nodes]
            if at:
                return self.both_directions(at)
        if household_id is None or household_id not in self._household_ids:
            return []
        near: list[int] = []
        for name in sorted({e["name"] for e in named}):
            near += self.session.edges_by_name(name, near_household=household_id, radius_m=self.NEAR_HOUSEHOLD_M)
        return self.both_directions(sorted(set(near)))


_ABBREV = {"st": "street", "ave": "avenue", "av": "avenue", "rd": "road", "dr": "drive", "blvd": "boulevard",
           "pkwy": "parkway", "sq": "square", "pl": "place", "ct": "court", "ln": "lane", "hwy": "highway",
           "ter": "terrace", "terr": "terrace", "n": "north", "s": "south", "e": "east", "w": "west", "mt": "mount"}


def normalize_street(name: str) -> str:
    words = "".join(ch.lower() if ch.isalnum() else " " for ch in name).split()
    words = [w for w in words if w != "the"]
    return " ".join(_ABBREV.get(w, w) for w in words)


def street_matches(edge_name: str | None, hint: str) -> bool:
    """'River St' ~ 'River Street'; 'Western Ave bridge' ~ 'Western Avenue'. Needs ≥ 1 non-generic word."""
    if not edge_name:
        return False
    a, b = normalize_street(edge_name), normalize_street(hint)
    if not a or not b:
        return False
    if a == b or (" " + a + " ") in (" " + b + " ") or (" " + b + " ") in (" " + a + " "):
        generic = {"street", "avenue", "road", "drive", "boulevard", "parkway", "square", "place", "court", "lane", "bridge"}
        return bool(set(a.split()) & set(b.split()) - generic)
    return False
