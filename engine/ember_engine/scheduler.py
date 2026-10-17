"""Tick loop: hazard → engine → snapshots."""

from __future__ import annotations

import time

import numpy as np


class Simulation:
    def __init__(self, world, hazard, engine, plan: dict | None = None, scenario: dict | None = None,
                 dt_s: float = 10.0, seed: int = 1):
        self.world, self.hazard, self.engine = world, hazard, engine
        self.plan, self.scenario = plan or {}, scenario or {}
        self.dt = dt_s
        self.t = 0.0
        self.rng = np.random.default_rng(int(self.scenario.get("seed", seed)))
        self.engine.reset(world, self.plan, self.scenario, self.rng)
        self._closed = np.zeros(world.n_edges, dtype=bool)
        self.snapshots: list[dict] = []

    def step(self):
        closed = self.hazard.closed_mask_at(self.t, self.world)
        newly = np.where(closed & ~self._closed)[0]
        self.engine.step(self.world, self.t, self.dt, closed, newly)
        self._closed = closed
        self.t += self.dt

    def run(self, T_s: float, snapshot_every: int = 6, stop_when_done: bool = True, verbose: bool = False) -> dict:
        t0 = time.time()
        n = 0
        while self.t < T_s:
            if n % snapshot_every == 0:
                self.snapshots.append(self.engine.snapshot(self.world, self.t))
            self.step()
            n += 1
            if stop_when_done and self.engine.done():
                break
            if verbose and n % 60 == 0:
                print(f"  t={self.t:6.0f}s  {self.snapshots[-1]['counts'] if 'counts' in self.snapshots[-1] else ''}")
        self.snapshots.append(self.engine.snapshot(self.world, self.t))
        m = self.engine.metrics(self.world, self.t)
        m["ticks"] = n
        m["wall_s"] = round(time.time() - t0, 3)
        return m
