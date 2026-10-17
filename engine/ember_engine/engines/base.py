"""Engine plug-in interface. One tick = one call to step()."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class Engine(Protocol):
    def reset(self, world, plan: dict, scenario: dict, rng: np.random.Generator) -> None:
        ...

    def step(self, world, t_s: float, dt_s: float, closed: np.ndarray, newly_closed: np.ndarray) -> None:
        """Advance one tick. `closed` is the current closed-edge mask; `newly_closed` the edges
        that closed this tick (indices)."""
        ...

    def snapshot(self, world, t_s: float) -> dict:
        """Lightweight state for the renderer (edge occupancy, state counts, sample positions)."""
        ...

    def metrics(self, world, t_s: float) -> dict:
        ...

    def done(self) -> bool:
        ...
