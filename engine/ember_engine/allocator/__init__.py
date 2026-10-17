"""EMBER allocator: candidate plans + local search, scored by the plan simulator (TECHNICAL.md §3.5)."""

from .context import Context
from .search import allocate, objective

__all__ = ["Context", "allocate", "objective"]
