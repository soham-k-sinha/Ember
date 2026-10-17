"""Which conversation thread a tester phone stands for, resolved against the current state.

Phones are registered by role, not by household/facility id, because ids differ between the state
fixture (judge #492, `mt_auburn`) and allston_flood_v1 (judge #10296, `mt-auburn`).
- resident → the judge's household (fallback: the first household with phone_role "resident")
- operator → OPERATOR_FACILITY_ID if set, else the critical hospital (fallback: any hospital)
"""

from __future__ import annotations

import os

from .db import Store, thread_key

ROLES = ("resident", "operator")


def resolve_thread(store: Store, role: str) -> dict | None:
    if role == "resident":
        hh = store.households()
        pick = next((h for h in hh if h.get("judge")), None) or next((h for h in hh if h.get("phone_role") == "resident"), None)
        return {"household_id": pick["household_id"]} if pick else None
    if role == "operator":
        fac = store.facilities()
        want = os.environ.get("OPERATOR_FACILITY_ID")
        pick = (next((f for f in fac if f["id"] == want), None) if want else None) \
            or next((f for f in fac if f["type"] == "hospital" and f.get("critical")), None) \
            or next((f for f in fac if f["type"] == "hospital"), None)
        return {"facility_id": pick["id"]} if pick else None
    raise ValueError(f"unknown role {role!r}")


def role_for_thread(store: Store, thread: dict) -> str | None:
    """Inverse: which role (if any) has a phone on this thread."""
    key = thread_key(thread)
    for role in ROLES:
        t = resolve_thread(store, role)
        if t is not None and thread_key(t) == key and store.phone(role=role):
            return role
    return None


def normalize_handle(raw: str) -> str:
    """'413 362 0520' / '4133620520' / '+1 (413) 362-0520' → '+14133620520' (US default). Emails pass through."""
    raw = raw.strip()
    if "@" in raw:
        return raw.lower()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValueError(f"can't read {raw!r} as a phone number")
