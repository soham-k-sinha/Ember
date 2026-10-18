"""Wastewater storage and overflow at a pumping station — the sustainability mechanism (TECHNICAL.md §3.3).

Per tick:  pumped = min(pump_m3ph, what is there to pump) if powered and downstream ok, else 0
           storage += (inflow − pumped)·dt;   anything above storage_max spills: overflow_m3 += excess
"""

from __future__ import annotations

from dataclasses import dataclass, field


def step_value(series, t: float) -> float:
    """[[t_s, value], ...] step function (latest t_s ≤ t), or a constant."""
    if not isinstance(series, list):
        return float(series)
    v = float(series[0][1])
    for ts, val in series:
        if ts <= t:
            v = float(val)
    return v


@dataclass
class Wastewater:
    params: dict                  # scenario facility["wastewater"]
    storage_scale: float = 1.0    # perturbation: storage_max × this
    inflow_scale: float = 1.0     # perturbation: inflow × this
    lead_s: float = 0.0           # perturbation: the storm runs this far ahead of the inflow forecast
    storage: float = field(init=False)
    overflow: float = field(init=False, default=0.0)
    inflow: float = field(init=False, default=0.0)
    pumped: float = field(init=False, default=0.0)
    overflow_started_t: float | None = field(init=False, default=None)

    def __post_init__(self):
        self.storage = float(self.params["storage_m3"])
        self.storage_max = float(self.params["storage_max_m3"]) * self.storage_scale
        self.pump = float(self.params["pump_m3ph"])

    def step(self, t: float, dt: float, powered: bool, downstream_ok: bool = True) -> float:
        """Advance dt seconds from t. Returns m³ overflowed this tick."""
        self.inflow = step_value(self.params["inflow_m3ph"], t + self.lead_s) * self.inflow_scale
        can_pump = powered and downstream_ok and self.params.get("downstream_ok", True)
        available_m3ph = self.inflow + self.storage * 3600.0 / dt
        self.pumped = min(self.pump, available_m3ph) if can_pump else 0.0
        self.storage += (self.inflow - self.pumped) * dt / 3600.0
        spill = 0.0
        if self.storage > self.storage_max:
            spill = self.storage - self.storage_max
            self.storage = self.storage_max
            self.overflow += spill
            if self.overflow_started_t is None:
                self.overflow_started_t = t
        return spill
