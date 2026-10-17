"""Resource movement on the closed-edge-aware graph (TECHNICAL.md §3.3).

A mover drives edge by edge at free-flow speed (× speed_factor, ÷ travel-time multiplier). At every
node it checks the road ahead: if the next edge has closed it re-routes from there; with no open
route it stalls (and retries every tick; stall time counts as delay). If water closes the edge it
is on, it turns back to the node it came from. Fuel burns per km; an empty tank means out of service.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Mover:
    world: object
    rid: str
    node: int                         # node index (where it is, or the node it left)
    speed_factor: float = 1.0
    fuel_l: float = float("inf")
    fuel_l_per_km: float = 0.0
    tt_mult: float = 1.0              # perturbation: travel times × this
    dest: int | None = field(default=None)
    route: list = field(default_factory=list)
    edge: int = -1                    # edge being traversed (-1 = at a node)
    toward: int = -1                  # node index it is driving toward on that edge
    rem_s: float = 0.0                # seconds left on the edge
    full_s: float = 0.0
    km: float = 0.0
    stall_s: float = 0.0
    out_of_fuel: bool = False

    def go(self, dest: int, closed: np.ndarray):
        self.dest = dest
        self.route = []
        if self.edge < 0:
            self._plan(closed)

    def at_dest(self) -> bool:
        return self.edge < 0 and self.dest is not None and self.node == self.dest

    def _edge_s(self, e: int) -> float:
        return float(self.world.edge_tt[e]) * self.tt_mult / self.speed_factor

    def _plan(self, closed: np.ndarray) -> bool:
        path, _ = self.world.route(self.node, self.dest, closed)
        self.route = list(path)
        return bool(path) or self.node == self.dest

    def eta_s(self, closed: np.ndarray) -> float:
        """Seconds to reach dest from here at current closures (inf if cut off)."""
        if self.dest is None:
            return 0.0
        start = self.toward if self.edge >= 0 else self.node
        _, tt = self.world.route(start, self.dest, closed)
        return (self.rem_s if self.edge >= 0 else 0.0) + tt * self.tt_mult / self.speed_factor

    def advance(self, dt: float, closed: np.ndarray) -> str:
        """Move for dt seconds. Returns 'arrived' | 'moving' | 'stalled' | 'idle' | 'no_fuel'."""
        if self.out_of_fuel:
            return "no_fuel"
        if self.dest is None:
            return "idle"
        w = self.world
        budget = dt
        # water reached the edge we're on: turn back to where we came from
        if self.edge >= 0 and closed[self.edge] and self.toward == int(w.edge_v[self.edge]):
            self.toward = int(w.edge_u[self.edge])
            self.rem_s = self.full_s - self.rem_s
            self.route = []
        while budget > 1e-9:
            if self.edge >= 0:
                use = min(budget, self.rem_s)
                self.rem_s -= use
                budget -= use
                km = use / self.full_s * float(w.edge_len[self.edge]) / 1000.0 if self.full_s > 0 else 0.0
                self.km += km
                if self.fuel_l_per_km:
                    self.fuel_l -= km * self.fuel_l_per_km
                    if self.fuel_l <= 0:
                        self.fuel_l, self.out_of_fuel = 0.0, True
                        return "no_fuel"
                if self.rem_s <= 1e-9:
                    self.node, self.edge, self.rem_s = self.toward, -1, 0.0
                continue
            if self.node == self.dest:
                return "arrived"
            if not self.route or closed[self.route[0]] or int(w.edge_u[self.route[0]]) != self.node:
                if not self._plan(closed):
                    self.stall_s += budget
                    return "stalled"
            e = self.route.pop(0)
            self.edge, self.toward = e, int(w.edge_v[e])
            self.full_s = self.rem_s = self._edge_s(e)
        return "arrived" if self.at_dest() else "moving"

    def lonlat(self) -> tuple[float, float]:
        w = self.world
        if self.edge < 0:
            return float(w.node_lon[self.node]), float(w.node_lat[self.node])
        done = 1.0 - self.rem_s / self.full_s if self.full_s > 0 else 1.0
        frac = done if self.toward == int(w.edge_v[self.edge]) else 1.0 - done
        x, y = w.edge_pos_to_xy(np.array([self.edge]), np.array([frac * w.edge_len[self.edge]]))
        lon, lat = w.xy_to_lonlat(x, y)
        return float(lon[0]), float(lat[0])
