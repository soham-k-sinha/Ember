"""Worker pools for robustness batches: Daytona sandboxes, or local processes as the fallback.

    pool = get_pool()                      # Daytona if DAYTONA_API_KEY is set (engine/.env), else local
    points = pool.run(batch_id, scenario, plans, reports, jobs, on_point=print)
    pool.close()

DaytonaPool (plan doc §6.5): N long-lived sandboxes from a snapshot that bakes in the engine package
and the shared town (named by a content hash, built once with `ember daytona-snapshot`); each loads
the town once in the stateful code_interpreter, then pulls chunks of about jobs ÷ N jobs from a queue
(one round trip per chunk, not per job); results come back as the run_code return value (Tier 1/2
sandboxes have no outbound network). Every call passes timeout=. A chunk that fails twice is computed
locally so a batch always completes. The backend keeps one pool warm across batches; a start first
deletes this app's sandboxes idle for ORPHAN_IDLE_MIN (left by a crash, they would hold the vCPU
quota for their TTL). EMBER_LOCAL_POOL=1 forces the local pool.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import hashlib
import json
import logging
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .jobs import batch_setup, job_code, parse_points, run_job, worker_prelude

ENGINE_DIR = Path(__file__).resolve().parents[2]          # engine/
PKG_DIR = ENGINE_DIR / "ember_engine"
CANONICAL_TOWN = ENGINE_DIR / "data" / "town.json.gz"
SNAPSHOT_PREFIX = "ember-engine"
PREP_TIMEOUT_S, BATCH_TIMEOUT_S, JOB_TIMEOUT_S = 180, 60, 60
LABELS = {"app": "ember", "role": "robustness"}
ORPHAN_IDLE_MIN = 3
log = logging.getLogger(__name__)


def load_env(path: Path = ENGINE_DIR / ".env") -> None:
    """KEY=VALUE lines from engine/.env into os.environ (existing variables win). No dependency."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_world(town_path: str | None = None):
    from ..world import World
    raw = Path(town_path or CANONICAL_TOWN).read_bytes()
    return World.from_dict(json.loads(gzip.decompress(raw) if str(town_path or CANONICAL_TOWN).endswith(".gz") else raw))


# ---------- local ----------
_LOCAL: dict = {}


def _local_init(town_path, scn, plans, reports):
    _LOCAL.update(world=_load_world(town_path), scn=scn, plans=plans, reports=reports)


def _local_job(job):
    return run_job(_LOCAL["world"], _LOCAL["scn"], _LOCAL["plans"], _LOCAL["reports"], job, worker=f"local-{os.getpid()}")


class LocalPool:
    kind = "local"
    startup_s = 0.0

    def __init__(self, workers: int | None = None, town_path: str | None = None, world=None):
        self.workers = max(1, workers if workers is not None else min(8, (os.cpu_count() or 2) - 1))
        self.town_path, self.world = town_path, world

    def run(self, batch_id: str, scn: dict, plans: dict, reports: list, jobs: list, on_point=None) -> list[dict]:
        out = []
        if self.workers == 1:   # in-process (tests, tiny batches)
            world = self.world or _load_world(self.town_path)
            for j in jobs:
                p = run_job(world, scn, plans, reports, j, worker="local-0")
                out.append(p)
                if on_point:
                    on_point(p)
            return out
        with ProcessPoolExecutor(self.workers, initializer=_local_init, initargs=(self.town_path, scn, plans, reports)) as ex:
            for f in as_completed([ex.submit(_local_job, j) for j in jobs]):
                p = f.result()
                out.append(p)
                if on_point:
                    on_point(p)
        return out

    def start(self):
        pass

    def close(self):
        pass


# ---------- Daytona ----------
def _config():
    from daytona import DaytonaConfig
    return DaytonaConfig(api_key=os.environ.get("DAYTONA_API_KEY"), api_url=os.environ.get("DAYTONA_API_URL") or None,
                         connection_pool_maxsize=None)


_CLOSURE_PROBE = (
    "import sys, json, ember_engine.world, ember_engine.daytona.jobs, ember_engine.allocator.search, ember_engine.sim\n"
    "print(json.dumps(sorted(m.__file__ for n, m in sys.modules.items() if n.startswith('ember_engine') and getattr(m, '__file__', None))))"
)
_HASH_CACHE: dict = {}


def sandbox_modules() -> list[Path]:
    """The engine files a sandbox job actually imports (measured in a fresh interpreter, so host-side
    imports don't leak in). Editing anything else (CLI, backend API, rationale text) keeps the snapshot."""
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-c", _CLOSURE_PROBE], cwd=str(ENGINE_DIR), capture_output=True, text=True, timeout=60,
                         env={**os.environ, "PYTHONPATH": str(ENGINE_DIR)}, check=True).stdout
    return [Path(f) for f in json.loads(out.strip().splitlines()[-1])]


