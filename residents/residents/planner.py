"""The replan loop (TECHNICAL.md §4): report → allocator → new plan version → state → WS events.

The backend owns the sim clock, live reports, every plan version, messages and phones. The engine
derives everything else: after any change, simulate(current plan, reports) and take state_at(clock).

One asyncio lock serializes bootstrap / replans / clock moves, so two texts arriving together are
planned one after the other, each on top of the previous version. Engine work runs in a thread so
the event loop (WS clients, the Photon socket) keeps moving during a 0.5–2 s search.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from starlette.concurrency import run_in_threadpool

from .bus import Hub
from .contracts import validate_report
from .db import Store
from .engine_bridge import FACT_KINDS, EngineBridge

log = logging.getLogger("residents.planner")

# Called after a new plan version is live: (plan_view, raw plan). Task 4 sends changed instructions here.
PlanHook = Callable[[dict, dict], Awaitable[Any]]


class ReportError(ValueError):
    pass


def new_report_id() -> str:
    return f"r-{uuid.uuid4().hex[:10]}"


class Planner:
    def __init__(self, store: Store, hub: Hub, bridge: EngineBridge):
        self.store, self.hub, self.bridge = store, hub, bridge
        self.lock = asyncio.Lock()
        self.plan_hooks: list[PlanHook] = []
        self._comparison: tuple[tuple, dict] | None = None

    # ---------- clock + state ----------
    def now(self) -> float:
        return float(self.store.meta().get("t_s", 0.0))

    async def bootstrap(self, t_s: float = 0.0) -> dict:
        """Fresh scenario: plan v1 at t=0 with no live reports, state at `t_s`."""
        async with self.lock:
            self.store.clear_scenario()
            plan = await run_in_threadpool(self.bridge.plan, [], 0.0, None, None, "initial plan")
            self.store.add_plan(plan, reports_used=[])
            self._comparison = None
            return await self._refresh(t_s)

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
        self.store.apply_snapshot(state)
        return self.store.snapshot()

    async def set_clock(self, t_s: float) -> dict:
        if not 0 <= t_s <= self.bridge.t_end_s:
            raise ValueError(f"t_s must be within [0, {self.bridge.t_end_s:.0f}]")
        async with self.lock:
            state = await self._refresh(t_s)
        await self.hub.broadcast("state", state, state["t_s"])
        return state

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

    async def replan(self, trigger: str = "manual replan") -> dict:
        """New plan version from the current one + every report known by the clock. Broadcasts `plan`
        and one `assignment` event per change, then runs plan hooks (outbound messages)."""
        t0 = time.time()
        async with self.lock:
            prev = self.store.current_plan()
            t_now = self.now()
            known = [r for r in self.store.reports() if r["observed_at_t_s"] <= t_now]
            prev_used = set(self.store.plan_reports_used(prev["version"])) if prev else set()
            prev_reports = [r for r in known if r["id"] in prev_used]
            plan = await run_in_threadpool(self.bridge.plan, known, t_now, prev, prev_reports, trigger)
            used = [r["id"] for r in known if r["kind"] in FACT_KINDS]
            self.store.add_plan(plan, reports_used=used)
            self.store.mark_reports_resolved(used)
            self._comparison = None
            state = await self._refresh(t_now)
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
        for hook in self.plan_hooks:
            try:
                await hook(view, plan)
            except Exception:  # noqa: BLE001 - a messaging failure must not undo a plan
                log.exception("plan hook failed for v%s", view["version"])
        return view

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
