"""Phone-to-household/facility bindings. Role defaults exist only for the original single-phone demo."""

from __future__ import annotations

import os

from .db import Store, thread_key

ROLES = ("resident", "operator")


def resolve_thread(store: Store, role: str, household_id: int | None = None,
                   facility_id: str | None = None) -> dict | None:
    """Validate an explicit target, or resolve the original demo default for registration."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    if (role == "resident" and facility_id is not None) or (role == "operator" and household_id is not None):
        raise ValueError("Residents use household_id; operators use facility_id.")
    if household_id is not None:
        if not any(h["household_id"] == household_id for h in store.households()):
            raise ValueError(f"Household {household_id} is not in the current scenario; choose an ID from GET /state.")
        return {"household_id": household_id}
    if facility_id is not None:
        if not any(f["id"] == facility_id for f in store.facilities()):
            raise ValueError(f"Facility {facility_id!r} is not in the current scenario.")
        return {"facility_id": facility_id}
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


def phone_thread(store: Store, phone: dict) -> dict | None:
    """Bind legacy role-only rows once; never retarget an explicit binding after a scenario switch."""
    key = phone.get("thread_key")
    if key is None and phone.get("scenario_id") is not None:
        return None  # registered to be placed by its location text, not placed yet (see unplaced())
    if key is None:
        thread = resolve_thread(store, phone["role"])
        if thread is None:
            return None
        store.upsert_phone(phone["handle"], phone["role"], thread_key=thread_key(thread),
                           scenario_id=store.meta().get("scenario_id"))
        return thread
    if phone.get("scenario_id") != store.meta().get("scenario_id"):
        return None
    kind, value = key.split(":", 1)
    try:
        return resolve_thread(store, phone["role"],
                              household_id=int(value) if kind == "household" else None,
                              facility_id=value if kind == "facility" else None)
    except ValueError:
        return None


def unplaced(store: Store, phone: dict) -> bool:
    """A resident phone registered with `locate`: it texts where it is before it has a household."""
    return (phone.get("role") == "resident" and phone.get("thread_key") is None
            and phone.get("scenario_id") is not None and phone.get("scenario_id") == store.meta().get("scenario_id"))


def player(store: Store, handle: str) -> int | None:
    """1-based join order of a drill player (texted the join phrase, D78); None for team phones."""
    n = store.kv_get(f"player:{handle}")
    return int(n) if n else None


def phone_for_thread(store: Store, thread: dict) -> dict | None:
    key = thread_key(thread)
    for phone in store.phones():
        target = phone_thread(store, phone)
        if target and thread_key(target) == key:
            return store.phone(handle=phone["handle"])
    return None


def select_thread(store: Store, role: str, household_id: int | None = None,
                  facility_id: str | None = None) -> dict | None:
    """HTTP selection: a role alone is usable only when it cannot pick the wrong person's chat."""
    if household_id is not None or facility_id is not None:
        return resolve_thread(store, role, household_id, facility_id)
    matches = [t for p in store.phones() if p["role"] == role if (t := phone_thread(store, p))]
    if len(matches) > 1:
        raise ValueError(f"Several {role} phones are registered; specify household_id or facility_id.")
    return matches[0] if matches else resolve_thread(store, role)


def normalize_handle(raw: str) -> str:
    """'617 555 0120' / '6175550120' / '+1 (617) 555-0120' → '+16175550120' (US default). Emails pass through."""
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
