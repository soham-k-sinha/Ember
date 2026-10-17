"""SQLite shared state (TECHNICAL.md §2).

Each table keeps the columns we query on plus a `data` column holding the contract object verbatim
(state / assignment / report schemas). `snapshot()` reassembles the state contract from the rows, so
GET /state is exactly what the contract says, with no mapping layer in between.

One connection guarded by a lock: FastAPI runs sync handlers in a thread pool, and the load here
is a few requests per second, so serializing access is simpler than per-thread connections.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                      -- JSON
);
CREATE TABLE IF NOT EXISTS closures (
    edge_id INTEGER PRIMARY KEY,
    ord     INTEGER NOT NULL,
    source  TEXT NOT NULL,
    data    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS households (
    household_id INTEGER PRIMARY KEY,
    ord          INTEGER NOT NULL,
    status       TEXT NOT NULL,
    data         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facilities (
    id    TEXT PRIMARY KEY,
    ord   INTEGER NOT NULL,
    state TEXT NOT NULL,
    data  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resources (
    id     TEXT PRIMARY KEY,
    ord    INTEGER NOT NULL,
    status TEXT NOT NULL,
    data   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    household_id INTEGER,
    facility_id  TEXT,
    resolved     INTEGER NOT NULL DEFAULT 0,
    data         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    version        INTEGER PRIMARY KEY,
    parent_version INTEGER,
    data           TEXT NOT NULL,            -- the plan object without `assignments`
    reports_used   TEXT NOT NULL DEFAULT '[]' -- live report ids the allocator saw (next replan's prev_reports)
);
CREATE TABLE IF NOT EXISTS assignments (
    plan_version INTEGER NOT NULL,
    id           TEXT NOT NULL,              -- stable across versions for the same resource → target
    ord          INTEGER NOT NULL,
    resource_id  TEXT NOT NULL,
    status       TEXT NOT NULL,
    data         TEXT NOT NULL,
    PRIMARY KEY (plan_version, id)
);
CREATE TABLE IF NOT EXISTS messages (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    thread_key   TEXT NOT NULL,              -- 'household:492' | 'facility:mt_auburn'
    direction    TEXT NOT NULL,
    plan_version INTEGER,
    external_id  TEXT UNIQUE,                -- Photon message id (dedupes inbound redeliveries)
    delivery     TEXT,                       -- outbound: pending | sent | failed | dev | no_phone | not_opted_in
    data         TEXT NOT NULL               -- the state.messages[] object, verbatim
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages (thread_key, seq);
-- Tester phones. Not scenario state: kept across reseeds. The thread is resolved from `role` against
-- the current state (resident → the judge's household, operator → the critical hospital), so the
-- same phones work for the fixture and for allston_flood_v1.
CREATE TABLE IF NOT EXISTS phones (
    handle          TEXT PRIMARY KEY,        -- E.164, e.g. +14135550100
    role            TEXT NOT NULL UNIQUE,    -- resident | operator
    assignment_id   TEXT,                    -- Photon shared-line assignment
    assigned_number TEXT,                    -- the shared line this tester texts
    peer_user_id    TEXT,                    -- Photon user id of the tester    } learned from their
    agent_user_id   TEXT,                    -- Photon user id of our line      } first inbound message;
    space_id        TEXT,                    -- the direct chat                 } needed to send
    last_inbound_at TEXT                     -- opt-in: a shared line may only reply after this is set
);
-- Small durable settings that survive reseeds (e.g. the Photon event cursor).
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

PHONE_FIELDS = ("handle", "role", "assignment_id", "assigned_number", "peer_user_id", "agent_user_id", "space_id", "last_inbound_at")

# Snapshot keys that live in `meta` (everything that isn't a row in its own table).
META_KEYS = ("version", "scenario_id", "t_s", "plan_version", "source", "synthetic", "hazard", "metrics")
# Derived from the engine on every refresh; replaced wholesale by apply_snapshot().
DERIVED_TABLES = ("closures", "households", "facilities", "resources")


def thread_key(thread: dict) -> str:
    """{'household_id': 492} → 'household:492'; {'facility_id': 'x'} → 'facility:x'."""
    if "household_id" in thread:
        return f"household:{int(thread['household_id'])}"
    if "facility_id" in thread:
        return f"facility:{thread['facility_id']}"
    raise ValueError(f"not a thread: {thread!r}")


def _dump(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Add columns that later versions introduced (CREATE TABLE IF NOT EXISTS won't)."""
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(plans)")}
        if "reports_used" not in cols:
            self._db.execute("ALTER TABLE plans ADD COLUMN reports_used TEXT NOT NULL DEFAULT '[]'")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---------- transactions ----------
    def _tx(self):
        store = self

        class _Tx:
            def __enter__(self_inner):
                store._lock.acquire()
                store._db.execute("BEGIN IMMEDIATE")
                return store._db

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    store._db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store._lock.release()
                return False

        return _Tx()

    def _rows(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # ---------- seeding ----------
    def is_empty(self) -> bool:
        return not self._rows("SELECT 1 FROM meta WHERE key = 'scenario_id'")

    def seed(self, state: dict) -> None:
        """Replace everything with a state snapshot (the fixture, or an engine snapshot). Phones are kept:
        they are tester registrations, not scenario state."""
        with self._tx() as db:
            for t in ("meta", "closures", "households", "facilities", "resources", "reports", "plans", "assignments", "messages"):
                db.execute(f"DELETE FROM {t}")
            db.execute("DELETE FROM sqlite_sequence WHERE name IN ('reports', 'messages')")
            for k in META_KEYS:
                if k in state:
                    db.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (k, _dump(state[k])))
            for i, c in enumerate(state["closures"]):
                db.execute("INSERT INTO closures VALUES (?, ?, ?, ?)", (c["edge_id"], i, c["source"], _dump(c)))
            for i, h in enumerate(state["households"]):
                db.execute("INSERT INTO households VALUES (?, ?, ?, ?)", (h["household_id"], i, h["status"], _dump(h)))
            for i, f in enumerate(state["facilities"]):
                db.execute("INSERT INTO facilities VALUES (?, ?, ?, ?)", (f["id"], i, f["state"], _dump(f)))
            for i, r in enumerate(state["resources"]):
                db.execute("INSERT INTO resources VALUES (?, ?, ?, ?)", (r["id"], i, r["status"], _dump(r)))
            for r in state["reports"]:
                self._insert_report(db, r)
            if state.get("plan"):
                self._insert_plan(db, state["plan"])
            for m in state["messages"]:
                self._insert_message(db, m, external_id=None)

    # ---------- writers (used by the loop in later tasks) ----------
    @staticmethod
    def _insert_report(db: sqlite3.Connection, r: dict) -> None:
        db.execute(
            "INSERT INTO reports (id, kind, household_id, facility_id, resolved, data) VALUES (?, ?, ?, ?, ?, ?)",
            (r["id"], r["kind"], r.get("household_id"), r.get("facility_id"), int(bool(r.get("resolved", False))), _dump(r)),
        )

    @staticmethod
    def _insert_plan(db: sqlite3.Connection, plan: dict, reports_used: list[str] | None = None) -> None:
        body = {k: v for k, v in plan.items() if k != "assignments"}
        db.execute("INSERT INTO plans (version, parent_version, data, reports_used) VALUES (?, ?, ?, ?)",
                   (plan["version"], plan.get("parent_version"), _dump(body), _dump(reports_used or [])))
        for i, a in enumerate(plan["assignments"]):
            db.execute("INSERT INTO assignments VALUES (?, ?, ?, ?, ?, ?)",
                       (plan["version"], a["id"], i, a["resource_id"], a["status"], _dump(a)))

    @staticmethod
    def _insert_message(db: sqlite3.Connection, m: dict, external_id: str | None, delivery: str | None = None) -> None:
        db.execute(
            "INSERT INTO messages (id, thread_key, direction, plan_version, external_id, delivery, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (m["id"], thread_key(m["thread"]), m["direction"], m.get("plan_version"), external_id, delivery, _dump(m)),
        )

    def clear_scenario(self) -> None:
        """Drop all scenario state (engine mode reseed). Phones and kv stay."""
        with self._tx() as db:
            for t in ("meta", "closures", "households", "facilities", "resources", "reports", "plans", "assignments", "messages"):
                db.execute(f"DELETE FROM {t}")
            db.execute("DELETE FROM sqlite_sequence WHERE name IN ('reports', 'messages')")

    def apply_snapshot(self, state: dict) -> None:
        """Replace the engine-derived part of the state (hazard, closures, households, facilities,
        resources, metrics, the plan as of t) with a simulator snapshot. Backend-owned rows (reports,
        messages, plan history, phones) are untouched."""
        with self._tx() as db:
            for k in ("version", "scenario_id", "t_s", "plan_version", "synthetic", "hazard", "metrics"):
                if k in state:
                    db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                               (k, _dump(state[k])))
            db.execute("INSERT INTO meta (key, value) VALUES ('plan_view', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                       (_dump(state.get("plan")),))
            for t in DERIVED_TABLES:
                db.execute(f"DELETE FROM {t}")
            for i, c in enumerate(state["closures"]):
                db.execute("INSERT INTO closures VALUES (?, ?, ?, ?)", (c["edge_id"], i, c["source"], _dump(c)))
            for i, h in enumerate(state["households"]):
                db.execute("INSERT INTO households VALUES (?, ?, ?, ?)", (h["household_id"], i, h["status"], _dump(h)))
            for i, f in enumerate(state["facilities"]):
                db.execute("INSERT INTO facilities VALUES (?, ?, ?, ?)", (f["id"], i, f["state"], _dump(f)))
            for i, r in enumerate(state["resources"]):
                db.execute("INSERT INTO resources VALUES (?, ?, ?, ?)", (r["id"], i, r["status"], _dump(r)))
            # scripted scenario reports the simulator applied so far (live ones are stored by add_report)
            db.execute("DELETE FROM meta WHERE key = 'scenario_reports'")
            db.execute("INSERT INTO meta (key, value) VALUES ('scenario_reports', ?)",
                       (_dump([r for r in state.get("reports", []) if r.get("source") == "scenario"]),))

    def add_plan(self, plan: dict, reports_used: list[str]) -> None:
        """Store an allocator plan version (raw: what the next replan gets as `prev`) and make it current."""
        with self._tx() as db:
            self._insert_plan(db, plan, reports_used)
            db.execute("INSERT INTO meta (key, value) VALUES ('plan_version', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                       (_dump(plan["version"]),))

    def plan_reports_used(self, version: int) -> list[str]:
        rows = self._rows("SELECT reports_used FROM plans WHERE version = ?", (version,))
        return json.loads(rows[0]["reports_used"]) if rows else []

    def add_report(self, r: dict) -> None:
        with self._tx() as db:
            self._insert_report(db, r)

    def mark_reports_resolved(self, ids: list[str]) -> None:
        with self._tx() as db:
            for rid in ids:
                row = db.execute("SELECT data FROM reports WHERE id = ?", (rid,)).fetchone()
                if row:
                    d = json.loads(row["data"]); d["resolved"] = True
                    db.execute("UPDATE reports SET resolved = 1, data = ? WHERE id = ?", (_dump(d), rid))

    def reports_by_id(self, ids: list[str]) -> list[dict]:
        by = {r["id"]: r for r in self.reports()}
        return [by[i] for i in ids if i in by]

    def reports(self) -> list[dict]:
        return self._objects("SELECT data FROM reports ORDER BY seq")

    def set_meta(self, key: str, value: Any) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                       (key, _dump(value)))

    def add_message(self, m: dict, external_id: str | None = None, delivery: str | None = None) -> bool:
        """Store one state.messages[] object. False (and nothing written) if `external_id` was already
        stored: Photon redelivers events after reconnects, and the poller can see the same message."""
        with self._tx() as db:
            if external_id and db.execute("SELECT 1 FROM messages WHERE external_id = ?", (external_id,)).fetchone():
                return False
            self._insert_message(db, m, external_id, delivery)
            return True

    def set_delivery(self, message_id: str, delivery: str, external_id: str | None = None) -> None:
        with self._tx() as db:
            db.execute("UPDATE messages SET delivery = ?, external_id = COALESCE(?, external_id) WHERE id = ?",
                       (delivery, external_id, message_id))

    def message_delivery(self, message_id: str) -> tuple[str | None, str | None]:
        rows = self._rows("SELECT delivery, external_id FROM messages WHERE id = ?", (message_id,))
        return (rows[0]["delivery"], rows[0]["external_id"]) if rows else (None, None)

    def has_external_id(self, external_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM messages WHERE external_id = ?", (external_id,)))

    def thread_messages(self, key: str) -> list[dict]:
        return [json.loads(r["data"]) for r in self._rows("SELECT data FROM messages WHERE thread_key = ? ORDER BY seq", (key,))]

    def last_outbound_plan_version(self, key: str) -> int | None:
        """The plan version of the last message we sent on a thread = what an inbound reply answers."""
        rows = self._rows("SELECT plan_version FROM messages WHERE thread_key = ? AND direction = 'out' ORDER BY seq DESC LIMIT 1", (key,))
        return rows[0]["plan_version"] if rows else None

    # ---------- phones + kv (survive reseeds) ----------
    def upsert_phone(self, handle: str, role: str, **fields: str | None) -> dict:
        bad = set(fields) - set(PHONE_FIELDS)
        if bad:
            raise ValueError(f"unknown phone fields {bad}")
        with self._tx() as db:
            # one phone per role: re-registering a role with a new number replaces the old one
            db.execute("DELETE FROM phones WHERE role = ? AND handle != ?", (role, handle))
            db.execute("INSERT INTO phones (handle, role) VALUES (?, ?) ON CONFLICT(handle) DO UPDATE SET role = excluded.role",
                       (handle, role))
            for k, v in fields.items():
                if v is not None:
                    db.execute(f"UPDATE phones SET {k} = ? WHERE handle = ?", (v, handle))
        return self.phone(handle=handle)  # type: ignore[return-value]

    def phone(self, *, handle: str | None = None, role: str | None = None) -> dict | None:
        col, val = ("handle", handle) if handle is not None else ("role", role)
        rows = self._rows(f"SELECT * FROM phones WHERE {col} = ?", (val,))
        return dict(rows[0]) if rows else None

    def phones(self) -> list[dict]:
        return [dict(r) for r in self._rows("SELECT * FROM phones ORDER BY role")]

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        rows = self._rows("SELECT value FROM kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def kv_set(self, key: str, value: str) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ---------- readers ----------
    def meta(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self._rows("SELECT key, value FROM meta")}

    def plan(self, version: int) -> dict | None:
        rows = self._rows("SELECT data FROM plans WHERE version = ?", (version,))
        if not rows:
            return None
        plan = json.loads(rows[0]["data"])
        plan["assignments"] = [json.loads(r["data"]) for r in self._rows(
            "SELECT data FROM assignments WHERE plan_version = ? ORDER BY ord", (version,))]
        return plan

    def plan_versions(self) -> list[int]:
        return [r["version"] for r in self._rows("SELECT version FROM plans ORDER BY version")]

    def current_plan(self) -> dict | None:
        """The current plan version as the allocator produced it (raw)."""
        v = self.meta().get("plan_version")
        return None if v is None else self.plan(v)

    def plan_view(self) -> dict | None:
        """The current plan as the state shows it (engine view with routes and as-of-t statuses)."""
        meta = self.meta()
        return meta["plan_view"] if "plan_view" in meta else self.current_plan()

    def _objects(self, sql: str) -> list[dict]:
        return [json.loads(r["data"]) for r in self._rows(sql)]

    def households(self) -> list[dict]:
        return self._objects("SELECT data FROM households ORDER BY ord")

    def facilities(self) -> list[dict]:
        return self._objects("SELECT data FROM facilities ORDER BY ord")

    def snapshot(self) -> dict:
        """The state contract (state.schema.json v0.1), assembled from the rows."""
        with self._lock:  # one consistent read across tables
            meta = self.meta()
            state: dict[str, Any] = {k: meta[k] for k in META_KEYS if k in meta}
            state["source"] = "backend"
            state["closures"] = self._objects("SELECT data FROM closures ORDER BY ord")
            state["households"] = self._objects("SELECT data FROM households ORDER BY ord")
            state["facilities"] = self._objects("SELECT data FROM facilities ORDER BY ord")
            state["resources"] = self._objects("SELECT data FROM resources ORDER BY ord")
            state["plan"] = meta["plan_view"] if "plan_view" in meta else self.current_plan()
            live = self._objects("SELECT data FROM reports ORDER BY seq")
            scripted = meta.get("scenario_reports", [])
            state["reports"] = sorted(scripted + live, key=lambda r: r["observed_at_t_s"]) if scripted else live
            state["messages"] = self._objects("SELECT data FROM messages ORDER BY seq")
        return state
