"""End-to-end check of the running stack: backend (engine mode) + engine + Daytona/local pool + WebSocket.

Drives a live backend over HTTP and WS the way the website and the phones do, and checks every step against the
contracts and the demo story. No real phones, LLM or calls: texts go through /reports, /disruption and /dev/inbound,
and the empty keys below beat residents/.env. Use a fresh DB: players (D89) survive resets, and MAX_PLAYERS=3 makes the
cap check run. Daytona is real when engine/.env has its key; --big also runs /optimize on 10,000 worlds (seeds 2000).

    cd residents && DB_PATH=/tmp/e2e.db RESET_ON_START=1 PHOTON_ENABLED=0 EXTRACT_ENABLED=0 MAX_PLAYERS=3 \
        ANTHROPIC_API_KEY= ELEVENLABS_API_KEY= ELEVENLABS_AGENT_ID= ELEVENLABS_PHONE_NUMBER_ID= \
        uv run uvicorn residents.app:app --port 8000
    cd residents && uv run python ../engine/scripts/e2e.py [--base http://127.0.0.1:8000] [--skip-optimize] [--big]

Exit code 0 = every check passed. Re-run it after any merge.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
JUDGE = 10296
RIVER_ST = [523, 833, 951, 952]

results: list[tuple[bool, str, str]] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    results.append((bool(ok), what, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  ({detail})" if detail else ""), flush=True)
    return bool(ok)


class Events:
    """Collects WS envelopes in the background."""

    def __init__(self, url: str):
        self.url, self.items, self._task = url, [], None

    async def start(self):
        self._ws = await websockets.connect(self.url, max_size=None)
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        try:
            async for raw in self._ws:
                self.items.append(json.loads(raw))
        except Exception:  # noqa: BLE001 - closed
            pass

    def since(self, n: int, kind: str | None = None) -> list[dict]:
        return [e for e in self.items[n:] if kind is None or e.get("type") == kind]

    async def stop(self):
        await self._ws.close()
        if self._task:
            await asyncio.wait([self._task], timeout=2)


def live(a: dict) -> bool:
    return a.get("status") not in ("cancelled", "rejected")


def mine(plan: dict, hid: int) -> list[dict]:
    return [a for a in plan["assignments"] if a["target"].get("household_id") == hid and live(a)]


async def run_optimize(get, post, seeds: int | None) -> tuple[dict, float]:
    """POST /optimize and wait for it; (robust summary, wall seconds)."""
    t0 = time.time()
    await post("/optimize", params={"k": 4, **({"seeds": seeds} if seeds else {})})
    last = None
    while time.time() - t0 < 600:
        o = await get("/optimize")
        if not o["running"]:
            last = o["last"]
            break
        await asyncio.sleep(0.5)
    check(last is not None and not last.get("error"), f"optimize ({seeds or 50} seeds) finishes without error",
          f"{last and last.get('error')} in {time.time() - t0:.1f}s")
    rob = (last or {}).get("robust") or {}
    print(f"      pool={rob.get('pool')} workers={rob.get('workers')} jobs={rob.get('jobs')} startup={rob.get('startup_s')}s "
          f"fan-out={rob.get('fanout_wall_s')}s wall={time.time() - t0:.1f}s chosen={rob.get('chosen')} nominal={rob.get('nominal_best')} "
          f"worst20_unreached={ {r_['candidate']: r_['worst20_people_unreached'] for r_ in rob.get('ranking', [])} }")
    return rob, time.time() - t0


async def main(base: str, skip_optimize: bool, big: bool = False) -> int:
    from ember_engine.scenario import load_scenario
    from ember_engine.state import validate_state
    from residents.contracts import errors

    scn = load_scenario(ROOT / "scenarios" / "allston_flood_v1" / "scenario.json")
    town = json.loads(gzip.decompress((ROOT / "engine" / "data" / "town.json.gz").read_bytes()))
    c = httpx.AsyncClient(base_url=base, timeout=120)

    async def get(path, **kw):
        r = await c.get(path, **kw)
        r.raise_for_status()
        return r.json()

    async def post(path, body=None, **kw):
        r = await c.post(path, json=body if body is not None else {}, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} → {r.status_code} {r.text[:300]}")
        return r.json()

    async def state(label: str) -> dict:
        st = await get("/state")
        errs = validate_state(st, scn, town)
        check(not errs, f"{label}: /state validates against the contracts", "; ".join(errs[:3]))
        return st

    print("\n[0] backend")
    h = await get("/health")
    check(h.get("mode") == "engine", "backend runs in engine mode", f"mode={h.get('mode')}")
    check(h.get("scenario_id") == "allston_flood_v1", "scenario is allston_flood_v1", str(h.get("scenario_id")))
    print(f"      extraction={h.get('extraction')} photon={h.get('photon')}")

    ev = Events(base.replace("http", "ws", 1).rstrip("/") + "/ws")
    await ev.start()
    await asyncio.sleep(0.5)
    check(any(e.get("type") == "state" for e in ev.items), "WS sends a state snapshot on connect")

    print("\n[1] reset → plan v1")
    n = len(ev.items)
    await post("/dev/reset")
    await asyncio.sleep(0.5)
    st = await state("v1")
    p = st["plan"]
    check(st["plan_version"] == 1 and st["t_s"] == 0, "fresh plan v1 at t=0", f"v{st['plan_version']} t={st['t_s']}")
    check(bool(ev.since(n, "state")), "WS broadcasts the reset state")
    rescues = [a for a in p["assignments"] if a["task"] == "rescue"]
    check(rescues and all(a["dropoff_facility_id"] == "treehouse-shelter" for a in rescues),
          "every rescue drops off at the nearest shelter (Treehouse)", f"{len(rescues)} rescues")
    gens = [a for a in p["assignments"] if a["task"] == "protect" and live(a)]
    check([a["target"].get("facility_id") for a in gens] == ["cottage-farm"], "Generator 1 pre-positioned at Cottage Farm")
    check(p["metrics"]["overflow_m3"] == 0, "v1 projects 0 m³ untreated overflow", str(p["metrics"]["overflow_m3"]))
    unknown = {u["target"].get("household_id") for u in p["unresolved"] if u.get("need") == "unknown"}
    check(JUDGE in unknown, "the judge's needs are unknown, so the plan asks", f"unknown={sorted(unknown)}")
    check(any(q["to"].get("household_id") == JUDGE for q in p["info_requests"]), "plan v1 has a question for the judge")
    shared = [a for a in rescues if "shares the trip" in a.get("rationale", "")]
    check(len(shared) > 0, "neighbours share vans (shared trips in v1)", f"{len(shared)} shared pickups")
    print(f"      v1 metrics: {json.dumps({k: p['metrics'][k] for k in ('people_reached_before_deadline', 'people_unreached', 'overflow_m3', 'vehicle_km')})}")

    print("\n[2] judge at minute 5: need + River St closed")
    n = len(ev.items)
    r = await post("/clock", {"t_s": 300})
    check(r["t_s"] == 300, "clock moves to 5:00")
    t0 = time.time()
    r = await post("/reports", {"source": "judge", "kind": "need", "household_id": JUDGE,
                                "payload": {"people": 2, "mobility": True, "accessible_vehicle": True}})
    check(r.get("replanned"), "the judge's need triggers a replan", f"v{r.get('plan_version')} in {time.time() - t0:.2f}s")
    st = await state("after need")
    jm = mine(st["plan"], JUDGE)
    van = jm[0] if jm else None
    check(van is not None and van["resource_id"] == "van-3", "the judge gets Accessible Van 3",
          f"{van and van['resource_id']}")
    check(van is not None and van["eta_s"] <= (van["deadline_s"] or 1e9), "judge pickup before the deadline",
          f"eta {van and round(van['eta_s'] / 60)} vs deadline {van and van['deadline_s'] and round(van['deadline_s'] / 60)} min")
    gen_eta_before = next(a["eta_s"] for a in st["plan"]["assignments"] if a["task"] == "protect" and live(a))
    r = await post("/disruption", {"close_edges": RIVER_ST[:3] + [RIVER_ST[3]], "note": "River St blocked at Memorial Dr"})
    st = await state("after closure")
    closed = {c["edge_id"] for c in st["closures"]}
    check(set(RIVER_ST) <= closed, "River St edges are closed in the state", f"{sorted(closed & set(RIVER_ST))}")
    gen = next(a for a in st["plan"]["assignments"] if a["task"] == "protect" and live(a))
    check(abs(gen["eta_s"] - gen_eta_before) > 60 or "road reported closed" in gen.get("rationale", ""),
          "the closure changes the generator's route", f"ETA {round(gen_eta_before / 60)} → {round(gen['eta_s'] / 60)} min")
    await asyncio.sleep(0.3)
    kinds = {e.get("type") for e in ev.since(n)}
    check({"plan", "assignment", "metrics", "report"} <= kinds, "WS broadcasts plan, assignment, metrics, report events",
          ",".join(sorted(k for k in kinds if k)))

    print("\n[3] confirm and decline")
    jm = mine(st["plan"], JUDGE)
    r = await post(f"/assignments/{jm[0]['id']}/confirm", {"plan_version": st["plan_version"]})
    check(r.get("applied"), "the judge confirms the van")
    st = await state("after confirm")
    jm2 = mine(st["plan"], JUDGE)
    check(jm2 and jm2[0]["status"] == "confirmed", "the judge's assignment is confirmed")
    check(jm2 and abs(jm2[0]["eta_s"] - jm[0]["eta_s"]) < 900, "confirming doesn't reorder the van's queue",
          f"ETA {round(jm[0]['eta_s'] / 60)} → {jm2 and round(jm2[0]['eta_s'] / 60)} min")
    other = next(a for a in st["plan"]["assignments"]
                 if a["task"] == "rescue" and a["status"] in ("proposed", "offered") and a["resource_id"] != "van-3"
                 and a["target"]["household_id"] != JUDGE)
    hid, rid = other["target"]["household_id"], other["resource_id"]
    r = await post(f"/assignments/{other['id']}/reject", {"plan_version": st["plan_version"]})
    check(r.get("applied"), f"household #{hid} declines {rid}")
    st = await state("after decline")
    again = [a for a in mine(st["plan"], hid) if a["resource_id"] == rid]
    check(not again, "the declined vehicle is not proposed again", f"{[a['id'] for a in again]}")
    served = mine(st["plan"], hid) or [u for u in st["plan"]["unresolved"] if u["target"].get("household_id") == hid]
    check(bool(served), "the declining household gets another vehicle or an explained unresolved entry")

    print("\n[4] hospital at minute 15: on backup, 10 minutes left")
    await post("/clock", {"t_s": 900})
    await post("/disruption", {"facility_id": "mt-auburn", "set": {"state": "backup", "backup_endurance_s": 600},
                               "note": "Mount Auburn: on backup, 10 min left"})
    st = await state("after operator")
    gens = [a for a in st["plan"]["assignments"] if a["task"] == "protect" and live(a)]
    check([a["target"].get("facility_id") for a in gens] == ["mt-auburn"], "Generator 1 is re-targeted to Mount Auburn")
    m = st["plan"]["metrics"]
    check(m["hospital_outage_s"] < 1800, "projected hospital outage under 30 min", f"{m['hospital_outage_s'] / 60:.0f} min")
    cf = next((u for u in st["plan"]["unresolved"] if u["target"].get("facility_id") == "cottage-farm"), None)
    check(cf is not None and "instead" in cf["blocked_by"], "the overflow cost is stated with simulated numbers",
          (cf or {}).get("blocked_by", "")[:120])
    check(gens and "down at 25 min" in gens[0].get("rationale", ""), "the rationale uses the operator's 10 minutes")

    print("\n[5] comparison + simulate")
    cmp_ = await get("/comparison", params={"seeds": 5})
    rows = {r_["metric"]: r_ for r_ in cmp_["metrics"]}
    pr = rows["people_reached_before_deadline"]
    check(pr["diff_mean"] > 0 and pr["ember_better_seeds"] >= 4, "EMBER reaches more people than the baseline",
          f"{pr['ember_mean']} vs {pr['baseline_mean']} ({pr['diff_mean']:+})")
    check(rows["hospital_outage_s"]["diff_mean"] <= 0, "EMBER's hospital outage is not worse",
          f"{rows['hospital_outage_s']['ember_mean'] / 60:.0f} vs {rows['hospital_outage_s']['baseline_mean'] / 60:.0f} min")
    for planner in ("ember", "baseline"):
        sim = await post("/simulate", {"planner": planner})
        check("metrics" in sim or "people_unreached" in json.dumps(sim), f"POST /simulate {planner} returns metrics")
        pb = await get("/playback", params={"which": planner})
        errs = errors("playback", pb)
        check(not errs and pb["planner"] == planner, f"GET /playback?which={planner} validates against the contract",
              "; ".join(errs[:3]))

    if not skip_optimize:
        print("\n[6] robust optimization (Daytona, local fallback)")
        n = len(ev.items)
        v_before = (await get("/state"))["plan_version"]
        rob, _ = await run_optimize(get, post, None)
        await asyncio.sleep(0.5)
        pts = ev.since(n, "scatter_point")
        check(rob.get("pool") == "daytona" and rob.get("startup_s") is not None, "the runs go to the Daytona pool, startup reported",
              f"pool={rob.get('pool')} startup_s={rob.get('startup_s')}")
        check(len(pts) == rob.get("jobs") == 250, "250 runs (50 seeds by default) stream as scatter_points", f"{len(pts)}/{rob.get('jobs')}")
        st = await state("after optimize")
        check(st["plan_version"] == v_before + 1 and (st["plan"].get("search") or {}).get("robust"),
              "optimize publishes a new plan version with the robustness ranking", f"v{st['plan_version']}")
        check(all(p_["data"]["batch_id"] == rob.get("batch_id") for p_ in pts), "points carry the published batch id")
        if big:  # the scale where Daytona clearly beats the laptop (D86): 2000 seeds × (4 candidates + baseline)
            n = len(ev.items)
            rob, _ = await run_optimize(get, post, 2000)
            await asyncio.sleep(2)
            pts = ev.since(n, "scatter_point")
            check(rob.get("pool") == "daytona" and rob.get("jobs") == 10000, "10,000 worlds run on the Daytona pool",
                  f"pool={rob.get('pool')} jobs={rob.get('jobs')} fan-out={rob.get('fanout_wall_s')}s")
            check(len(pts) == 10000, "all 10,000 runs stream as scatter_points", f"{len(pts)}")

    print("\n[7] texting endpoints (no real phones)")
    try:
        r = await post("/ask", {"role": "operator", "facility_id": "mt-auburn"})
        check("message" in r, "POST /ask stores the operator prompt", f"delivery={r.get('delivery')}")
    except RuntimeError as e:
        check("409" in str(e), "POST /ask without an operator phone answers 409", str(e)[:100])
    try:
        r = await post("/dev/inbound", {"role": "resident", "household_id": JUDGE, "text": "how long until the van?"})
        check(r.get("message") is not None, "an inbound text is stored on the judge's thread")
    except RuntimeError as e:
        check("409" in str(e), "inbound text without a resident thread answers 409", str(e)[:100])
    q = await get("/questions")
    check(isinstance(q, list), "GET /questions lists the coordinator queue", f"{len(q)} open")
    calls = await get("/calls")
    check(set(calls) == {"live", "recent"} and all(isinstance(v, list) for v in calls.values()), "GET /calls is {live, recent}")

    print("\n[8] play the clock to the end of the horizon")
    prev_closed = 0
    for t in (1800, 3600, 5400, 7200, 9000, 10800, 14400):
        await post("/clock", {"t_s": t})
        st = await state(f"t={t / 60:.0f} min")
        nc = len(st["closures"])
        check(nc >= prev_closed, f"closures only grow as the flood rises ({nc} at {t / 60:.0f} min)")
        prev_closed = nc
    safe = [h for h in st["households"] if h["status"] == "safe"]
    unreached = [h for h in st["households"] if h["status"] == "unreached"]
    print(f"      end: {len(safe)} households safe, {len(unreached)} unreached, metrics {json.dumps(st['metrics'])[:200]}")
    check(len(safe) >= 25, "most households end safe at the shelter", f"{len(safe)}/{len(st['households'])}")
    check(st["metrics"]["hospital_outage_s"] < 1800, "hospital outage stays under 30 min by the end",
          f"{st['metrics']['hospital_outage_s'] / 60:.0f} min")

    print("\n[9] three phones register (POST /join), then text JOIN EMBER (multiplayer, D89)")
    await post("/dev/reset")
    await asyncio.sleep(3)  # players from earlier runs who texted are placed again, with their own replan
    v0 = (await get("/state"))["plan_version"]
    n0 = sum(p_["player"] is not None for p_ in await get("/phones"))
    first = 5550000 + int(time.time()) % 1000 * 10
    phones = [f"+1617{first + i}" for i in range(4)]
    regs = [await post("/join", {"handle": ph}) for ph in phones[:3]]
    check([r_["player"] for r_ in regs] == [n0 + 1, n0 + 2, n0 + 3] and all(r_["assigned_number"] for r_ in regs),
          "POST /join returns Player N and the line to text", str([(r_["player"], r_["assigned_number"]) for r_ in regs]))
    again = await post("/join", {"handle": phones[0]})
    check(again["player"] == n0 + 1, "POST /join is idempotent per phone", f"player {again['player']}")
    ps = {p_["handle"]: p_ for p_ in await get("/phones")}
    check(all(ps[ph]["household_id"] is None for ph in phones[:3]) and (await get("/state"))["plan_version"] == v0,
          "registered phones wait for their first text (no household, no replan yet)")
    for ph in phones[:3]:
        await post("/dev/inbound", {"role": "resident", "handle": ph, "text": "JOIN EMBER"})
    t0 = time.time()
    while (await get("/state"))["plan_version"] == v0 and time.time() - t0 < 20:
        await asyncio.sleep(0.5)
    await asyncio.sleep(3)
    ps = {p_["handle"]: p_ for p_ in await get("/phones")}
    got = [ps.get(ph, {}) for ph in phones[:3]]
    hids = [g.get("household_id") for g in got]
    check([g.get("player") for g in got] == [n0 + 1, n0 + 2, n0 + 3], "they are the next three players in GET /phones",
          str([g.get("player") for g in got]))
    st = await state("after joins")
    hh = {h_["household_id"]: h_ for h_ in st["households"]}
    check(None not in hids and len(set(hids)) == 3 and all(hh.get(x, {}).get("deadline_s") for x in hids),
          "on three distinct flood-zone households in /state", f"{[(x, hh.get(x, {}).get('deadline_s')) for x in hids]}")
    check(sorted(hh.get(x, {}).get("label") for x in hids) == [f"Player {n0 + k}" for k in (1, 2, 3)],
          "labelled Player N on the map", str([hh.get(x, {}).get("label") for x in hids]))
    check(v0 < st["plan_version"] <= v0 + 1, "the burst of joins costs one replan", f"v{v0} → v{st['plan_version']}")
    r = await c.post("/dev/inbound", json={"role": "resident", "handle": phones[3], "text": "JOIN EMBER"})
    check(r.status_code == 422, "a phone that never registered can't join by texting", f"{r.status_code}")
    if (await get("/health")).get("max_players") == n0 + 3:
        r = await c.post("/join", json={"handle": phones[3]})
        check(r.status_code == 409 and "full" in r.text and phones[3] not in {p_["handle"] for p_ in await get("/phones")},
              "a 4th POST /join over MAX_PLAYERS is refused with 409", f"{r.status_code} {r.text[:80]}")
    else:
        print(f"      cap check skipped: start the backend with MAX_PLAYERS={n0 + 3} on a fresh DB")

    await ev.stop()
    await c.aclose()
    failed = [r_ for r_ in results if not r_[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for _, what, detail in failed:
        print(f"  FAILED: {what}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--skip-optimize", action="store_true")
    ap.add_argument("--big", action="store_true", help="also /optimize on 10,000 worlds (seeds 2000)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.base, a.skip_optimize, a.big)))
