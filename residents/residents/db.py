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
    data           TEXT NOT NULL             -- the plan object without `assignments`
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
    external_id  TEXT UNIQUE,                -- Photon message id (dedupes inbound)
    data         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages (thread_key, seq);
CREATE TABLE IF NOT EXISTS phones (
    handle          TEXT PRIMARY KEY,        -- E.164 phone number or email of the tester
    role            TEXT NOT NULL,           -- resident | operator
    thread_key      TEXT NOT NULL UNIQUE,
    assigned_number TEXT,                    -- Photon shared line the tester texts
    data            TEXT NOT NULL DEFAULT '{}'
);
"""

# Snapshot keys that live in `meta` (everything that isn't a row in its own table).
META_KEYS = ("version", "scenario_id", "t_s", "plan_version", "source", "synthetic", "hazard", "metrics")


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
    def _insert_plan(db: sqlite3.Connection, plan: dict) -> None:
        body = {k: v for k, v in plan.items() if k != "assignments"}
        db.execute("INSERT INTO plans (version, parent_version, data) VALUES (?, ?, ?)",
                   (plan["version"], plan.get("parent_version"), _dump(body)))
        for i, a in enumerate(plan["assignments"]):
            db.execute("INSERT INTO assignments VALUES (?, ?, ?, ?, ?, ?)",
                       (plan["version"], a["id"], i, a["resource_id"], a["status"], _dump(a)))

    @staticmethod
    def _insert_message(db: sqlite3.Connection, m: dict, external_id: str | None) -> None:
        db.execute(
            "INSERT INTO messages (id, thread_key, direction, plan_version, external_id, data) VALUES (?, ?, ?, ?, ?, ?)",
            (m["id"], thread_key(m["thread"]), m["direction"], m.get("plan_version"), external_id, _dump(m)),
        )

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
        v = self.meta().get("plan_version")
        return None if v is None else self.plan(v)

    def _objects(self, sql: str) -> list[dict]:
        return [json.loads(r["data"]) for r in self._rows(sql)]

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
            state["plan"] = self.current_plan()
            state["reports"] = self._objects("SELECT data FROM reports ORDER BY seq")
            state["messages"] = self._objects("SELECT data FROM messages ORDER BY seq")
        return state
