"""The replan loop (TECHNICAL.md §4): report → allocator → new plan version → state → WS events.

The backend owns the sim clock, live reports, every plan version, messages and phones. The engine
derives everything else: after any change, simulate(current plan, reports) and take state_at(clock).

One asyncio lock serializes bootstrap / replans / clock moves, so two texts arriving together are
planned one after the other, each on top of the previous version. Engine work runs in a thread so
the event loop (WS clients, the Photon socket) keeps moving during a 0.5–2 s search.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from starlette.concurrency import run_in_threadpool

from .bus import Hub
from .contracts import validate_report
from .db import Store, thread_key
from .engine_bridge import FACT_KINDS, EngineBridge

log = logging.getLogger("residents.planner")

# Called after a new plan version is live: (plan_view, raw plan). Task 4 sends changed instructions here.
PlanHook = Callable[[dict, dict], Awaitable[Any]]
# Called after the clock moved (POST /clock, the drill): step-by-step directions that became due go out.
ClockHook = Callable[[], Awaitable[Any]]


class ReportError(ValueError):
    pass


def new_report_id() -> str:
    return f"r-{uuid.uuid4().hex[:10]}"


class Planner:
    def __init__(self, store: Store, hub: Hub, bridge: EngineBridge):
        self.store, self.hub, self.bridge = store, hub, bridge
        self.lock = asyncio.Lock()
        self.plan_hooks: list[PlanHook] = []
        self.clock_hooks: list[ClockHook] = []
        self._comparison: tuple[tuple, dict] | None = None
        self._optimizing = False
        self.last_optimize: dict | None = None

    # ---------- clock + state ----------
    def now(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    async def bootstrap(self, t_s: float = 0.0) -> dict:
        """Fresh scenario: plan v1 at t=0 with no live reports, state at `t_s`. Plan hooks run too, so
        opted-in phones get v1's open questions (the judge's phone shows EMBER's question right after a
        reset, as DEMO.md expects)."""
        async with self.lock:
            self.store.clear_scenario()
            await run_in_threadpool(self.bridge.set_extra_households, [])  # households texted in belong to the run
            # texts sent before this moment belong to the previous run (see Messenger._before_this_run)
            self.store.kv_set("run_started_at", datetime.now(timezone.utc).isoformat())
            plan = await run_in_threadpool(self.bridge.plan, [], 0.0, None, None, "initial plan")
            self.store.add_plan(plan, reports_used=[])
            self._comparison = None
            state = await self._refresh(t_s)
        await self._run_hooks(state["plan"])
        return self.store.snapshot()

    async def _run_hooks(self, view: dict) -> None:
        raw = self.store.current_plan()
        for hook in self.plan_hooks:
            try:
                await hook(view, raw)
            except Exception:  # noqa: BLE001 - a messaging failure must not undo a plan
                log.exception("plan hook failed for v%s", view["version"])

    async def _refresh(self, t_s: float) -> dict:
        """Recompute the engine-derived state at t_s from the current plan + live reports (lock held)."""
        plan = self.store.current_plan()
        if plan is None:
            raise RuntimeError("no plan yet; bootstrap first")
        reports = [r for r in self.store.reports() if r["observed_at_t_s"] <= t_s]
        state = await run_in_threadpool(self.bridge.state_at, plan, reports, t_s)
        state["t_s"] = float(t_s)
        state["plan_version"] = plan["version"]
        if state.get("plan") is not None:
            # the snapshot rebuilds the plan from the simulation, which drops the allocator's search info
            # and replan latency; carry them over for the rationale panel and the "<2 s" claim
            state["plan"]["search"] = plan.get("search")
            latency = (plan.get("metrics") or {}).get("replan_latency_s")
            state["plan"]["metrics"]["replan_latency_s"] = latency
            state["metrics"]["replan_latency_s"] = latency
        if state.get("plan") is not None:
            # confirmations are backend facts the simulator doesn't model: show them on the household
            confirmed = {a["target"].get("household_id") for a in state["plan"]["assignments"] if a["status"] == "confirmed"}
            for h in state["households"]:
                if h["household_id"] in confirmed and h["status"] == "assigned":
                    h["status"] = "confirmed"
        self.store.apply_snapshot(state)
        return self.store.snapshot()

    async def set_clock(self, t_s: float) -> dict:
        if not 0 <= t_s <= self.bridge.t_end_s:
            raise ValueError(f"t_s must be within [0, {self.bridge.t_end_s:.0f}]")
        async with self.lock:
            state = await self._refresh(t_s)
        await self.hub.broadcast("state", state, state["t_s"])
        for hook in self.clock_hooks:
            try:
                await hook()
            except Exception:  # noqa: BLE001 - a messaging failure must not break the clock
                log.exception("clock hook failed at t=%.0f", t_s)
        return state

    # ---------- households added at runtime (a resident texted their location, D56) ----------
    def extra_households(self) -> list[dict]:
        return json.loads(self.store.kv_get("extra_households") or "[]")

    async def restore_households(self) -> None:
        """After a restart: give the engine back the households this run added (kv is the record)."""
        extra = self.extra_households()
        if extra:
            await run_in_threadpool(self.bridge.set_extra_households, extra)
            log.info("restored %d household(s) added by location texts", len(extra))

    async def add_household(self, entry: dict) -> None:
        """Make a town building an assisted household of this run (needs unknown). The caller replans."""
        async with self.lock:
            extra = self.extra_households()
            if any(h["household_id"] == entry["household_id"] for h in extra):
                raise ReportError(f"household {entry['household_id']} was already added")
            extra.append(entry)
            await run_in_threadpool(self.bridge.set_extra_households, extra)
            self.store.kv_set("extra_households", json.dumps(extra))

    # ---------- reports → replan ----------
    async def submit_report(self, report: dict, replan: bool = True) -> tuple[dict, dict | None]:
        """Validate + store a report (id / observed_at default to new / the clock), then replan if it's a
        fact. Returns (report, new plan view or None)."""
        report = dict(report)
        report.setdefault("id", new_report_id())
        report.setdefault("observed_at_t_s", self.now())
        report.setdefault("confidence", 1.0)
        report.setdefault("resolved", False)
        errs = validate_report(report)
        if errs:
            raise ReportError("; ".join(errs))
        if report["observed_at_t_s"] > self.bridge.t_end_s:
            raise ReportError("observed_at_t_s is after the scenario ends")
        self._check_refs(report)
        if any(r["id"] == report["id"] for r in self.store.reports()):
            raise ReportError(f"report {report['id']} already exists")
        self.store.add_report(report)
        await self.hub.broadcast("report", report, self.now())
        if not replan or report["kind"] not in FACT_KINDS:
            return report, None
        plan = await self.replan(trigger=self._trigger(report))
        return self.store.reports_by_id([report["id"]])[0], plan

    def _check_refs(self, r: dict) -> None:
        if "household_id" in r and not self.bridge.has_household(r["household_id"]):
            raise ReportError(f"household {r['household_id']} is not an assisted household in {self.bridge.scenario_id}")
        if "facility_id" in r and not self.bridge.has_facility(r["facility_id"]):
            raise ReportError(f"facility {r['facility_id']!r} is not in {self.bridge.scenario_id}")
        for e in (r.get("payload") or {}).get("edge_ids", []):
            if not self.bridge.has_edge(e):
                raise ReportError(f"edge {e} is not in town.json")
        if r["kind"] == "closure_report" and not (r.get("payload") or {}).get("edge_ids"):
            raise ReportError("closure_report needs payload.edge_ids (resolve road_hint to edges first)")

    def _trigger(self, r: dict) -> str:
        who = f"household #{r['household_id']}" if "household_id" in r else r.get("facility_id", r["source"])
        what = {"need": "needs", "closure_report": "road closed", "facility_status": "status"}[r["kind"]]
        return f"report {r['id']} ({r['source']}): {who} {what}"

    def _known(self) -> tuple[float, dict | None, list[dict], list[dict]]:
        """(clock, current raw plan, reports known by the clock, the ones the current plan already saw)."""
        prev = self.store.current_plan()
        t_now = self.now()
        known = [r for r in self.store.reports() if r["observed_at_t_s"] <= t_now]
        prev_used = set(self.store.plan_reports_used(prev["version"])) if prev else set()
        return t_now, prev, known, [r for r in known if r["id"] in prev_used]

    async def replan(self, trigger: str = "manual replan") -> dict:
        """New plan version from the current one + every report known by the clock. Broadcasts `plan`
        and one `assignment` event per change, then runs plan hooks (outbound messages)."""
        t0 = time.time()
        async with self.lock:
            t_now, prev, known, prev_reports = self._known()
            plan = await run_in_threadpool(self.bridge.plan, known, t_now, prev, prev_reports, trigger)
            state = await self._store_plan(plan, known, t_now)
        return await self._publish(state, trigger, t0)

    async def _store_plan(self, plan: dict, known: list[dict], t_now: float) -> dict:
        """(lock held) Make `plan` the current version and recompute the state."""
        used = [r["id"] for r in known if r["kind"] in FACT_KINDS]
        self.store.add_plan(plan, reports_used=used)
        self.store.mark_reports_resolved(used)
        self._comparison = None
        return await self._refresh(t_now)

    async def _publish(self, state: dict, trigger: str, t0: float) -> dict:
        view = state["plan"]
        log.info("plan v%s (%s): %d changes in %.2fs", view["version"], trigger, len(view.get("changes", [])), time.time() - t0)
        await self.hub.broadcast("plan", view, state["t_s"])
        by_id = {a["id"]: a for a in view["assignments"]}
        for ch in view.get("changes", []):
            await self.hub.broadcast("assignment", {
                "plan_version": view["version"], "change": ch["change"], "assignment_id": ch["assignment_id"],
                "assignment": None if ch["change"] == "removed" else by_id.get(ch["assignment_id"]),
                **({"note": ch["note"]} if ch.get("note") else {})}, state["t_s"])
        await self.hub.broadcast("metrics", state["metrics"], state["t_s"])
        await self._run_hooks(view)
        return view

    # ---------- confirm / reject (Task 5) ----------
    async def respond(self, assignment_id: str, decision: str, answered_version: int | None = None,
                      on_applied: Callable[[dict], Awaitable[Any]] | None = None) -> dict:
        """A person accepts or declines an offered assignment.

        `answered_version` = the plan version of the message they replied to. If the plan moved on since
        and that assignment changed (gone, or a different resource / target), the reply is stale: nothing
        is applied and the caller re-sends the latest instruction. Reject → status `rejected` + replan;
        the backend never re-offers that vehicle to that thread (outbound) even if the allocator proposes it
        again. Returns {applied, stale, reason, assignment}."""
        if decision not in ("confirm", "reject"):
            raise ValueError("decision must be confirm or reject")
        async with self.lock:
            current = self.store.current_plan()
            if current is None:
                return {"applied": False, "stale": False, "reason": "no plan", "assignment": None}
            a = next((x for x in current["assignments"] if x["id"] == assignment_id), None)
            stale_reason = None
            if a is None:
                stale_reason = f"{assignment_id} is not in plan v{current['version']}"
            elif answered_version is not None and answered_version < current["version"]:
                old_plan = self.store.plan(answered_version)
                old = next((x for x in (old_plan or {}).get("assignments", []) if x["id"] == assignment_id), None)
                if old is None or old["resource_id"] != a["resource_id"] or old["target"] != a["target"]:
                    stale_reason = f"answered v{answered_version}, but {assignment_id} changed by v{current['version']}"
            if stale_reason:
                log.info("stale %s: %s", decision, stale_reason)
                return {"applied": False, "stale": True, "reason": stale_reason, "assignment": a}
            new = "confirmed" if decision == "confirm" else "rejected"
            if a.get("status") == new:
                return {"applied": False, "stale": False, "reason": f"already {new}", "assignment": a}
            if not self.store.set_assignment_status(current["version"], assignment_id, new, ("proposed", "offered", "confirmed")):
                return {"applied": False, "stale": False, "reason": f"can't {decision} a {a.get('status')} assignment", "assignment": a}
            if decision == "reject":
                key = thread_key(a["target"]) if "edge_ids" not in a["target"] else None
                if key:
                    pairs = json.loads(self.store.kv_get(f"rejected:{key}") or "[]")
                    pairs.append(a["resource_id"])
                    self.store.kv_set(f"rejected:{key}", json.dumps(sorted(set(pairs))))
            state = await self._refresh(self.now())
        a = next(x for x in state["plan"]["assignments"] if x["id"] == assignment_id)
        await self.hub.broadcast("assignment", {"plan_version": state["plan_version"], "change": "status_changed",
                                                "assignment_id": assignment_id, "assignment": a}, state["t_s"])
        if on_applied is not None:
            await on_applied(a)
        if decision == "reject":
            await self.replan(trigger=f"{assignment_id} rejected")
        return {"applied": True, "stale": False, "reason": None, "assignment": a}

    # ---------- robust optimization (Daytona / local pool) ----------
    @property
    def optimizing(self) -> bool:
        return self._optimizing

    async def optimize(self, seeds: int = 50, k: int = 4) -> dict:
        """Top-k candidate plans × `seeds` perturbed worlds (+ the baseline), on Daytona when engine has a
        key, else a local process pool. Every run is broadcast as a `scatter_point` as it lands; the
        plan with the best worst-20% outcome becomes the next version."""
        if self._optimizing:
            raise RuntimeError("an optimization is already running")
        self._optimizing = True
        t0 = time.time()
        loop = asyncio.get_running_loop()
        sent: list[asyncio.Future] = []
        try:
            async with self.lock:  # only to read a consistent starting point
                t_now, prev, known, prev_reports = self._known()
            start_version = prev["version"] if prev else None

            def on_point(p: dict) -> None:  # called on the engine's worker thread
                sent.append(asyncio.run_coroutine_threadsafe(self.hub.broadcast("scatter_point", p, t_now), loop))

            # the fan-out (a few seconds, locally or on Daytona) runs WITHOUT the planner lock, so the web's
            # clock ticks, texts and replans keep flowing meanwhile
            plan = await run_in_threadpool(self.bridge.optimize, known, t_now, prev, on_point, seeds, k)
            await asyncio.gather(*(asyncio.wrap_future(f) for f in sent))  # every point before the plan
            async with self.lock:
                now_version = self.store.meta().get("plan_version")
                if now_version != start_version:  # a report replanned meanwhile: don't overwrite newer facts
                    raise RuntimeError(f"superseded: plan moved v{start_version} → v{now_version} during the optimization")
                state = await self._store_plan(plan, known, t_now)
            view = await self._publish(state, "robust optimization", t0)
            self.last_optimize = {"plan_version": view["version"], "points": len(sent), "wall_s": round(time.time() - t0, 2),
                                  "robust": (view.get("search") or {}).get("robust"), "error": None}
            return self.last_optimize
        except Exception as e:
            self.last_optimize = {"plan_version": None, "points": len(sent), "wall_s": round(time.time() - t0, 2), "error": str(e)}
            raise
        finally:
            self._optimizing = False

    # ---------- simulate (Task 7) ----------
    async def simulate(self, planner: str) -> dict:
        """Projected metrics over the whole horizon for the current plan ("ember") or the incident-by-
        incident baseline ("baseline"), both with every report known by the clock."""
        if planner not in ("ember", "baseline"):
            raise ValueError("planner must be ember or baseline")
        async with self.lock:
            t_now, current, known, _ = self._known()
            metrics = await run_in_threadpool(self.bridge.simulate, planner, current, known)
        return {"planner": planner, "plan_version": current["version"] if current else None, "t_s": t_now, "metrics": metrics}

    # ---------- disruption ----------
    async def close_road(self, edge_ids: list[int], source: str = "judge", note: str | None = None) -> tuple[dict, dict | None]:
        for e in edge_ids:
            if not self.bridge.has_edge(e):
                raise ReportError(f"edge {e} is not in town.json")
        both = self.bridge.both_directions(edge_ids)
        names = sorted({self.bridge.edge_name(e) for e in both})
        return await self.submit_report({"source": source, "kind": "closure_report", "payload": {"edge_ids": both},
                                         "text": note or f"closed: {', '.join(names)}"})

    async def set_facility(self, facility_id: str, fields: dict, source: str = "judge", note: str | None = None) -> tuple[dict, dict | None]:
        if not fields:
            raise ReportError("set needs at least one field")
        return await self.submit_report({"source": source, "kind": "facility_status", "facility_id": facility_id,
                                         "payload": {"set": fields}, **({"text": note} if note else {})})

    # ---------- comparison ----------
    async def comparison(self, seeds: int = 5) -> dict:
        """Baseline vs EMBER on paired perturbations, for the reports known now. Cached per plan version."""
        key = (self.store.meta().get("plan_version"), len(self.store.reports()), seeds)
        if self._comparison and self._comparison[0] == key:
            return self._comparison[1]
        async with self.lock:
            known = [r for r in self.store.reports() if r["observed_at_t_s"] <= self.now()]
            result = await run_in_threadpool(self.bridge.compare, known, seeds)
        self._comparison = (key, result)
        return result
