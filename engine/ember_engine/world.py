"""World: town.json → numpy arrays, routing, geometry lookups."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from .geo import local_projector


@dataclass
class World:
    meta: dict
    center: tuple[float, float]                 # lon, lat
    node_id: np.ndarray                         # (N,) osm ids
    node_lon: np.ndarray
    node_lat: np.ndarray
    node_x: np.ndarray                          # local meters
    node_y: np.ndarray
    edge_id: np.ndarray                         # (E,)
    edge_u: np.ndarray                          # node index
    edge_v: np.ndarray
    edge_len: np.ndarray                        # m
    edge_tt: np.ndarray                         # s (free flow)
    edge_speed: np.ndarray                      # m/s
    edge_cap_vph: np.ndarray
    edge_storage: np.ndarray
    edge_name: list
    edge_highway: list
    # flattened geometry
    geom_x: np.ndarray                          # (V,) local meters
    geom_y: np.ndarray
    geom_cum: np.ndarray                        # (V,) cumulative length within edge, m
    geom_start: np.ndarray                      # (E,) first vertex index of each edge
    geom_count: np.ndarray                      # (E,)
    geom_total: np.ndarray                      # (E,) geometry length, m
    # households
    hh_id: np.ndarray
    hh_lon: np.ndarray
    hh_lat: np.ndarray
    hh_node: np.ndarray                         # node index
    hh_zone: np.ndarray
    hh_size: np.ndarray
    hh_vehicles: np.ndarray
    hh_vulnerable: np.ndarray                   # bool: elderly|mobility|medical
    hh_no_car: np.ndarray
    exits: np.ndarray                           # node indices
    assets: list
    zones: list
    venue: dict
    paths: list = field(default_factory=list)
    _uv_edges: dict = field(default_factory=dict)

    # ---------- construction ----------
    @classmethod
    def load(cls, path: str | Path) -> "World":
        return cls.from_dict(json.loads(Path(path).read_text()))

    @classmethod
    def from_dict(cls, t: dict) -> "World":
        clon, clat = t["meta"]["center"]
        to_xy, _ = local_projector(clon, clat)
        nodes = t["nodes"]
        node_id = np.array([n["id"] for n in nodes], dtype=np.int64)
        idx = {int(n["id"]): i for i, n in enumerate(nodes)}
        node_lon = np.array([n["lon"] for n in nodes]); node_lat = np.array([n["lat"] for n in nodes])
        node_x, node_y = to_xy(node_lon, node_lat)

        edges = t["edges"]
        E = len(edges)
        edge_u = np.array([idx[e["u"]] for e in edges], dtype=np.int64)
        edge_v = np.array([idx[e["v"]] for e in edges], dtype=np.int64)
        edge_len = np.array([e["length_m"] for e in edges], dtype=np.float64)
        edge_tt = np.array([max(e["travel_time_s"], 0.5) for e in edges], dtype=np.float64)
        edge_speed = np.maximum(edge_len / edge_tt, 1.0)
        edge_cap = np.array([e["capacity_vph"] for e in edges], dtype=np.float64)
        edge_storage = np.array([e["storage_veh"] for e in edges], dtype=np.float64)

        gx, gy, gcum, gstart, gcount, gtotal = [], [], [], [], [], []
        pos = 0
        for e in edges:
            coords = np.asarray(e["geom"], dtype=np.float64)
            x, y = to_xy(coords[:, 0], coords[:, 1])
            seg = np.hypot(np.diff(x), np.diff(y))
            cum = np.concatenate([[0.0], np.cumsum(seg)])
            gx.append(x); gy.append(y); gcum.append(cum)
            gstart.append(pos); gcount.append(len(x)); gtotal.append(float(cum[-1]) if len(cum) else 0.0)
            pos += len(x)
        geom_x = np.concatenate(gx); geom_y = np.concatenate(gy); geom_cum = np.concatenate(gcum)

        hh = t["households"]
        hh_node = np.array([idx[h["node"]] for h in hh], dtype=np.int64) if hh else np.zeros(0, dtype=np.int64)
        flags = [h["flags"] for h in hh]
        w = cls(
            meta=t["meta"], center=(clon, clat),
            node_id=node_id, node_lon=node_lon, node_lat=node_lat, node_x=node_x, node_y=node_y,
            edge_id=np.array([e["id"] for e in edges], dtype=np.int64), edge_u=edge_u, edge_v=edge_v,
            edge_len=edge_len, edge_tt=edge_tt, edge_speed=edge_speed, edge_cap_vph=edge_cap,
            edge_storage=edge_storage, edge_name=[e.get("name") for e in edges],
            edge_highway=[e.get("highway") for e in edges],
            geom_x=geom_x, geom_y=geom_y, geom_cum=geom_cum,
            geom_start=np.array(gstart, dtype=np.int64), geom_count=np.array(gcount, dtype=np.int64),
            geom_total=np.array(gtotal, dtype=np.float64),
            hh_id=np.array([h["id"] for h in hh], dtype=np.int64),
            hh_lon=np.array([h["lon"] for h in hh], dtype=np.float64),
            hh_lat=np.array([h["lat"] for h in hh], dtype=np.float64),
            hh_node=hh_node,
            hh_zone=np.array([h["zone"] for h in hh], dtype=np.int64),
            hh_size=np.array([h["size"] for h in hh], dtype=np.int64),
            hh_vehicles=np.array([h["vehicles"] for h in hh], dtype=np.int64),
            hh_vulnerable=np.array([f["elderly"] or f["mobility"] or f["medical"] for f in flags], dtype=bool),
            hh_no_car=np.array([f["no_car"] for f in flags], dtype=bool),
            exits=np.array([idx[n] for n in t["exits"] if n in idx], dtype=np.int64),
            assets=t.get("assets", []), zones=t.get("zones", []), venue=t.get("venue", {}),
            paths=t.get("paths", []),
        )
        uv: dict[tuple[int, int], list[int]] = {}
        for i in range(E):
            uv.setdefault((int(edge_u[i]), int(edge_v[i])), []).append(i)
        w._uv_edges = uv
        return w

    def edge_lines(self) -> np.ndarray:
        """Shapely LineStrings per edge in local meters (cached)."""
        if "_lines" not in self.__dict__:
            import shapely
            pts = np.c_[self.geom_x, self.geom_y]
            idx = np.repeat(np.arange(self.n_edges), self.geom_count)
            self.__dict__["_lines"] = shapely.linestrings(pts, indices=idx)
        return self.__dict__["_lines"]

    def exit_in_edges(self) -> list[np.ndarray]:
        """Per exit (same order as self.exits): indices of edges entering it."""
        return [np.where(self.edge_v == x)[0] for x in self.exits]

    @property
    def n_nodes(self) -> int:
        return len(self.node_id)

    @property
    def n_edges(self) -> int:
        return len(self.edge_id)

    # ---------- routing ----------
    def routing_table(self, closed: np.ndarray | None = None, weight: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """next_edge[node] toward the nearest exit avoiding closed edges (-1 if unreachable),
        plus dist_to_exit[node] in seconds. `weight` overrides free-flow edge times (e.g. congested)."""
        N, E = self.n_nodes, self.n_edges
        w = (self.edge_tt if weight is None else np.asarray(weight, dtype=np.float64)).copy()
        if closed is not None and closed.any():
            w = np.where(closed, np.inf, w)
        ok = np.isfinite(w) & (self.edge_u != self.edge_v)
        # reversed graph: v -> u with weight tt; dijkstra from exits gives dist(node → exit).
        # csr_matrix sums duplicate (row, col) entries, so collapse parallel edges to their minimum first.
        ei = np.where(ok)[0]
        ei = ei[np.lexsort((w[ei], self.edge_u[ei], self.edge_v[ei]))]
        pair = self.edge_v[ei] * N + self.edge_u[ei]
        first = np.ones(len(ei), dtype=bool); first[1:] = pair[1:] != pair[:-1]
        ei = ei[first]
        rev = csr_matrix((w[ei], (self.edge_v[ei], self.edge_u[ei])), shape=(N, N))
        if len(self.exits) == 0:
            return np.full(N, -1, dtype=np.int64), np.full(N, np.inf)
        dist, pred, _src = dijkstra(rev, directed=True, indices=self.exits, min_only=True, return_predecessors=True)
        next_edge = np.full(N, -1, dtype=np.int64)
        for n in range(N):
            p = pred[n]
            if p < 0:
                continue
            cands = [e for e in self._uv_edges.get((n, int(p)), []) if ok[e]]
            if cands:
                next_edge[n] = min(cands, key=lambda e: w[e])
        next_edge[self.exits] = -2   # -2 = at exit
        return next_edge, dist

    # ---------- geometry ----------
    def edge_pos_to_xy(self, edge: np.ndarray, pos_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(edge index, meters along edge) → local x,y. Vectorized."""
        edge = np.asarray(edge, dtype=np.int64); pos_m = np.asarray(pos_m, dtype=np.float64)
        frac = np.clip(pos_m / np.maximum(self.edge_len[edge], 1e-6), 0.0, 1.0)
        gp = frac * self.geom_total[edge]
        start = self.geom_start[edge]; count = self.geom_count[edge]
        x = np.empty(len(edge)); y = np.empty(len(edge))
        for i in range(len(edge)):   # small arrays only (trajectory sampling)
            s, c = start[i], count[i]
            cum = self.geom_cum[s:s + c]
            j = int(np.searchsorted(cum, gp[i], side="right")) - 1
            j = min(max(j, 0), c - 2) if c >= 2 else 0
            if c < 2:
                x[i], y[i] = self.geom_x[s], self.geom_y[s]
                continue
            seg = cum[j + 1] - cum[j]
            f = 0.0 if seg <= 0 else (gp[i] - cum[j]) / seg
            x[i] = self.geom_x[s + j] + f * (self.geom_x[s + j + 1] - self.geom_x[s + j])
            y[i] = self.geom_y[s + j] + f * (self.geom_y[s + j + 1] - self.geom_y[s + j])
        return x, y

    def xy_to_lonlat(self, x, y):
        _, to_ll = local_projector(*self.center)
        return to_ll(x, y)

    def exit_label(self, osm_node: int) -> str:
        """Street name(s) entering an exit node, for logs: 'Memorial Drive@61317667'."""
        k = int(np.where(self.node_id == osm_node)[0][0])
        names = sorted({self.edge_name[e] or self.edge_highway[e] for e in np.where(self.edge_v == k)[0]})
        return f"{'/'.join(names)}@{osm_node}"

    def edge_label(self, e: int) -> str:
        return f"{self.edge_name[e] or self.edge_highway[e]}#{int(self.edge_id[e])}"
