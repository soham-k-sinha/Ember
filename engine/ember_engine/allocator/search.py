"""The allocator (TECHNICAL.md §3.5): search over candidate plans with the simulator as the oracle.

    plan = allocate(world, scenario, reports=[...])                         # initial plan at t=0
    plan = allocate(world, scenario, reports=[...], t_now=t, prev=prev_plan, prev_reports=[...])   # replan

1. Candidates from priority rules (deadline-first, least-slack, largest-household, mobility-first,
   nearest-first) × reserve held/released × generator policy (dependency-first, critical-first, none)
   × keeping the accessible van for mobility needs. On a replan: work already under way is kept
   (cancelled only if new facts make it infeasible) and variants that move a generator are added.
2. Each candidate is simulated; the lexicographically best is improved by a seeded local search
   (relocate / swap / reorder / insert / drop pickups), every move scored by the simulator.
3. ETAs, rationale, unmet needs and questions come from the winning simulation (explain.py).
The allocator never trusts its own estimates over the simulator's. Deterministic for a given seed.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace

from ..models.facilities import compatible
from ..sim.plan_sim import cut_at, simulate
from .context import VEHICLES, Context

PROTECT_TYPES = ("pumping_station", "hospital", "clinic")


def objective(m: dict, churn: int = 0) -> tuple:
    """Lexicographic: people unreached ↓, hospital outage ↓, overflow ↓, people reached ↑,
    changed assignments vs the previous plan ↓ (every change is a message to a person), fuel+km ↓, reserve kept ↑."""
    return (m["people_unreached"], round(m["hospital_outage_s"]), round(m["overflow_m3"], 1),
            -m["people_reached_before_deadline"], churn, round(m["fuel_l"] + m["vehicle_km"], 1), -m["reserve_remaining"])


@dataclass(frozen=True)
class Policy:
    order: str = "deadline"
    use_reserve: bool = False
    protect: str = "dependency"
    keep_accessible: bool = True
    feasible_only: bool = True
    move_generators: bool = False

    def label(self) -> str:
        return (f"{self.order}-first, reserve {'released' if self.use_reserve else 'held'}, generators {self.protect}"
                + ("" if self.keep_accessible else ", accessible van for anyone")
                + ("" if self.feasible_only else ", best effort past deadlines")
                + (", generators re-targeted" if self.move_generators else ""))


POLICIES = [Policy(order="previous"), Policy(order="previous", use_reserve=True)] + [
    Policy(order=o, use_reserve=r) for o in ("deadline", "slack", "people", "mobility", "nearest") for r in (False, True)] + [
    Policy(protect="critical_first"), Policy(protect="none"), Policy(keep_accessible=False), Policy(feasible_only=False),
    Policy(order="slack", feasible_only=False, use_reserve=True)]


# ---------- carry-over for a replan ----------
@dataclass
class Carry:
    kept: list          # assignments from the previous plan that stay (history, in progress, sticky)
    slots: dict         # rid → Slot at t_now
    served: set         # household ids handled by kept work
    protected: dict     # facility id → generator rid (kept protect work)
    movable: list       # kept protect assignments a variant may cancel to re-target the generator
    prev_queues: dict = None   # rid → [hid] of the previous plan's not-started rescues (the low-churn candidate)
    prev_pairs: set = None     # (rid, hid) of the previous plan's rescues not yet started
    pinned: dict = None        # (rid, hid) → confirmed, not-started rescue: stays on that vehicle, keeps its place in the queue


def carry_over(ctx: Context, prev: dict | None, prev_reports) -> Carry:
    slots = ctx.fleet()
    if not prev:
        return Carry([], slots, set(), {}, [], {}, set(), {})
    t = ctx.t_now
    res = simulate(ctx.world, ctx.scn, prev, reports=prev_reports)
    i = res.tick_index(t)
    out = {o["assignment_id"]: o for o in res.outcomes}
    kept, served, protected, movable = [], set(), {}, []
    prev_queues, prev_pairs, pinned = {}, set(), {}
    for rid, s in slots.items():   # where each resource is at t_now
        tl = res.timeline["res"][rid]
        n = tl["node"][i]
        e = tl["edge"][i]
        s.node = ctx.world.node_index(n) if n is not None else int(ctx.world.edge_v[e])
        s.available = tl["status"][i] != "out_of_service"
    for a in prev.get("assignments", []):
        o = out[a["id"]]
        status = a.get("status")
        if status == "rejected":   # a person declined: history, and never this vehicle for that target again
            kept.append(a if a.get("cancelled_at_t_s") is not None else dict(a, cancelled_at_t_s=t))
            ctx.banned.add((a["resource_id"], a["target"].get("household_id", a["target"].get("facility_id"))))
            continue
        if cut_at(a) is not None and cut_at(a) <= t:
            kept.append(a)   # history
            continue
        if a.get("cancelled_at_t_s") is not None:   # a decline taken back (status live again): a live assignment
            a = dict(a, cancelled_at_t_s=None)
        ended = o["end_t"] is not None and o["end_t"] <= t
        started = o["start_t"] is not None and o["start_t"] <= t
        s = slots[a["resource_id"]]
        if a["task"] == "protect":
            if started or a.get("status") == "confirmed":
                kept.append(a)
                protected[a["target"]["facility_id"]] = a["resource_id"]
                s.available = False
                if o["status"] in ("done", "en_route", "working", "pending"):
                    movable.append(a)
            continue
        if a["task"] != "rescue":
            if started:
                kept.append(a)
            continue
        hid = a["target"]["household_id"]
        if ended:
            kept.append(a)
            if o["status"] == "done" or o["pickup_t"] is not None:
                served.add(hid)
            continue
        picked = o["pickup_t"] is not None and o["pickup_t"] <= t
        if started and (picked or ctx.eligible(s.spec, hid)):
            kept.append(a); served.add(hid)
            drop = a.get("dropoff_facility_id") if a.get("dropoff_facility_id") in ctx.fac else None
            done_at = o["complete_t"] if o["complete_t"] is not None else ctx.rescue_cycle(s, hid, drop)[1]
            s.free_at, s.node = max(s.free_at, done_at), ctx.after_rescue(hid, drop)
        elif started:
            kept.append(dict(a, status="cancelled", cancelled_at_t_s=t))       # new facts made it infeasible
        elif a.get("status") == "confirmed" and ctx.eligible(s.spec, hid):
            pinned[(a["resource_id"], hid)] = a                                 # sticky, but not queue-jumping
            prev_queues.setdefault(a["resource_id"], []).append(hid)
            prev_pairs.add((a["resource_id"], hid))
        else:
            prev_queues.setdefault(a["resource_id"], []).append(hid)
            prev_pairs.add((a["resource_id"], hid))
    return Carry(kept, slots, served, protected, movable, prev_queues, prev_pairs, pinned)


# ---------- construction ----------
def _order(ctx: Context, hids: list, how: str) -> list:
    d = lambda h: ctx.deadline.get(h) if ctx.deadline.get(h) is not None else 1e12  # noqa: E731
    out_t = ctx.tf(ctx.base_node)
    if how == "slack":
        return sorted(hids, key=lambda h: (d(h) - float(out_t[ctx.hh_node[h]]), h))
    if how == "people":
        return sorted(hids, key=lambda h: (-ctx.needs[h]["people"], d(h), h))
    if how == "mobility":
        return sorted(hids, key=lambda h: (not (ctx.needs[h].get("mobility") or ctx.needs[h].get("accessible_vehicle")), d(h), h))
    if how == "nearest":
        return sorted(hids, key=lambda h: (float(out_t[ctx.hh_node[h]]), h))
    return sorted(hids, key=lambda h: (d(h), -ctx.needs[h]["people"], h))


def _held(ctx: Context, slots: dict, pol: Policy) -> set:
    if pol.use_reserve:
        return set()
    rsv = ctx.scn.get("reserve", {})
    veh = sorted((s for s in slots.values() if s.spec["kind"] in VEHICLES and s.available), key=lambda s: -s.spec.get("capacity_people", 0))
    gen = sorted((s for s in slots.values() if s.spec["kind"] == "generator" and s.available), key=lambda s: s.spec.get("kw", 0))
    return {s.rid for s in veh[:rsv.get("vans", 0)]} | {s.rid for s in gen[:rsv.get("generators", 0)]}


def construct(ctx: Context, carry: Carry, pol: Policy) -> tuple[dict, list, dict]:
    """→ (rescue queues {rid: [hid]}, protect list [(rid, fid)], cancel {assignment id: …} for moved generators)."""
    slots = {k: replace(v) for k, v in carry.slots.items()}
    held = _held(ctx, slots, pol)
    protects, cancels = [], {}
    protected = dict(carry.protected)
    if pol.move_generators:
        for a in carry.movable:
            cancels[a["id"]] = a
            protected.pop(a["target"]["facility_id"], None)
            s = slots[a["resource_id"]]
            s.available, s.node = True, ctx.fac_node[a["target"]["facility_id"]]
            s.free_at = max(s.free_at, ctx.t_now + 600.0)   # disconnect + load
    if pol.protect != "none":
        threats = [(k, d) for k, (_, d) in ctx.power_risk.items()
                   if d is not None and k not in protected and ctx.fac[k]["type"] in PROTECT_TYPES and ctx.fac[k].get("connector")]
        crit = lambda k: 0 if ctx.fac[k].get("critical") or ctx.fac[k]["type"] == "hospital" else 1  # noqa: E731
        threats.sort(key=(lambda kd: (crit(kd[0]), kd[1])) if pol.protect == "critical_first" else (lambda kd: (kd[1], crit(kd[0]))))
        for k, down_t in threats:
            cands = [s for s in slots.values() if s.spec["kind"] == "generator" and s.available and s.rid not in held
                     and compatible(s.spec, ctx.fac[k])[0] and (s.rid, k) not in ctx.banned]
            if not cands:
                continue
            g = min(cands, key=lambda s: (s.free_at + ctx.travel(s.spec, s.node, ctx.fac_node[k]) > down_t, -s.spec["kw"],
                                          ctx.travel(s.spec, s.node, ctx.fac_node[k])))
            g.available = False
            protects.append((g.rid, k))
    queues = {k: [] for k, s in slots.items() if s.spec["kind"] in VEHICLES}
    todo = [h for h in ctx.hh if h not in carry.served and ctx.needs[h] != "unknown"]
    if pol.order == "previous":
        for rid, hids in (carry.prev_queues or {}).items():
            s = slots.get(rid)
            for hid in hids:
                if s is not None and s.available and hid in todo and ctx.eligible(s.spec, hid):
                    queues[rid].append(hid)
                    s.free_at, s.node = ctx.rescue_cycle(s, hid)[1], ctx.after_rescue(hid)
                    todo.remove(hid)
    pin = {hid: rid for rid, hid in (carry.pinned or {})}
    for hid in _order(ctx, todo, "deadline" if pol.order == "previous" else pol.order):
        need = ctx.needs[hid]
        mob = need.get("mobility") or need.get("accessible_vehicle")
        if hid in pin and pin[hid] in queues:   # confirmed: that vehicle, in deadline order with the rest of its queue
            s = slots[pin[hid]]
            queues[s.rid].append(hid)
            s.free_at, s.node = ctx.rescue_cycle(s, hid)[1], ctx.after_rescue(hid)
            continue
        best = None
        for s in slots.values():
            if not s.available or s.rid in held or not ctx.eligible(s.spec, hid):
                continue
            arrive, free = ctx.rescue_cycle(s, hid)
            score = arrive + (600.0 if pol.keep_accessible and s.spec.get("accessible") and not mob else 0.0)
            if arrive != float("inf") and (best is None or score < best[0]):
                best = (score, s, arrive, free)
        if best is None:
            continue
        _, s, arrive, free = best
        d = ctx.deadline.get(hid)
        if pol.feasible_only and d is not None and arrive > d:
            continue
        queues[s.rid].append(hid)
        s.free_at, s.node = free, ctx.after_rescue(hid)
    return queues, protects, cancels


def assemble(ctx: Context, carry: Carry, queues: dict, protects: list, cancels: dict, version: int) -> list:
    t = ctx.t_now
    nb = t if t > 0 else None
    out = [dict(a, status="cancelled", cancelled_at_t_s=t) if a["id"] in cancels else a for a in carry.kept]
    pinned = carry.pinned or {}
    ids = {a["id"] for a in out} | {a["id"] for a in pinned.values()}

    def new_id(base):
        i, k = base, 2
        while i in ids:
            i, k = f"{base}-v{version}-{k}", k + 1
        ids.add(i)
        return i
    for rid, fid in protects:
        out.append({"id": new_id(f"a-{rid}-{fid}"), "plan_version": version, "resource_id": rid, "task": "protect",
                    "target": {"facility_id": fid}, "dropoff_facility_id": None, "eta_s": 0.0, "status": "proposed",
                    "not_before_t_s": nb, "rationale": ""})
    room = {k: float(ctx.fac[k].get("capacity_people", float("inf"))) for k in ctx.dropoffs}
    for a in out:   # people already headed to a drop-off by kept work
        if a["task"] == "rescue" and a.get("dropoff_facility_id") in room and cut_at(a) is None:
            room[a["dropoff_facility_id"]] -= _people(ctx, a["target"]["household_id"])

    def dropoff(hid):   # nearest drop-off with room; the nearest one if all are full
        k = next((k for k in ctx.dropoff_order(hid) if room[k] >= _people(ctx, hid)), ctx.dropoff_for(hid))
        room[k] -= _people(ctx, hid)
        return k
    for rid, hids in queues.items():
        for hid in hids:
            if (rid, hid) in pinned:
                out.append(pinned[(rid, hid)])
                continue
            out.append({"id": new_id(f"a-{rid}-{hid}"), "plan_version": version, "resource_id": rid, "task": "rescue",
                        "target": {"household_id": hid}, "dropoff_facility_id": dropoff(hid), "eta_s": 0.0, "status": "proposed",
                        "not_before_t_s": nb, "rationale": ""})
    return out


def _people(ctx: Context, hid: int) -> int:
    need = ctx.needs.get(hid)
    return int(need["people"]) if isinstance(need, dict) else 0


# ---------- search ----------
INITIAL_MOVES, REPLAN_MOVES = 120, 60   # local-search budget: the initial plan can take longer; replans target < 2 s


@dataclass
class Candidate:
    cid: str
    key: tuple
    pol: Policy
    assignments: list
    result: object          # SimResult on the nominal scenario (record=False)
    note: str = ""


@dataclass
class Search:
    ctx: Context
    carry: Carry
    version: int
    reports: list
    ranked: list            # [Candidate], best first; ranked[0] is the local-search winner
    constructed: int
    moves_scored: int
    seed: int
    t0: float


def search(world, scn: dict, reports=(), t_now: float = 0.0, prev: dict | None = None, prev_reports=None,
           seed: int = 0, moves: int | None = None, policies=None) -> Search:
    """Candidates from priority rules + local search on the best; every plan scored by the simulator."""
    t0 = time.time()
    reports = list(reports)
    ctx = Context(world, scn, reports, t_now)
    carry = carry_over(ctx, prev, prev_reports if prev_reports is not None else reports)
    version = (prev.get("version", 0) + 1) if prev else 1
    moves = moves if moves is not None else (REPLAN_MOVES if prev else INITIAL_MOVES)
    pols = list(policies or POLICIES)
    if carry.movable:   # every rescue rule also gets a variant that may re-target generators already committed
        pols += [replace(p, move_generators=True) for p in pols if p.protect != "none" and not p.move_generators]
        pols.append(Policy(protect="critical_first", move_generators=True))
        pols = list(dict.fromkeys(pols))

    def churn(q) -> int:
        if not carry.prev_pairs:
            return 0
        now = {(rid, h) for rid, hs in q.items() for h in hs}
        moved = {h for _, h in carry.prev_pairs} - {h for _, h in carry.prev_pairs & now}
        return len(moved)

    def score(plan_assign, q):
        r = simulate(world, scn, {"assignments": plan_assign}, reports=reports, record=False)
        return objective(r.metrics, churn(q)), r

    cands = []
    seen = set()
    for pol in pols:
        q, pr, cn = construct(ctx, carry, pol)
        sig = (tuple((k, tuple(v)) for k, v in sorted(q.items())), tuple(pr), tuple(sorted(cn)))
        if sig in seen:
            continue
        seen.add(sig)
        a = assemble(ctx, carry, q, pr, cn, version)
        k, r = score(a, q)
        cands.append((k, pol, q, pr, cn, a, r))
    cands.sort(key=lambda c: c[0])
    best_k, best_pol, q, pr, cn, best_a, best_r = cands[0]

    # local search on the rescue queues of the best candidate
    rng = random.Random(seed)
    q = {k: list(v) for k, v in q.items()}
    tried = 0
    for _ in range(moves):
        nq = {k: list(v) for k, v in q.items()}
        if not _move(ctx, carry, nq, rng):
            continue
        a = assemble(ctx, carry, nq, pr, cn, version)
        k, r = score(a, nq)
        tried += 1
        if k < best_k:
            best_k, q, best_a, best_r = k, nq, a, r
    ranked = [Candidate("c00", best_k, best_pol, best_a, best_r, "best rule + local search")]
    ranked += [Candidate(f"c{i:02d}", c[0], c[1], c[5], c[6]) for i, c in enumerate(cands[1:], start=1)]
    return Search(ctx, carry, version, reports, ranked, len(cands), tried, seed, t0)


def finalize(s: Search, chosen: Candidate, prev: dict | None = None, trigger: str | None = None) -> dict:
    """The published plan for one candidate: simulated ETAs, rationale, unmet needs, questions, diff."""
    from .explain import explain
    plan = explain(s.ctx, s.carry, chosen.assignments, chosen.result, s.reports, version=s.version, prev=prev, pol=chosen.pol)
    plan["trigger"] = trigger or ("initial plan" if prev is None else f"replan at {s.ctx.t_now/60:.0f} min")
    plan["search"] = {"candidates": s.constructed, "moves_scored": s.moves_scored, "policy": chosen.pol.label(), "seed": s.seed,
                      "candidate": chosen.cid, "objective": list(chosen.key), "wall_s": round(time.time() - s.t0, 3)}
    plan["metrics"]["replan_latency_s"] = round(time.time() - s.t0, 3)
    return plan


def allocate(world, scn: dict, reports=(), t_now: float = 0.0, prev: dict | None = None, prev_reports=None,
             seed: int = 0, moves: int | None = None, policies=None, trigger: str | None = None) -> dict:
    s = search(world, scn, reports, t_now, prev, prev_reports, seed, moves, policies)
    return finalize(s, s.ranked[0], prev, trigger)


def _move(ctx: Context, carry: Carry, q: dict, rng: random.Random) -> bool:
    """One random neighbourhood move on the rescue queues (in place). False if nothing applicable."""
    vehicles = [k for k in q if carry.slots[k].available]
    pin = {hid: rid for rid, hid in (carry.pinned or {})}
    assigned = [(k, i) for k in q for i in range(len(q[k])) if q[k][i] not in pin]   # pinned: reorder only
    in_q = {h for v in q.values() for h in v}
    unserved = [h for h in ctx.hh if h not in carry.served and h not in in_q and ctx.needs[h] != "unknown"]
    kind = rng.choice(["relocate", "swap", "reorder", "insert", "drop"])
    if kind == "insert" and unserved:
        h = rng.choice(sorted(unserved))
        ok = [k for k in vehicles if ctx.eligible(carry.slots[k].spec, h) and pin.get(h, k) == k]
        if not ok:
            return False
        k = rng.choice(ok)
        q[k].insert(rng.randint(0, len(q[k])), h)
        return True
    if not assigned:
        return False
    if kind == "drop":
        k, i = rng.choice(assigned)
        q[k].pop(i)
        return True
    if kind == "reorder":
        k = rng.choice([k for k in q if len(q[k]) >= 2] or [None])
        if k is None:
            return False
        i, j = rng.sample(range(len(q[k])), 2)
        q[k][i], q[k][j] = q[k][j], q[k][i]
        return True
    k, i = rng.choice(assigned)
    h = q[k][i]
    if kind == "relocate":
        ok = [v for v in vehicles if v != k and ctx.eligible(carry.slots[v].spec, h)]
        if not ok:
            return False
        v = rng.choice(ok)
        q[k].pop(i)
        q[v].insert(rng.randint(0, len(q[v])), h)
        return True
    others = [(v, j) for v, j in assigned if v != k and ctx.eligible(carry.slots[v].spec, h) and ctx.eligible(carry.slots[k].spec, q[v][j])]
    if not others:
        return False
    v, j = rng.choice(others)
    q[k][i], q[v][j] = q[v][j], q[k][i]
    return True
