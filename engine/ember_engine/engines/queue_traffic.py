"""Queue traffic engine v0: per-edge point queues with spillback and capacity limits.

Vehicles: one per household with >= 1 vehicle. States:
    0 waiting (at home)  1 moving  2 queued (at edge end, blocked)  3 exited  4 exposed  5 stuck (no route)

Routing is a single reverse Dijkstra from all exits (world.routing_table), recomputed when
the closed set changes and every `reroute_every_s` with congested weights
(free-flow time + time to discharge the queue already on the edge). Vehicles follow
next_edge[node] dynamically, so closures re-route everyone without per-vehicle pathfinding.

Effective storage is floored at 2 ticks of capacity (synthetic): with jam-density storage alone a
13 m edge holds 2 vehicles and throttles a 1,800 veh/h road to a few hundred veh/h.
"""

from __future__ import annotations

import numpy as np

WAITING, MOVING, QUEUED, EXITED, EXPOSED, STUCK = 0, 1, 2, 3, 4, 5


class QueueTrafficEngine:
    def __init__(self, n_traj: int = 1500, reroute_every_s: float = 60.0):
        self.n_traj = n_traj
        self.reroute_every_s = reroute_every_s

    # ---------- setup ----------
    def reset(self, world, plan: dict, scenario: dict, rng: np.random.Generator):
        self.world = world
        self.plan, self.scenario = plan, scenario
        hh = np.where(world.hh_vehicles >= 1)[0]
        self.N = len(hh)
        self.hh = hh
        self.home = world.hh_node[hh]
        zone = world.hh_zone[hh]

        order_t = float(plan.get("order_t_s", 0.0))
        offsets = plan.get("zone_offsets_s", {})
        zoff = np.array([float(offsets.get(str(int(z)), offsets.get(int(z), 0.0))) for z in zone])
        compliance = float(scenario.get("compliance", 1.0))
        follows = rng.random(self.N) < compliance
        mobil = rng.lognormal(mean=np.log(float(scenario.get("mobilization_median_s", 900.0))),
                              sigma=float(scenario.get("mobilization_sigma", 0.6)), size=self.N)
        self.depart = order_t + np.where(follows, zoff, 0.0) + mobil

        self.state = np.full(self.N, WAITING, dtype=np.int8)
        self.edge = np.full(self.N, -1, dtype=np.int64)
        self.pos = np.zeros(self.N)
        self.exit_t = np.full(self.N, np.nan)
        self.count = np.zeros(world.n_edges)
        self.credit = np.zeros(world.n_edges)
        self.cap_tick = None
        self._dt = None
        self.exit_in = world.exit_in_edges()
        self.exit_closed_t = np.full(len(world.exits), np.nan)
        self.closed = np.zeros(world.n_edges, dtype=bool)
        self.next_edge, _ = world.routing_table(self.closed)
        self.storage = world.edge_storage.astype(np.float64)
        self._last_reroute = 0.0
        self.max_queue = 0
        self.first_closure_s = None
        self.closure_order: list = []
        self.traj_idx = np.sort(rng.choice(self.N, size=min(self.n_traj, self.N), replace=False)) if self.N else np.zeros(0, dtype=np.int64)
        self.traj: list = []   # (t, edge[], pos[], state[])
        self._t = 0.0
        self.extra_closed = np.zeros(world.n_edges, dtype=bool)
        for e in plan.get("closed_edges", []):
            self.extra_closed[int(e)] = True

    # ---------- tick ----------
    def step(self, world, t_s, dt_s, closed, newly_closed):
        self._t = t_s
        if self.cap_tick is None or self._dt != dt_s:
            self._dt = dt_s
            self.cap_tick = world.edge_cap_vph * dt_s / 3600.0
            self.storage = np.maximum(world.edge_storage, np.ceil(2.0 * self.cap_tick))
        closed_all = closed | self.extra_closed
        if not np.array_equal(closed_all, self.closed):
            new = closed_all & ~self.closed
            if new.any():
                if self.first_closure_s is None:
                    self.first_closure_s = t_s
                for e in np.where(new)[0]:
                    self.closure_order.append([int(world.edge_id[e]), float(t_s), world.edge_label(int(e))])
                # an exit closes when every edge into it is closed
                for k, ins in enumerate(self.exit_in):
                    if np.isnan(self.exit_closed_t[k]) and len(ins) and closed_all[ins].all():
                        self.exit_closed_t[k] = t_s
                # vehicles on newly closed edges are exposed
                on = (self.state == MOVING) | (self.state == QUEUED)
                hit = on & new[np.maximum(self.edge, 0)] & (self.edge >= 0)
                if hit.any():
                    np.subtract.at(self.count, self.edge[hit], 1)
                    self.state[hit] = EXPOSED
                    self.exit_t[hit] = t_s
            self.closed = closed_all.copy()
            self._reroute(world, t_s)
        elif t_s - self._last_reroute >= self.reroute_every_s:
            self._reroute(world, t_s)

        self.credit = np.minimum(self.credit + self.cap_tick, 2.0 * self.cap_tick)

        # 1) departures
        dep = (self.state == WAITING) & (self.depart <= t_s)
        if dep.any():
            idx = np.where(dep)[0]
            ne = self.next_edge[self.home[idx]]
            for i, e in zip(idx, ne):
                if e == -2:          # home node is an exit
                    self.state[i] = EXITED; self.exit_t[i] = t_s
                elif e < 0:
                    self.state[i] = STUCK
                elif self.count[e] < self.storage[e]:
                    self.state[i] = MOVING; self.edge[i] = e; self.pos[i] = 0.0; self.count[e] += 1
                # else wait at home (driveway) until storage frees

        # 2) movement with simple congestion slowdown
        mv = self.state == MOVING
        if mv.any():
            e = self.edge[mv]
            occ = self.count[e] / self.storage[e]
            v = world.edge_speed[e] * np.clip(1.0 - 0.8 * occ, 0.2, 1.0)
            self.pos[mv] = np.minimum(self.pos[mv] + v * dt_s, world.edge_len[e])
            at_end = np.where(mv)[0][self.pos[mv] >= world.edge_len[e] - 1e-6]
            self.state[at_end] = QUEUED

        # 3) transfers (Python loop over vehicles at edge ends; ordered by edge for fairness)
        q = np.where(self.state == QUEUED)[0]
        if len(q):
            q = q[np.argsort(self.edge[q], kind="stable")]
            for i in q:
                e = self.edge[i]
                if self.credit[e] < 1.0:
                    continue
                node = world.edge_v[e]
                ne = self.next_edge[node]
                if ne == -2:                                  # reached an exit node
                    self.credit[e] -= 1.0; self.count[e] -= 1
                    self.state[i] = EXITED; self.exit_t[i] = t_s   # keep edge: trajectory ends at the exit
                elif ne < 0:
                    continue                                   # no route right now; wait
                elif self.count[ne] < self.storage[ne]:
                    self.credit[e] -= 1.0; self.count[e] -= 1; self.count[ne] += 1
                    self.edge[i] = ne; self.pos[i] = 0.0; self.state[i] = MOVING
        self.max_queue = max(self.max_queue, int((self.state == QUEUED).sum()))

    def _reroute(self, world, t_s):
        queue_delay = self.count / np.maximum(world.edge_cap_vph / 3600.0, 1e-6)
        self.next_edge, _ = world.routing_table(self.closed, weight=world.edge_tt + queue_delay)
        self._last_reroute = t_s

    # ---------- outputs ----------
    def snapshot(self, world, t_s):
        if len(self.traj_idx):
            self.traj.append((float(t_s), self.edge[self.traj_idx].copy(), self.pos[self.traj_idx].copy(), self.state[self.traj_idx].copy()))
        occ = self.count / np.maximum(self.storage, 1.0)
        return {
            "t_s": float(t_s),
            "counts": {"waiting": int((self.state == WAITING).sum()), "moving": int((self.state == MOVING).sum()),
                       "queued": int((self.state == QUEUED).sum()), "exited": int((self.state == EXITED).sum()),
                       "exposed": int((self.state == EXPOSED).sum()), "stuck": int((self.state == STUCK).sum())},
            "occupancy": occ.astype(np.float32),
            "closed": np.where(self.closed)[0],
        }

    def metrics(self, world, t_s):
        departed = self.state != WAITING
        done = (self.state == EXITED) | (self.state == EXPOSED)
        exited = self.state == EXITED
        n_dep = int(departed.sum())
        clearance = None
        if n_dep and exited.sum() >= 0.95 * max(n_dep, 1):
            clearance = float(np.nanpercentile(self.exit_t[exited], 95))
        travel = np.where(np.isnan(self.exit_t), t_s, self.exit_t) - self.depart
        travel = np.clip(travel[departed], 0, None)
        vul = world.hh_vulnerable[self.hh]
        vdel = travel[vul[departed]] if vul.any() else np.zeros(0)
        return {
            "vehicles": int(self.N),
            "departed": n_dep,
            "exited": int(exited.sum()),
            "exposed_vehicles": int((self.state == EXPOSED).sum()),
            "stuck": int((self.state == STUCK).sum()),
            "still_moving_or_queued": int(((self.state == MOVING) | (self.state == QUEUED)).sum()),
            "clearance_s_95": clearance,
            "max_queue_veh": int(self.max_queue),
            "vulnerable_delay_s_mean": float(vdel.mean()) if len(vdel) else None,
            "vehicle_hours": float(travel.sum() / 3600.0),
            "first_closure_s": self.first_closure_s,
            "closure_order": self.closure_order[:25],
            "exit_closure_order": self._exit_closure_order(world),
            "closed_edges": int(self.closed.sum()),
            "t_s": float(t_s),
        }

    def _exit_closure_order(self, world) -> list:
        """[[exit osm node id, t_s], ...] sorted by closing time (closed exits only)."""
        k = np.where(~np.isnan(self.exit_closed_t))[0]
        k = k[np.argsort(self.exit_closed_t[k], kind="stable")]
        return [[int(world.node_id[world.exits[i]]), float(self.exit_closed_t[i])] for i in k]

    def done(self):
        return bool(np.all((self.state == EXITED) | (self.state == EXPOSED) | (self.state == STUCK))) and self.N > 0

    def trajectories(self, world) -> list[dict]:
        """Sampled vehicles → [{id, path:[[lon,lat],...], t:[s,...]}] for deck.gl TripsLayer."""
        out = []
        if not self.traj:
            return out
        ts = np.array([f[0] for f in self.traj])
        edges = np.stack([f[1] for f in self.traj])      # (T, K)
        poss = np.stack([f[2] for f in self.traj])
        states = np.stack([f[3] for f in self.traj])
        home = self.home[self.traj_idx]
        for k, vi in enumerate(self.traj_idx):
            e, p, s = edges[:, k], poss[:, k], states[:, k]
            on_road = e >= 0
            x = np.full(len(ts), world.node_x[home[k]]); y = np.full(len(ts), world.node_y[home[k]])
            if on_road.any():
                xx, yy = world.edge_pos_to_xy(e[on_road], p[on_road])
                x[on_road], y[on_road] = xx, yy
            # after exit, hold the last position
            ended = (s == EXITED) | (s == EXPOSED)
            if ended.any():
                last = int(np.argmax(ended))
                x[last:], y[last:] = x[last], y[last]
            lon, lat = world.xy_to_lonlat(x, y)
            # keep both ends of every stationary run so TripsLayer doesn't interpolate a slow creep
            chg = (np.abs(np.diff(lon)) > 1e-7) | (np.abs(np.diff(lat)) > 1e-7) | (np.diff(s) != 0)
            keep = np.ones(len(ts), dtype=bool)
            keep[1:-1] = chg[:-1] | chg[1:]
            out.append({"id": int(world.hh_id[self.hh[vi]]),
                        "path": [[round(float(a), 6), round(float(b), 6)] for a, b in zip(lon[keep], lat[keep])],
                        "t": [round(float(t), 1) for t in ts[keep]],
                        "final": int(s[-1])})
        return out
