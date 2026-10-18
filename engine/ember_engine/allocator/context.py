"""What a planner knows at time t_now: closures, needs, deadlines, facility threats, fleet, travel times.

Shared by the baseline and the allocator so both see exactly the same inputs (TECHNICAL.md §3.6).
Reports count as known once observed_at_t_s ≤ t_now. Flood keyframes are a forecast: deadlines use
all of them; current closures use the keyframe in effect at t_now.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..models.facilities import FacilityModel
from ..scenario import deadlines, flood_keyframes

UNLOAD_S = 120.0
VEHICLES = ("van", "accessible_van", "ambulance", "truck")
AMBULANCE = "ambulance"   # carries medical cases only (with their stretcher / wheelchair); D114


@dataclass
class Slot:
    """A resource's planning state: where it will be and when it is free."""
    rid: str
    spec: dict
    node: int
    free_at: float
    available: bool = True        # False: busy for the rest of the horizon (e.g. a connected generator)


@dataclass
class Context:
    world: object
    scn: dict
    reports: list = field(default_factory=list)
    t_now: float = 0.0

    def __post_init__(self):
        import shapely

        w, scn, t = self.world, self.scn, self.t_now
        self.known_reports = [r for r in self.reports if float(r["observed_at_t_s"]) <= t + 1e-9]
        frames = flood_keyframes(scn, w)
        cur = [g for ft, g in frames if ft <= t]
        self.closed = shapely.intersects(cur[-1], w.edge_lines()) if cur and not cur[-1].is_empty else np.zeros(w.n_edges, bool)
        self.closed = self.closed.copy()
        for r in self.known_reports:
            if r["kind"] == "closure_report":
                ids = [i for i in r.get("payload", {}).get("edge_ids", []) if 0 <= i < w.n_edges]
                self.closed[ids] = True
        dl = deadlines(scn, w, frames)
        self.deadline = dl["households"]
        self.fac_threatened_at = dl["facilities"]

        rows = {int(h): i for i, h in enumerate(w.hh_id)}
        self.hh = {h["household_id"]: h for h in scn["households"]}
        self.hh_node = {hid: int(w.hh_node[rows[hid]]) for hid in self.hh}
        self.needs = {hid: h["needs"] for hid, h in self.hh.items()}
        for r in sorted(scn.get("scripted_reports", []), key=lambda r: r["t_s"]):
            if r["kind"] == "need" and r["t_s"] <= t and r.get("household_id") in self.needs:
                self.needs[r["household_id"]] = dict(r["needs"])
        for r in self.known_reports:
            if r["kind"] == "need" and r.get("household_id") in self.needs:
                p = r.get("payload", {})
                self.needs[r["household_id"]] = {k: p[k] for k in ("people", "mobility", "accessible_vehicle", "medical") if k in p}

        self.fac = {f["id"]: f for f in scn["facilities"]}
        assets = {a["id"]: a for a in w.assets}
        self.fac_node = {k: w.node_index(f["node"] if "node" in f else assets[f["asset_id"]]["node"]) for k, f in self.fac.items()}
        self.base = next(k for k, f in self.fac.items() if f["type"] in ("response_base", "shelter"))   # where the fleet stages
        self.base_node = self.fac_node[self.base]
        # drop-off points: shelters first on a tie, then response bases (DECISIONS: nearest open drop-off)
        self.dropoffs = sorted((k for k, f in self.fac.items() if f["type"] in ("shelter", "response_base")),
                               key=lambda k: (self.fac[k]["type"] != "shelter", k))
        self._drop: dict = {}
        self.power_risk = self._power_risk()
        self.res = {x["id"]: x for x in scn["resources"]}
        self.banned: set = set()      # (resource id, household id | facility id) a person declined (set by carry_over)
        self._tf, self._tb = {}, {}

    # ---------- facilities ----------
    def _power_risk(self) -> dict:
        """Dry run with no generators: {facility id: (first backup t, first down t)} for facilities that lose grid power."""
        status = [r for r in self.scn.get("scripted_reports", []) if r["kind"] == "facility_status"]
        status += [{"t_s": float(r["observed_at_t_s"]), "facility_id": r.get("facility_id"), "set": r.get("payload", {}).get("set", {})}
                   for r in self.known_reports if r["kind"] == "facility_status"]
        fm = FacilityModel(self.scn["facilities"])
        out, t, dt = {}, 0.0, float(self.scn.get("tick_s", 60.0))
        while t < float(self.scn["t_end_s"]):
            for r in status:
                if t <= float(r["t_s"]) < t + dt and r.get("facility_id") in self.fac and float(r["t_s"]) <= self.t_now + 1e-9:
                    fm.apply_status(r["facility_id"], r.get("set", {}))
            fm.step(t, dt)
            for k, s in fm.state.items():
                if s != "ok":
                    b, d = out.get(k, (None, None))
                    out[k] = (b if b is not None else t, d if d is not None or s != "down" else t)
            t += dt
        return out

    # ---------- travel ----------
    def _weight(self):
        """Road times the planner estimates with: free flow, or the background traffic at t_now (D73)."""
        if not hasattr(self, "_w"):
            from ..traffic_bg import bin_of, table
            mult = table(self.world, self.scn)
            self._w = None if mult is None else self.world.edge_tt * mult[bin_of(self.t_now, mult)]
        return self._w

    def tf(self, node: int) -> np.ndarray:
        if node not in self._tf:
            self._tf[node] = self.world.times_from(node, self.closed, weight=self._weight())
        return self._tf[node]

    def tb(self, node: int) -> np.ndarray:
        if node not in self._tb:
            self._tb[node] = self.world.times_from(node, self.closed, reverse=True, weight=self._weight())
        return self._tb[node]

    def travel(self, spec: dict, a: int, b: int) -> float:
        return float(self.tf(a)[b]) / float(spec.get("speed_factor", 1.0))

    # ---------- fleet ----------
    def fleet(self) -> dict[str, Slot]:
        """Every resource at its start position, free at t_now."""
        out = {}
        for x in self.scn["resources"]:
            node = self.fac_node[x["at_facility"]] if "at_facility" in x else self.world.node_index(x["node"])
            out[x["id"]] = Slot(x["id"], x, node, self.t_now)
        return out

    def eligible(self, spec: dict, hid: int) -> bool:
        need = self.needs[hid]
        if need == "unknown" or spec["kind"] not in VEHICLES or (spec["id"], hid) in self.banned:
            return False
        if (need.get("mobility") or need.get("accessible_vehicle")) and not spec.get("accessible"):
            return False
        if spec["kind"] == AMBULANCE and not need.get("medical"):
            return False
        return spec.get("capacity_people", 0) >= need["people"]

    def off_ambulance(self, queues: dict) -> int:
        """Medical households riding something else although an ambulance could carry them (D114)."""
        amb = [x for x in self.res.values() if x["kind"] == AMBULANCE]
        return sum(1 for rid, hids in queues.items() if self.res[rid]["kind"] != AMBULANCE for h in hids
                   if self.needs[h] != "unknown" and self.needs[h].get("medical") and any(self.eligible(x, h) for x in amb))

    def dropoff_order(self, hid: int) -> list[str]:
        """Drop-off points by drive time from the household on today's open roads (unreachable ones last)."""
        if hid not in self._drop:
            node = self.hh_node[hid]
            self._drop[hid] = sorted(self.dropoffs, key=lambda k: float(self.tb(self.fac_node[k])[node]))
        return self._drop[hid]

    def dropoff_for(self, hid: int) -> str:
        return self.dropoff_order(hid)[0]

    def rescue_cycle(self, slot: Slot, hid: int, dropoff: str | None = None) -> tuple[float, float]:
        """(estimated arrival at the household, time the vehicle is free again at the drop-off)."""
        node = self.hh_node[hid]
        arrive = slot.free_at + self.travel(slot.spec, slot.node, node)
        to = self.fac_node[dropoff or self.dropoff_for(hid)]
        back = float(self.tb(to)[node]) / float(slot.spec.get("speed_factor", 1.0))
        return arrive, arrive + float(slot.spec.get("service_s", 300)) + back + UNLOAD_S

    def after_rescue(self, hid: int, dropoff: str | None = None) -> int:
        """Where the vehicle is once it has unloaded this household."""
        return self.fac_node[dropoff or self.dropoff_for(hid)]
