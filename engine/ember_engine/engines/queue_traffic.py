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

    def trajectories(self, world, follow_roads: bool = False) -> list[dict]:
        """Sampled vehicles → [{id, path:[[lon,lat],...], t:[s,...]}] for deck.gl TripsLayer.

        follow_roads: also emit every road-geometry vertex and junction a car passes between two samples
        (times by distance), so a straight line between samples never cuts a corner. Needs a snapshot every
        tick: a car changes edge at most once per tick, so consecutive samples are on the same or adjacent edges."""
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
            if follow_roads:
                ts_k, x, y, s = _along_roads(world, ts, e, p, s, x, y)
            else:
                ts_k = ts
            lon, lat = world.xy_to_lonlat(x, y)
            # keep both ends of every stationary run so TripsLayer doesn't interpolate a slow creep
            chg = (np.abs(np.diff(lon)) > 1e-7) | (np.abs(np.diff(lat)) > 1e-7) | (np.diff(s) != 0)
            keep = np.ones(len(ts_k), dtype=bool)
            keep[1:-1] = chg[:-1] | chg[1:]
            if follow_roads:
                keep[np.where(keep)[0]] = _simplify(ts_k[keep], x[keep], y[keep])
            out.append({"id": int(world.hh_id[self.hh[vi]]),
                        "path": [[round(float(a), 6), round(float(b), 6)] for a, b in zip(lon[keep], lat[keep])],
                        "t": [round(float(t), 1) for t in ts_k[keep]],
                        "final": int(s[-1])})
        return out


def _along_roads(world, ts, e, p, s, x, y):
    """Insert the geometry vertices (and the junction) between consecutive samples of one vehicle."""
    T, X, Y, S = [ts[:1]], [x[:1]], [y[:1]], [s[:1]]
    gc, gx, gy = world.geom_cum, world.geom_x, world.geom_y

    def verts(edge, g0, g1):
        a, c = int(world.geom_start[edge]), int(world.geom_count[edge])
        cum = gc[a:a + c]
        k = np.where((cum > g0 + 1e-6) & (cum < g1 - 1e-6))[0]
        return [(float(cum[j]) - g0, float(gx[a + j]), float(gy[a + j])) for j in k]

    def g(edge, pos):
        return float(np.clip(pos / max(world.edge_len[edge], 1e-6), 0.0, 1.0) * world.geom_total[edge])

    # only ticks where the car moved need work; the rest are copied through in slices
    moved = np.where((e[1:] >= 0) & (e[:-1] >= 0) & ((e[1:] != e[:-1]) | (p[1:] > p[:-1])))[0] + 1
    prev = 0
    for i in moved:
        T.append(ts[prev + 1:i]); X.append(x[prev + 1:i]); Y.append(y[prev + 1:i]); S.append(s[prev + 1:i])
        e0, e1 = int(e[i - 1]), int(e[i])
        mid: list = []  # (distance from the previous sample, x, y)
        if e0 == e1:
            mid = verts(e0, g(e0, p[i - 1]), g(e0, p[i]))
        elif world.edge_v[e0] == world.edge_u[e1]:
            g0 = g(e0, p[i - 1])
            rest = float(world.geom_total[e0]) - g0
            mid = verts(e0, g0, float(world.geom_total[e0]) + 1.0)  # up to and including the junction
            mid += [(rest + d, vx, vy) for d, vx, vy in verts(e1, 0.0, g(e1, p[i]))]
        if mid:
            total = mid[-1][0] + float(np.hypot(x[i] - mid[-1][1], y[i] - mid[-1][2]))
            T.append(np.array([ts[i - 1] + (ts[i] - ts[i - 1]) * (d / max(total, 1e-6)) for d, _, _ in mid]))
            X.append(np.array([vx for _, vx, _ in mid])); Y.append(np.array([vy for _, _, vy in mid]))
            S.append(np.full(len(mid), s[i]))
        T.append(ts[i:i + 1]); X.append(x[i:i + 1]); Y.append(y[i:i + 1]); S.append(s[i:i + 1])
        prev = i
    T.append(ts[prev + 1:]); X.append(x[prev + 1:]); Y.append(y[prev + 1:]); S.append(s[prev + 1:])
    return np.concatenate(T), np.concatenate(X), np.concatenate(Y), np.concatenate(S)


def _simplify(t, x, y, tol_m: float = 1.5) -> np.ndarray:
    """Douglas–Peucker on synchronized distance: drop a point when the car, moving linearly in time between
    the kept neighbours, would be within tol_m of where it really was at that moment."""
    n = len(t)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        span = t[b] - t[a]
        f = (t[a + 1:b] - t[a]) / span if span > 0 else np.zeros(b - a - 1)
        err = np.hypot(x[a] + (x[b] - x[a]) * f - x[a + 1:b], y[a] + (y[b] - y[a]) * f - y[a + 1:b])
        k = int(np.argmax(err))
        if err[k] > tol_m:
            m = a + 1 + k
            keep[m] = True
            stack += [(a, m), (m, b)]
    return keep
