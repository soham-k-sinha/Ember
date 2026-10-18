"""Does nothing. Lets the environment (hazard, closures, snapshots, render) be tested alone."""

from __future__ import annotations



class NoopEngine:
    def reset(self, world, plan, scenario, rng):
        self.closed_count = 0

    def step(self, world, t_s, dt_s, closed, newly_closed):
        self.closed_count = int(closed.sum())

    def snapshot(self, world, t_s):
        return {"t_s": t_s, "closed_edges": self.closed_count}

    def metrics(self, world, t_s):
        return {"closed_edges": self.closed_count}

    def done(self):
        return False
