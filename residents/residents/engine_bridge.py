"""The one place the backend calls ember_engine. Swap internals here when engine's wrapper lands;
nothing else in residents/ imports ember_engine (except tests' contract checks).

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
    def __init__(self, scenario_path: Path | str, town_path: Path | str | None = None,
                 moves: int | None = None, seed: int = 0):
        from ember_engine.scenario import load_scenario
        from ember_engine.world import World

        self.scenario_path = Path(scenario_path)
        self.scenario = load_scenario(self.scenario_path)
        town_file = Path(town_path) if town_path else self._unpacked_town()
        self.town = json.loads(town_file.read_text())
        self.world = World.load(town_file)
        self.moves, self.seed = moves, seed
        self._lock = threading.Lock()
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

    # ---------- planning ----------
    def plan(self, reports: list[dict], t_now: float, prev: dict | None, prev_reports: list[dict] | None,
             trigger: str | None = None) -> dict:
        from ember_engine.allocator import allocate
        with self._lock:
            return allocate(self.world, self.scenario, reports=self.engine_reports(reports), t_now=t_now, prev=prev,
                            prev_reports=self.engine_reports(prev_reports) if prev_reports is not None else None,
                            seed=self.seed, moves=self.moves, trigger=trigger)

    def state_at(self, plan: dict, reports: list[dict], t_s: float) -> dict:
        """Simulate the current plan with every report known so far → state contract at t_s."""
        from ember_engine.sim import simulate
        with self._lock:
            res = simulate(self.world, self.scenario, plan, reports=self.engine_reports(reports))
            return res.state_at(min(max(t_s, 0.0), self.t_end_s))

    def compare(self, reports: list[dict], seeds: int = 5) -> dict:
        from ember_engine.compare import compare
        with self._lock:
            return compare(self.world, self.scenario, seeds=seeds, reports=self.engine_reports(reports), seed=self.seed)

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