def snapshot_name() -> str:
    """Content hash of the code sandboxes run + the shared town: a change there → a new snapshot."""
    key = "name"
    if key not in _HASH_CACHE:
        h = hashlib.sha1()
        for f in sorted(sandbox_modules()):
            h.update(f.resolve().relative_to(PKG_DIR.resolve()).as_posix().encode()); h.update(f.read_bytes())
        h.update(CANONICAL_TOWN.read_bytes())
        _HASH_CACHE[key] = f"{SNAPSHOT_PREFIX}-{h.hexdigest()[:10]}"
    return _HASH_CACHE[key]


class SnapshotMissing(RuntimeError):
    pass


async def ensure_snapshot(client, on_logs=print, build: bool = True) -> str:
    """The snapshot for the current sandbox code. build=False: raise SnapshotMissing instead of building
    (a build takes minutes; never let one start implicitly in the middle of a demo)."""
    from daytona import CreateSnapshotParams, Image, Resources
    name = snapshot_name()
    with contextlib.suppress(Exception):
        await client.snapshot.get(name)
        return name
    if not build:
        raise SnapshotMissing(f"Daytona snapshot {name} is not built for the current engine code; "
                              "run `uv run --project engine ember daytona-snapshot` (≈1–2 min). Using local processes meanwhile.")
    image = (Image.debian_slim("3.12").pip_install("numpy>=1.26", "scipy>=1.12", "shapely>=2.0")
             .add_local_dir(PKG_DIR, "/home/daytona/engine/ember_engine")
             .add_local_file(CANONICAL_TOWN, "/home/daytona/town.json.gz")
             .workdir("/home/daytona"))
    await client.snapshot.create(CreateSnapshotParams(name=name, image=image, resources=Resources(cpu=1, memory=1, disk=3)),
                                 on_logs=on_logs, timeout=1800)
    return name


