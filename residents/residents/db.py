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
import time
from pathlib import Path
from typing import Any

PHONE_SCHEMA = """
CREATE TABLE IF NOT EXISTS phones (
    handle TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    thread_key TEXT UNIQUE,
    scenario_id TEXT,
    assignment_id TEXT,
    assigned_number TEXT,
    peer_user_id TEXT,
    agent_user_id TEXT,
    space_id TEXT,
    last_inbound_at TEXT
);
"""


class PhoneConflict(ValueError):
    """Registration would replace another household's phone or move an existing phone."""


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
    created_wall REAL,                       -- wall-clock seconds (only for retry age; the sim uses t_s)
    data         TEXT NOT NULL               -- the state.messages[] object, verbatim
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages (thread_key, seq);
-- One phone per household/facility. Registrations and opt-in survive reseeds.
""" + PHONE_SCHEMA + """
-- Photon message ids already handled. Survives reseeds: after /dev/reset the messages table is empty,
-- and without this a redelivered or polled old text would be treated as new and answered again.
CREATE TABLE IF NOT EXISTS inbound_seen (
    external_id TEXT PRIMARY KEY,
    seen_wall   REAL NOT NULL
);
-- Small durable settings that survive reseeds (e.g. the Photon event cursor).
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

PHONE_FIELDS = ("handle", "role", "thread_key", "scenario_id", "assignment_id", "assigned_number",
                "peer_user_id", "agent_user_id", "space_id", "last_inbound_at")

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
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(messages)")}
        if "created_wall" not in cols:
            self._db.execute("ALTER TABLE messages ADD COLUMN created_wall REAL")
        if "recipient_handle" not in cols:
            self._db.execute("ALTER TABLE messages ADD COLUMN recipient_handle TEXT")
        if "said" not in cols:  # D76: the reply the person actually got for a turn ('' = merged into a later one)
            self._db.execute("ALTER TABLE messages ADD COLUMN said TEXT")
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(phones)")}
        if "thread_key" not in cols:
            # SQLite cannot drop the old UNIQUE(role) constraint in place. Keep every
            # registration and its Photon opt-in credentials in one atomic migration.
            with self._tx() as db:
                db.execute("ALTER TABLE phones RENAME TO phones_legacy")
                db.execute(PHONE_SCHEMA)
                old_fields = ", ".join(k for k in PHONE_FIELDS if k in cols)
                db.execute(f"INSERT INTO phones ({old_fields}) SELECT {old_fields} FROM phones_legacy")
                db.execute("DROP TABLE phones_legacy")

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
            "INSERT INTO messages (id, thread_key, direction, plan_version, external_id, delivery, created_wall, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (m["id"], thread_key(m["thread"]), m["direction"], m.get("plan_version"), external_id, delivery, time.time(), _dump(m)),
        )

    def clear_scenario(self) -> None:
        """Drop all scenario state (engine mode reseed). Phones and kv stay, except: a phone that was
        placed by texting its location goes back to waiting for a location (its household was part of
        the run), and the households added that way are dropped (kv `extra_households`)."""
        with self._tx() as db:
            for t in ("meta", "closures", "households", "facilities", "resources", "reports", "plans", "assignments", "messages"):
                db.execute(f"DELETE FROM {t}")
            db.execute("DELETE FROM sqlite_sequence WHERE name IN ('reports', 'messages')")
            located = [r["key"][len("located:"):] for r in db.execute("SELECT key FROM kv WHERE key LIKE 'located:%'")]
            for handle in located:
                db.execute("UPDATE phones SET thread_key = NULL WHERE handle = ?", (handle,))
            db.execute("DELETE FROM kv WHERE key = 'extra_households'")
            # per-run conversation memory: half-answered questions, last instruction texted, questions asked,
            # step-by-step directions, where located phones were placed, pre-placement chat, when we last called
            for prefix in ("pending:", "instr:", "asked:", "rejected:", "guide:", "located:", "lobby:", "welcomed:", "keep:",
                           "question:", "call:"):
                db.execute("DELETE FROM kv WHERE key LIKE ?", (prefix + "%",))

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

    def set_assignment_status(self, version: int, assignment_id: str, status: str, only_from: tuple[str, ...]) -> bool:
        """Backend-owned status bookkeeping (offered / confirmed / rejected) on the raw plan, which the next
        replan reads as `prev` (the allocator keeps `confirmed` work), and on the state's view. Only moves
        from `only_from`; False if the assignment isn't there or is already past that."""
        with self._tx() as db:
            row = db.execute("SELECT data FROM assignments WHERE plan_version = ? AND id = ?", (version, assignment_id)).fetchone()
            if not row:
                return False
            a = json.loads(row["data"])
            if a.get("status", "proposed") not in only_from:
                return False
            a["status"] = status
            db.execute("UPDATE assignments SET status = ?, data = ? WHERE plan_version = ? AND id = ?",
                       (status, _dump(a), version, assignment_id))
            row = db.execute("SELECT value FROM meta WHERE key = 'plan_view'").fetchone()
            if row:
                view = json.loads(row["value"])
                if view and view.get("version") == version:
                    for x in view["assignments"]:
                        if x["id"] == assignment_id and x["status"] in only_from:
                            x["status"] = status
                    db.execute("UPDATE meta SET value = ? WHERE key = 'plan_view'", (_dump(view),))
            return True

    def mark_offered(self, version: int, assignment_id: str) -> bool:
        """proposed → offered once the instruction is texted."""
        return self.set_assignment_status(version, assignment_id, "offered", ("proposed",))

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

    def add_message(self, m: dict, external_id: str | None = None, delivery: str | None = None,
                    recipient_handle: str | None = None) -> bool:
        """Store one state.messages[] object. False (and nothing written) if `external_id` was already
        stored: Photon redelivers events after reconnects, and the poller can see the same message."""
        with self._tx() as db:
            if external_id and db.execute("SELECT 1 FROM messages WHERE external_id = ?", (external_id,)).fetchone():
                return False
            self._insert_message(db, m, external_id, delivery)
            if recipient_handle:
                db.execute("UPDATE messages SET recipient_handle = ? WHERE id = ?", (recipient_handle, m["id"]))
            return True

    def set_delivery(self, message_id: str, delivery: str, external_id: str | None = None) -> None:
        with self._tx() as db:
            db.execute("UPDATE messages SET delivery = ?, external_id = COALESCE(?, external_id) WHERE id = ?",
                       (delivery, external_id, message_id))

    def message_delivery(self, message_id: str) -> tuple[str | None, str | None]:
        rows = self._rows("SELECT delivery, external_id FROM messages WHERE id = ?", (message_id,))
        return (rows[0]["delivery"], rows[0]["external_id"]) if rows else (None, None)

    def failed_outbound(self, max_age_s: float) -> list[dict]:
        """Outbound messages whose delivery failed within the last `max_age_s` wall seconds, oldest first
        (an instruction from long ago is no longer worth sending)."""
        rows = self._rows("SELECT data, recipient_handle FROM messages WHERE direction = 'out' AND delivery = 'failed' "
                          "AND created_wall >= ? ORDER BY seq", (time.time() - max_age_s,))
        return [{**json.loads(r["data"]), "recipient_handle": r["recipient_handle"]} for r in rows]

    def inbound_seen(self, external_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM inbound_seen WHERE external_id = ?", (external_id,)))

    def mark_inbound_seen(self, external_id: str) -> None:
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO inbound_seen (external_id, seen_wall) VALUES (?, ?)", (external_id, time.time()))

    def has_external_id(self, external_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM messages WHERE external_id = ?", (external_id,)))

    def thread_messages(self, key: str) -> list[dict]:
        return [json.loads(r["data"]) for r in self._rows("SELECT data FROM messages WHERE thread_key = ? ORDER BY seq", (key,))]

    def last_outbound_plan_version(self, key: str) -> int | None:
        """The plan version of the last message we sent on a thread = what an inbound reply answers."""
        rows = self._rows("SELECT plan_version FROM messages WHERE thread_key = ? AND direction = 'out' "
                          "AND delivery IN ('sent', 'dev') ORDER BY seq DESC LIMIT 1", (key,))
        return rows[0]["plan_version"] if rows else None

    def set_said(self, message_ids: list[str], text: str) -> None:
        """One turn's computed messages went out as one reply `text` (D76): it's stored on the last of them; the
        others are marked as merged ('') so the conversation shows what the person actually got, once."""
        with self._tx() as db:
            for i, mid in enumerate(message_ids):
                db.execute("UPDATE messages SET said = ? WHERE id = ?", (text if i == len(message_ids) - 1 else "", mid))

    def conversation(self, key: str, n: int = 8) -> list[dict]:
        """The last `n` turns as the person experienced them: [{"from": "them" | "EMBER", "text"}], oldest first."""
        out = []
        for r in self._rows("SELECT data, direction, said, delivery FROM messages WHERE thread_key = ? ORDER BY seq", (key,)):
            m = json.loads(r["data"])
            if r["direction"] == "in":
                out.append({"from": "them", "text": m["text"]})
            elif r["delivery"] in ("sent", "dev", "failed"):
                text = r["said"] if r["said"] is not None else m["text"]
                if text:
                    out.append({"from": "EMBER", "text": text.removeprefix("[EMBER drill] ")})
        return out[-n:]

    def delivered_outbound(self, key: str) -> list[dict]:
        return [json.loads(r["data"]) for r in self._rows(
            "SELECT data FROM messages WHERE thread_key = ? AND direction = 'out' "
            "AND delivery IN ('sent', 'dev') ORDER BY seq", (key,))]

    # ---------- phones + kv (survive reseeds) ----------
    def clear_phone_opt_in(self, handle: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE phones SET peer_user_id = NULL, agent_user_id = NULL, space_id = NULL, "
                       "last_inbound_at = NULL WHERE handle = ?", (handle,))

    def upsert_phone(self, handle: str, role: str, **fields: str | None) -> dict:
        bad = set(fields) - set(PHONE_FIELDS)
        if bad:
            raise ValueError(f"unknown phone fields {bad}")
        with self._tx() as db:
            key = fields.get("thread_key")
            previous = db.execute("SELECT * FROM phones WHERE handle = ?", (handle,)).fetchone()
            if previous and (previous["role"] != role or (key and previous["thread_key"] not in (None, key))):
                raise PhoneConflict("This phone is already registered to a different household/facility.")
            if key and db.execute("SELECT 1 FROM phones WHERE thread_key = ? AND handle != ?", (key, handle)).fetchone():
                raise PhoneConflict(f"{key} already has a registered phone. Choose a different household/facility ID.")
            db.execute("INSERT INTO phones (handle, role) VALUES (?, ?) ON CONFLICT(handle) DO UPDATE SET role = excluded.role",
                       (handle, role))
            for k, v in fields.items():
                if v is not None:
                    db.execute(f"UPDATE phones SET {k} = ? WHERE handle = ?", (v, handle))
        return self.phone(handle=handle)  # type: ignore[return-value]

    def phone(self, *, handle: str | None = None, role: str | None = None, key: str | None = None) -> dict | None:
        col, val = ("handle", handle) if handle is not None else (("thread_key", key) if key is not None else ("role", role))
        rows = self._rows(f"SELECT * FROM phones WHERE {col} = ?", (val,))
        if len(rows) > 1:
            raise ValueError("Several phones have this role; specify a household_id or facility_id.")
        return dict(rows[0]) if rows else None

    def phones(self) -> list[dict]:
        return [dict(r) for r in self._rows("SELECT * FROM phones ORDER BY role, thread_key, handle")]

    def rebind_phone(self, handle: str, role: str, thread_key: str | None, scenario_id: str | None) -> None:
        """Give a known phone a new role/target, keeping its Photon line and opt-in (the drill's command
        line decides who plays what in a fresh run). Raises PhoneConflict if the target has another phone."""
        with self._tx() as db:
            if thread_key and db.execute("SELECT 1 FROM phones WHERE thread_key = ? AND handle != ?", (thread_key, handle)).fetchone():
                raise PhoneConflict(f"{thread_key} already has another phone in this run.")
            db.execute("UPDATE phones SET role = ?, thread_key = ?, scenario_id = ? WHERE handle = ?",
                       (role, thread_key, scenario_id, handle))

    def delete_phone(self, handle: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM phones WHERE handle = ?", (handle,))
            db.execute("DELETE FROM kv WHERE key IN (?, ?, ?) OR key LIKE ?",
                       (f"located:{handle}", f"player:{handle}", f"joined:{handle}", f"lobby:{handle}%"))

    def unplace_phone(self, handle: str) -> None:
        """Back to waiting for a location (thread_key NULL, scenario kept so it isn't legacy-bound)."""
        with self._tx() as db:
            db.execute("UPDATE phones SET thread_key = NULL WHERE handle = ?", (handle,))

    def kv_prefix(self, prefix: str) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._rows("SELECT key, value FROM kv WHERE key LIKE ? ORDER BY key", (prefix + "%",))}

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        rows = self._rows("SELECT value FROM kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def kv_delete(self, key: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM kv WHERE key = ?", (key,))

    def set_message_report(self, message_id: str, report_id: str) -> None:
        """Link an inbound message to the report extracted from it (state.messages[].report_id)."""
        with self._tx() as db:
            row = db.execute("SELECT data FROM messages WHERE id = ?", (message_id,)).fetchone()
            if row:
                d = json.loads(row["data"]); d["report_id"] = report_id
                db.execute("UPDATE messages SET data = ? WHERE id = ?", (_dump(d), message_id))

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
