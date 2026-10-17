"""Facility state machine with dependencies (TECHNICAL.md §3.3).

    ok → backup (a dependency is down and the facility has backup endurance left; endurance counts down)
       → down   (endurance exhausted, or no backup at all, or its own scheduled event says down)
    A connected, compatible generator returns the facility to ok and stops the endurance clock.

Outfalls are not power dependencies: a pumping station "depends on" its outfall for discharge
(see Wastewater.downstream_ok), not for power.
"""

from __future__ import annotations

from dataclasses import dataclass, field

POWER_EXEMPT = {"outfall"}           # depends_on targets that are not power sources
SERVICE_TYPES = {"hospital", "clinic", "pumping_station"}   # counted in service_outage_s_total


def compatible(generator: dict, facility: dict) -> tuple[bool, str]:
    """Can this generator power this facility? (ok, reason)"""
    need_kw, conn = facility.get("power_kw_required"), facility.get("connector")
    if need_kw is None or conn is None:
        return False, f"{facility['id']} has no generator hookup"
    if generator.get("connector") != conn:
        return False, f"connector {generator.get('connector')} ≠ {conn}"
    if generator.get("kw", 0) < need_kw:
        return False, f"{generator.get('kw', 0):.0f} kW < {need_kw:.0f} kW required"
    return True, "compatible"


@dataclass
class FacilityModel:
    facilities: list[dict]
    endurance_scale: float = 1.0          # perturbation: backup endurance × this
    state: dict = field(init=False)
    since: dict = field(init=False)
    endurance: dict = field(init=False)   # total backup seconds available
    used: dict = field(init=False)        # backup seconds consumed
    own: dict = field(init=False)         # state set by the facility's own events
    generator: dict = field(init=False)   # facility id → generator resource id (connected)
    down_s: dict = field(init=False)      # cumulative seconds down

    def __post_init__(self):
        self.by_id = {f["id"]: f for f in self.facilities}
        self.own = {k: f.get("state0", "ok") for k, f in self.by_id.items()}
        self.state = dict(self.own)
        self.since = {k: 0.0 for k in self.by_id}
        self.endurance = {k: float(f.get("backup_endurance_s", 0.0)) * self.endurance_scale for k, f in self.by_id.items()}
        self.used = {k: 0.0 for k in self.by_id}
        self.generator = {}
        self.down_s = {k: 0.0 for k in self.by_id}

    # ---------- inputs ----------
    def connect_generator(self, facility_id: str, resource_id: str):
        self.generator[facility_id] = resource_id

    def disconnect_generator(self, facility_id: str):
        self.generator.pop(facility_id, None)

    def apply_status(self, facility_id: str, fields: dict):
        """A facility_status report: e.g. {"backup_endurance_s": 7200} = 'we have 2 h left from now'."""
        if "backup_endurance_s" in fields:
            self.endurance[facility_id] = float(fields["backup_endurance_s"]) * self.endurance_scale + self.used[facility_id]
        if "state" in fields:
            self.own[facility_id] = fields["state"]

    # ---------- tick ----------
    def step(self, t: float, dt: float) -> list[dict]:
        """Advance to time t (events at t apply now), then account dt seconds. Returns state-change events."""
        for k, f in self.by_id.items():
            for ev in f.get("events", []):
                if t <= ev["t_s"] < t + dt:
                    self.own[k] = ev["state"]
        changes = []
        for _ in range(len(self.by_id)):   # settle dependency chains (bounded: no cycles by validation)
            moved = False
            for k, f in self.by_id.items():
                new = self._resolve(k, f)
                if new != self.state[k]:
                    changes.append({"t_s": t, "kind": "facility_state", "facility_id": k, "from": self.state[k], "to": new})
                    self.state[k], self.since[k] = new, t
                    moved = True
            if not moved:
                break
        for k in self.by_id:
            if self.state[k] == "backup":
                self.used[k] += dt
            elif self.state[k] == "down":
                self.down_s[k] += dt
        return changes

    def _resolve(self, k: str, f: dict) -> str:
        if self.own[k] == "down":
            return "down"
        if k in self.generator:
            return "ok"
        deps = [d for d in f.get("depends_on", []) if self.by_id[d]["type"] not in POWER_EXEMPT]
        if self.own[k] == "backup" or any(self.state[d] == "down" for d in deps):   # reported or forced onto backup
            return "backup" if self.endurance[k] - self.used[k] > 0 else "down"
        return self.own[k]

    # ---------- outputs ----------
    def powered(self, k: str) -> bool:
        return self.state[k] in ("ok", "backup")

    def endurance_left(self, k: str) -> float | None:
        return max(0.0, self.endurance[k] - self.used[k]) if self.state[k] == "backup" else None

    def outage(self) -> tuple[float, float]:
        """(hospital_outage_s, service_outage_s_total)"""
        hosp = sum(s for k, s in self.down_s.items() if self.by_id[k]["type"] == "hospital")
        svc = sum(s for k, s in self.down_s.items() if self.by_id[k]["type"] in SERVICE_TYPES)
        return hosp, svc
