"""Plan simulator: run a plan on a scenario, get metrics, outcomes, a replay and state snapshots."""

from .example_plan import example_plan
from .plan_sim import SimResult, simulate

__all__ = ["SimResult", "example_plan", "simulate"]