class DaytonaPool:
    """N long-lived sandboxes. Use run() from sync code, or arun() from an event loop (the backend)."""
    kind = "daytona"

    def __init__(self, workers: int = 10, api_key: str | None = None, ttl_minutes: int = 360, job_timeout: int = JOB_TIMEOUT_S,
                 local_fallback_world=None):
        self.n, self.api_key, self.ttl, self.job_timeout = workers, api_key, ttl_minutes, job_timeout
        self.client, self.sandboxes, self.snapshot = None, [], None
        self._fallback_world = local_fallback_world
        self._loop = None
        self.log = []
        self.fell_back = False
        self.startup_s = 0.0

    @property
    def workers(self) -> int:
        return len(self.sandboxes)

    # -- lifecycle --
    async def _open_client(self):
        from daytona import AsyncDaytona
        if self.api_key:
            os.environ.setdefault("DAYTONA_API_KEY", self.api_key)
        self.client = AsyncDaytona(_config())
        self.snapshot = await ensure_snapshot(self.client, build=os.environ.get("EMBER_DAYTONA_BUILD") == "1")

    async def _create_one(self, i: int):
        from daytona import CreateSandboxFromSnapshotParams, DaytonaRateLimitError
        for attempt in range(5):
            try:
                sb = await self.client.create(CreateSandboxFromSnapshotParams(snapshot=self.snapshot, auto_stop_interval=0, ttl_minutes=self.ttl,
                                                                              labels=LABELS), timeout=120)
                break
            except DaytonaRateLimitError:
                await asyncio.sleep(2 ** attempt)
        else:
            self.log.append(f"sandbox {i} not created: rate-limited 5 times")
            return None
        r = await sb.code_interpreter.run_code(worker_prelude(), timeout=PREP_TIMEOUT_S)
        if r.error:
            self.log.append(f"sandbox {i} prelude failed: {r.error.value}")
            await self.client.delete(sb, timeout=60)
            return None
        return sb

    async def _delete_orphans(self):
        from daytona import ListSandboxesQuery
        idle = datetime.now(UTC) - timedelta(minutes=ORPHAN_IDLE_MIN)
        old = [s async for s in self.client.list(ListSandboxesQuery(labels=LABELS, last_activity_before=idle))]
        if old:
            await asyncio.gather(*(self.client.delete(s, timeout=60) for s in old), return_exceptions=True)
            self.log.append(f"deleted {len(old)} orphaned sandboxes")

    async def astart(self):
        if self.sandboxes:
            return
        t0 = time.time()
        if self.client is None:
            await self._open_client()
        await self._delete_orphans()
        made = await asyncio.gather(*(self._create_one(i) for i in range(self.n)), return_exceptions=True)
        self.sandboxes = [s for s in made if s is not None and not isinstance(s, BaseException)]
        self.log += [f"sandbox create failed: {s!r}" for s in made if isinstance(s, BaseException)]
        self.startup_s += time.time() - t0
        if len(self.sandboxes) < self.n:
            log.warning("Daytona: %d of %d sandboxes came up: %s", len(self.sandboxes), self.n, "; ".join(self.log[-3:]))
        if not self.sandboxes:
            raise RuntimeError("no Daytona sandbox came up: " + "; ".join(self.log[-3:]))

    async def _setup(self, code: str) -> None:
        """Register the batch on every sandbox; dead ones (past their TTL, deleted elsewhere) are deleted and dropped."""
        ok = await asyncio.gather(*(s.code_interpreter.run_code(code, timeout=BATCH_TIMEOUT_S) for s in self.sandboxes), return_exceptions=True)
        up = [not isinstance(r, BaseException) and not r.error for r in ok]
        if not all(up):
            self.log.append(f"dropped {up.count(False)} of {len(up)} sandboxes that failed the batch setup")
            await asyncio.gather(*(self.client.delete(s, timeout=60) for s, u in zip(self.sandboxes, up) if not u), return_exceptions=True)
            self.sandboxes = [s for s, u in zip(self.sandboxes, up) if u]

    async def aclose(self):
        if self.client is not None:
            await asyncio.gather(*(self.client.delete(s, timeout=60) for s in self.sandboxes), return_exceptions=True)
            with contextlib.suppress(Exception):
                await self.client.close()
        self.sandboxes, self.client = [], None

    # -- batches --
    async def arun(self, batch_id: str, scn: dict, plans: dict, reports: list, jobs: list, on_point=None) -> list[dict]:
        self.log, self.fell_back, self.startup_s = [], False, 0.0
        setup = batch_setup(batch_id, scn, plans, reports)
        try:
            await self.astart()
            await self._setup(setup)
            if not self.sandboxes:   # the warm pool is gone (TTL, or deleted as orphans by another process): start afresh
                await self.astart()
                await self._setup(setup)
        except Exception as ex:   # noqa: BLE001 — no snapshot / no sandbox: the batch still completes locally
            self.log.append(f"Daytona unavailable, running locally: {ex}"[:400])
            self.fell_back = True
            world = self._fallback_world or _load_world()
            out = []
            for j in jobs:
                p = run_job(world, scn, plans, reports, j, worker="local-fallback")
                out.append(p)
                if on_point:
                    on_point(p)
            return out
        live = self.sandboxes
        size = math.ceil(len(jobs) / max(1, len(live)))
        q: asyncio.Queue = asyncio.Queue()
        for i in range(0, len(jobs), size):
            q.put_nowait((jobs[i:i + size], 0))
        out, failed = [], []

        async def worker(sb, wid: str):
            while True:
                try:
                    chunk, tries = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    r = await sb.code_interpreter.run_code(job_code(chunk, wid), timeout=self.job_timeout * len(chunk))
                    if r.error:
                        raise RuntimeError(f"{r.error.name}: {r.error.value}")
                    for p in parse_points(r.stdout, len(chunk)):
                        out.append(p)
                        if on_point:
                            on_point(p)
                except Exception as ex:   # noqa: BLE001 — retry once elsewhere, then compute locally
                    self.log.append(f"{chunk[0]['run_id']} (+{len(chunk) - 1}) on {wid}: {ex!r}"[:300])
                    (q.put_nowait((chunk, tries + 1)) if tries == 0 else failed.extend(chunk))

        await asyncio.gather(*(worker(s, getattr(s, "id", f"sb{i}")) for i, s in enumerate(live)))
        if failed or not live:   # guarantee completeness
            rest = failed if live else jobs
            world = self._fallback_world or _load_world()
            for j in rest:
                p = run_job(world, scn, plans, reports, j, worker="local-fallback")
                out.append(p)
                if on_point:
                    on_point(p)
        return out

    def _sync(self, coro):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    def start(self):
        self._sync(self.astart())

    def run(self, *a, **k):
        return self._sync(self.arun(*a, **k))

    def close(self):
        if self._loop is not None:
            self._sync(self.aclose())
            self._loop.close()
            self._loop = None


def get_pool(kind: str = "auto", workers: int | None = None, world=None):
    """auto: Daytona when DAYTONA_API_KEY is set and EMBER_LOCAL_POOL != 1, else local processes."""
    load_env()
    want_local = kind == "local" or (kind == "auto" and (os.environ.get("EMBER_LOCAL_POOL") == "1" or not os.environ.get("DAYTONA_API_KEY")))
    if want_local:
        return LocalPool(workers, world=world)
    return DaytonaPool(workers or int(os.environ.get("EMBER_DAYTONA_WORKERS", "10")), local_fallback_world=world)


def build_snapshot() -> str:
    """CLI helper: make sure the snapshot for the current engine + town exists."""
    load_env()
    if not os.environ.get("DAYTONA_API_KEY"):
        raise SystemExit("DAYTONA_API_KEY is not set. Put `DAYTONA_API_KEY=...` in engine/.env (gitignored) — "
                         "app.daytona.io → API Keys. Tier 2 (card + $25) gives ~100 concurrent sandboxes.")

    async def go():
        from daytona import AsyncDaytona
        client = AsyncDaytona(_config())
        try:
            return await ensure_snapshot(client)
        finally:
            with contextlib.suppress(Exception):
                await client.close()
    t0 = time.time()
    name = asyncio.run(go())
    print(f"[daytona] snapshot {name} ready ({time.time() - t0:.0f}s)")
    return name

