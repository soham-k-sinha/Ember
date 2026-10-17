"""Robustness fan-out: jobs, pools (local, and a stand-in Daytona sandbox running the exact remote code), selection."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ember_engine.daytona import jobs as J
from ember_engine.daytona.pool import CANONICAL_TOWN, PKG_DIR, DaytonaPool, LocalPool, get_pool
from ember_engine.daytona.robust import robust_plan, robust_rank, worst_mean
from ember_engine.state import validate_state
from ember_engine.world import World

FX = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
CONTRACTS = FX.parent


@pytest.fixture(scope="module")
def town() -> dict:
    return json.loads((FX / "town.fixture.json").read_text())


@pytest.fixture(scope="module")
def world(town) -> World:
    return World.from_dict(town)


@pytest.fixture(scope="module")
def scn() -> dict:
    return json.loads((FX / "scenario.fixture.json").read_text())


def test_perturbations_are_deterministic_and_paired(scn, world):
    assert J.sample_perturbation(0, scn, world.n_edges) == {}
    a, b = J.sample_perturbation(3, scn, world.n_edges), J.sample_perturbation(3, scn, world.n_edges)
    assert a == b and set(J.RANGES) <= set(a)
    jobs = J.make_jobs("v1", ["c00", "baseline"], [1, 2], scn, world.n_edges)
    assert len(jobs) == 4 and len({j["run_id"] for j in jobs}) == 4
    by_seed = {}
    for j in jobs:
        by_seed.setdefault(j["seed"], []).append(j["perturbation"])
    assert all(p[0] == p[1] for p in by_seed.values())          # same seed = same world for every candidate


def test_worst_share_and_ranking():
    assert worst_mean([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) == 8.5
    pts = [{"candidate": c, "metrics": {"people_unreached": u, "overflow_m3": 0.0}} for c, us in
           (("a", [0, 0, 0, 0, 20]), ("b", [3, 3, 3, 3, 3]), ("baseline", [0] * 5)) for u in us]
    rank = robust_rank(pts)
    assert rank[0]["candidate"] == "b"                            # a has the better mean but the worse tail
    assert rank[-1]["candidate"] == "baseline" and not rank[-1]["eligible"]


def test_hundred_jobs_complete_and_pick_a_plan(world, scn, town):
    streamed = []
    plan, pts = robust_plan(world, scn, k=4, seeds=20, pool=LocalPool(1, world=world), on_point=streamed.append)
    assert len(pts) == 100 and len(streamed) == 100                # 4 candidates + baseline × 20 seeds
    r = plan["search"]["robust"]
    assert r["jobs"] == 100 and r["chosen"] in {c for c in r["candidates"] if c != "baseline"}
    assert r["ranking"][0]["candidate"] == r["chosen"]
    st = __import__("ember_engine.sim", fromlist=["simulate"]).simulate(world, scn, plan).state_at(3600)
    assert validate_state(st, scn, town) == []


def test_scatter_points_match_the_ws_contract(world, scn):
    js = pytest.importorskip("jsonschema")
    from referencing import Registry, Resource
    reg = Registry()
    for p in CONTRACTS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        reg = reg.with_resource(s["$id"], Resource.from_contents(s))
    ws = json.loads((CONTRACTS / "ws-events.schema.json").read_text())
    v = js.Draft202012Validator(ws, registry=reg)
    _, pts = robust_plan(world, scn, k=1, seeds=2, pool=LocalPool(1, world=world))
    for i, p in enumerate(pts):
        assert not list(v.iter_errors({"type": "scatter_point", "seq": i, "t_s": 0.0, "data": p}))


def test_process_pool_matches_in_process(world, scn):
    plans = {"c": {"assignments": []}}
    jobs = J.make_jobs("t", ["c"], [1, 2, 3], scn, world.n_edges)
    one = LocalPool(1, world=world).run("t", scn, plans, [], jobs)
    many = LocalPool(2, town_path=str(FX / "town.fixture.json")).run("t", scn, plans, [], jobs)
    key = lambda ps: sorted((p["run_id"], json.dumps(p["metrics"], sort_keys=True)) for p in ps)  # noqa: E731
    assert key(one) == key(many)


# ---------- Daytona path with stand-in sandboxes that exec the exact remote code ----------
class FakeInterpreter:
    def __init__(self, fail_first: int = 0):
        self.g, self.fail_first, self.calls = {}, fail_first, 0

    async def run_code(self, code, timeout=None):
        assert timeout is not None, "every Daytona call must pass timeout="
        self.calls += 1
        if "_ember_run_job" in code and "print(json.dumps(_ember_run_job" in code and self.fail_first > 0:
            self.fail_first -= 1
            return SimpleNamespace(stdout="", stderr="", error=SimpleNamespace(name="RuntimeError", value="boom", traceback=""))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, self.g)
        except Exception as ex:   # noqa: BLE001
            return SimpleNamespace(stdout=buf.getvalue(), stderr="", error=SimpleNamespace(name=type(ex).__name__, value=str(ex), traceback=""))
        return SimpleNamespace(stdout=buf.getvalue(), stderr="", error=None)


class FakeDaytonaPool(DaytonaPool):
    def __init__(self, n, fail_first=(0,), **k):
        super().__init__(n, **k)
        self._fails = list(fail_first) + [0] * n

    async def astart(self):
        if self.sandboxes:
            return
        for i in range(self.n):
            sb = SimpleNamespace(id=f"fake-{i}", code_interpreter=FakeInterpreter(self._fails[i]))
            r = await sb.code_interpreter.run_code(J.worker_prelude(str(PKG_DIR.parent), str(CANONICAL_TOWN)), timeout=180)
            assert r.error is None, r.error
            self.sandboxes.append(sb)

    async def aclose(self):
        self.sandboxes = []


def test_daytona_wire_protocol_with_retry(world, scn):
    plans = {"c00": {"assignments": []}, "baseline": {"assignments": []}}
    jobs = J.make_jobs("v9", list(plans), [1, 2, 3], scn, world.n_edges)
    pool = FakeDaytonaPool(2, fail_first=(1, 0), local_fallback_world=world)
    try:
        town_scn = dict(scn)
        pts = asyncio.run(pool.arun("v9", town_scn, plans, [], jobs))
    finally:
        asyncio.run(pool.aclose())
    assert sorted(p["run_id"] for p in pts) == sorted(j["run_id"] for j in jobs)
    assert {p["worker"] for p in pts} <= {"fake-0", "fake-1"}
    assert any("boom" in line for line in pool.log)              # the failed job was retried elsewhere


def test_get_pool_falls_back_to_local(monkeypatch):
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.setattr("ember_engine.daytona.pool.load_env", lambda *a, **k: None)
    assert get_pool().kind == "local"
    monkeypatch.setenv("DAYTONA_API_KEY", "x")
    monkeypatch.setenv("EMBER_LOCAL_POOL", "1")
    assert get_pool().kind == "local"


def test_missing_snapshot_falls_back_to_local_instead_of_building(world, scn):
    """A changed engine means a new snapshot name; until `ember daytona-snapshot` runs, batches complete locally
    (never an implicit multi-minute build in the middle of a demo)."""
    class NoSnapshotPool(DaytonaPool):
        async def astart(self):
            from ember_engine.daytona.pool import SnapshotMissing
            raise SnapshotMissing("snapshot ember-engine-test is not built")
    plans = {"c00": {"assignments": []}}
    jobs = J.make_jobs("v1", ["c00"], [1, 2], scn, world.n_edges)
    pool = NoSnapshotPool(2, local_fallback_world=world)
    pts = asyncio.run(pool.arun("v1", scn, plans, [], jobs))
    assert len(pts) == 2 and {p["worker"] for p in pts} == {"local-fallback"}
    assert pool.fell_back and "not built" in pool.log[0]


def test_snapshot_hash_ignores_host_only_modules():
    from ember_engine.daytona.pool import PKG_DIR, sandbox_modules
    mods = {str(m.resolve().relative_to(PKG_DIR.resolve())) for m in sandbox_modules()}
    assert {"world.py", "sim/plan_sim.py", "daytona/jobs.py", "allocator/search.py"} <= mods
    assert not mods & {"cli.py", "api.py", "allocator/explain.py", "render_png.py", "build_town.py", "daytona/pool.py"}
