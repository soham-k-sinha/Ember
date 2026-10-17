"""Worker pools for robustness batches: Daytona sandboxes, or local processes as the fallback.

    pool = get_pool()                      # Daytona if DAYTONA_API_KEY is set (engine/.env), else local
    points = pool.run(batch_id, scenario, plans, reports, jobs, on_point=print)
    pool.close()

DaytonaPool (plan doc §6.5): N long-lived sandboxes from a snapshot that bakes in the engine package
and the shared town (named by a content hash, built once with `ember daytona-snapshot`); each loads
the town once in the stateful code_interpreter, then pulls jobs from a queue; results come back as
the run_code return value (Tier 1/2 sandboxes have no outbound network). Every call passes timeout=.
A job that fails twice is computed locally so a batch always completes. EMBER_LOCAL_POOL=1 forces
the local pool.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import hashlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .jobs import batch_setup, job_code, parse_last_json, run_job, worker_prelude

ENGINE_DIR = Path(__file__).resolve().parents[2]          # engine/
PKG_DIR = ENGINE_DIR / "ember_engine"
CANONICAL_TOWN = ENGINE_DIR / "data" / "town.json.gz"
SNAPSHOT_PREFIX = "ember-engine"
PREP_TIMEOUT_S, BATCH_TIMEOUT_S, JOB_TIMEOUT_S = 180, 60, 60


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

    def close(self):
        pass


# ---------- Daytona ----------
HOST_ONLY = {"cli.py", "api.py", "render_png.py", "build_town.py", "daytona/pool.py", "daytona/robust.py"}


def _config():
    from daytona import DaytonaConfig
    return DaytonaConfig(api_key=os.environ.get("DAYTONA_API_KEY"), api_url=os.environ.get("DAYTONA_API_URL") or None,
                         connection_pool_maxsize=None)


def snapshot_name() -> str:
    """Content hash of the code sandboxes run + the shared town: a change there → a new snapshot.
    Host-only modules (CLI, backend API, renderer, OSM builder, the pool itself) don't count."""
    h = hashlib.sha1()
    for f in sorted(PKG_DIR.rglob("*.py")):
        if f.relative_to(PKG_DIR).as_posix() in HOST_ONLY:
            continue
        h.update(f.relative_to(PKG_DIR).as_posix().encode()); h.update(f.read_bytes())
    h.update(CANONICAL_TOWN.read_bytes())
    return f"{SNAPSHOT_PREFIX}-{h.hexdigest()[:10]}"


async def ensure_snapshot(client, on_logs=print) -> str:
    """Build the snapshot if this content hash doesn't exist yet (takes a few minutes once)."""
    from daytona import CreateSnapshotParams, Image, Resources
    name = snapshot_name()
    with contextlib.suppress(Exception):
        await client.snapshot.get(name)
        return name
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

    # -- lifecycle --
    async def _open_client(self):
        from daytona import AsyncDaytona
        if self.api_key:
            os.environ.setdefault("DAYTONA_API_KEY", self.api_key)
        self.client = AsyncDaytona(_config())
        self.snapshot = await ensure_snapshot(self.client)

    async def _create_one(self, i: int):
        from daytona import CreateSandboxFromSnapshotParams, DaytonaRateLimitError
        for attempt in range(5):
            try:
                sb = await self.client.create(CreateSandboxFromSnapshotParams(snapshot=self.snapshot, auto_stop_interval=0, ttl_minutes=self.ttl,
                                                                              labels={"app": "ember", "role": "robustness"}), timeout=120)
                break
            except DaytonaRateLimitError:
                await asyncio.sleep(2 ** attempt)
        else:
            return None
        r = await sb.code_interpreter.run_code(worker_prelude(), timeout=PREP_TIMEOUT_S)
        if r.error:
            self.log.append(f"sandbox {i} prelude failed: {r.error.value}")
            await self.client.delete(sb, timeout=60)
            return None
        return sb

    async def astart(self):
        if self.sandboxes:
            return
        if self.client is None:
            await self._open_client()
        made = await asyncio.gather(*(self._create_one(i) for i in range(self.n)), return_exceptions=True)
        self.sandboxes = [s for s in made if s is not None and not isinstance(s, BaseException)]
        self.log += [f"sandbox create failed: {s!r}" for s in made if isinstance(s, BaseException)]
        if not self.sandboxes:
            raise RuntimeError("no Daytona sandbox came up: " + "; ".join(self.log[-3:]))

    async def aclose(self):
        if self.client is not None:
            await asyncio.gather(*(self.client.delete(s, timeout=60) for s in self.sandboxes), return_exceptions=True)
            with contextlib.suppress(Exception):
                await self.client.close()
        self.sandboxes, self.client = [], None

    # -- batches --
    async def arun(self, batch_id: str, scn: dict, plans: dict, reports: list, jobs: list, on_point=None) -> list[dict]:
        await self.astart()
        setup = batch_setup(batch_id, scn, plans, reports)
        ok = await asyncio.gather(*(s.code_interpreter.run_code(setup, timeout=BATCH_TIMEOUT_S) for s in self.sandboxes), return_exceptions=True)
        live = [s for s, r in zip(self.sandboxes, ok) if not isinstance(r, BaseException) and not r.error]
        q: asyncio.Queue = asyncio.Queue()
        for j in jobs:
            q.put_nowait((j, 0))
        out, failed = [], []

        async def worker(sb, wid: str):
            while True:
                try:
                    job, tries = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    r = await sb.code_interpreter.run_code(job_code(job, wid), timeout=self.job_timeout)
                    if r.error:
                        raise RuntimeError(f"{r.error.name}: {r.error.value}")
                    p = parse_last_json(r.stdout)
                    out.append(p)
                    if on_point:
                        on_point(p)
                except Exception as ex:   # noqa: BLE001 — retry once elsewhere, then compute locally
                    self.log.append(f"{job['run_id']} on {wid}: {ex!r}"[:300])
                    (q.put_nowait((job, tries + 1)) if tries == 0 else failed.append(job))

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

