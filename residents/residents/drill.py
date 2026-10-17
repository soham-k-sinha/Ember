"""A whole drill in one process, driven by text messages: `uv run ember-drill` (from residents/).

    uv run ember-drill --resident 6175550101                       # your phone is a resident (Photon on)
    uv run ember-drill --resident 6175550101 --resident 6175550102 --operator 6175550103@mt-auburn
    uv run ember-drill --dry                                       # no phones: type the residents' texts here
    uv run ember-drill --crowded ...                               # + the scenario's 40 synthetic households

It starts the backend (planner + Photon listener + the HTTP/WS API on :8000, so the web map can watch),
starts the run from scratch (unless --keep), registers the phones, and prints every text in and out.
Residents text where they are, answer EMBER's questions, reply YES to an offer and DONE after each step.
The sim clock moves one step at a time: when everyone EMBER is waiting on has replied DONE, it jumps to
the next event (the vehicle arriving, the pickup, the drop-off). Console commands: `help`.
Phones also come from residents/.env: DRILL_RESIDENTS=6175550101,6175550102 and
DRILL_OPERATORS=6175550103@mt-auburn (keep real numbers out of git).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from .config import PKG_ROOT, Settings

HELP = """commands:
  status | s            who is where, what EMBER knows, their vehicle and step
  next | n              move the clock to the next step anyone has (else +5 min)
  +N                    move the clock N minutes forward (e.g. +10)
  @r1 <text>            text EMBER as r1 (any participant name; needed with --dry, works with phones too)
  close <street> and <cross street>   report that road closed at that corner (replans)
  plan                  the current plan's assignments for the participants
  reset                 start over from scratch (everyone texts their location again)
  help | quit"""


def _fmt_t(t_s: float) -> str:
    return f"t={t_s / 60:5.1f} min"


class Drill:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.names: dict[str, str] = {}   # handle → r1 / op1
        self.app = None
        self.server = None

    # ---------- setup ----------
    def settings(self) -> Settings:
        s = Settings()
        return replace(s, db_path=Path(self.args.db), reset_on_start=not self.args.keep,
                       photon_enabled=not self.args.dry, drill_solo=not self.args.crowded,
                       auto_clock=not self.args.manual_clock, dev_endpoints=True, start_t_s=0.0)

    def check(self, s: Settings) -> list[str]:
        problems = []
        problems += preflight(self.args.port, s.photon_enabled)
        if not s.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is not set in residents/.env: EMBER can't read texts without it.")
        if s.photon_enabled and not (s.photon_api_key and s.photon_project_id):
            problems.append("PHOTON_API_KEY / PHOTON_PROJECT_ID missing in residents/.env (or run with --dry).")
        if not self.args.resident and not self.args.operator:
            problems.append("No phones: pass --resident PHONE (repeatable) and/or --operator PHONE@facility_id, "
                            "or set DRILL_RESIDENTS / DRILL_OPERATORS in residents/.env.")
        return problems

    async def start(self) -> None:
        import uvicorn

        from .app import create_app
        s = self.settings()
        problems = self.check(s)
        if problems:
            raise SystemExit("\n".join(problems))
        self.app = create_app(s)
        cfg = uvicorn.Config(self.app, host="127.0.0.1", port=self.args.port, log_level="warning", lifespan="on")
        self.server = uvicorn.Server(cfg)
        self.server.install_signal_handlers = lambda: None  # Ctrl-C / `quit` are ours
        self._serve = asyncio.create_task(self.server.serve())
        print(f"starting EMBER ({'dry run, no texts sent' if self.args.dry else 'Photon on: real texts'}"
              f"{', with the scenario households' if self.args.crowded else ', only the drill participants need rescue'}) …",
              flush=True)
        while not self.server.started:
            if self._serve.done():
                raise SystemExit(f"backend didn't start (is port {self.args.port} in use?)")
            await asyncio.sleep(0.1)
        st = self.app.state
        st.messenger.taps.append(self.on_message)
        await self.register()
        await st.locator.welcome()

    async def register(self) -> None:
        st = self.app.state
        rows = []
        for i, raw in enumerate(self.args.resident, 1):
            p = await st.messenger.register_phone("resident", raw, locate=True)
            self.names[p["handle"]] = f"r{i}"
            rows.append((f"r{i}", "resident", p))
        for i, spec in enumerate(self.args.operator, 1):
            raw, _, fid = spec.partition("@")
            p = await st.messenger.register_phone("operator", raw, facility_id=fid or None)
            self.names[p["handle"]] = f"op{i}"
            rows.append((f"op{i}", f"operator of {p.get('facility_id')}", p))
        print("\nparticipants:")
        for name, role, p in rows:
            line = f"  {name:4} {role:28} {p['handle']}"
            if not self.args.dry:
                line += f"  → texts {p.get('assigned_number') or '?'}  ({'ready' if p['opted_in'] else 'must text first'})"
            print(line)
        if not self.args.dry and any(not p["opted_in"] for *_, p in rows):
            print("\nEach phone that isn't ready: text HI to its number above (Photon only lets EMBER reply"
                  " after you text first).")
        print("\nResidents: EMBER asks where you are → answer its questions → reply YES to the offer → "
              "reply DONE after each step.\nOperators: tell EMBER your power status (e.g. 'on backup, about "
              "40 minutes left').")
        corners = self.app.state.planner.bridge.flood_corners(4)
        if corners:
            print("To be evacuated, be somewhere the flood reaches (elsewhere EMBER says to shelter in place), e.g.:")
            for d, label in corners:
                print(f"  {label}   (pickup needed by {d / 60:.0f} min)")
        print(f"Map: http://localhost:5173 (web) · API: http://127.0.0.1:{self.args.port}/state\n")
        print(HELP + "\n", flush=True)

    # ---------- output ----------
    def _who(self, who) -> str | None:
        if isinstance(who, str):
            return self.names.get(who, who)
        from .threads import phone_for_thread
        p = phone_for_thread(self.app.state.store, who)
        return self.names.get(p["handle"]) if p else None

    def on_message(self, ev: dict) -> None:
        name = self._who(ev["who"])
        if name is None:
            return  # a household without a phone: the dashboard shows it
        t = _fmt_t(float(self.app.state.store.meta().get("t_s", 0.0)))
        text = ev["text"].removeprefix("[EMBER drill] ")
        if ev["direction"] == "in":
            print(f"\n[{t}] {name} → EMBER: {text}", flush=True)
        else:
            flag = "" if ev["delivery"] in ("sent", "dev", None) else f"   (delivery: {ev['delivery']})"
            print(f"\n[{t}] EMBER → {name}: {text}{flag}", flush=True)

    # ---------- commands ----------
    async def status(self) -> None:
        st = self.app.state
        store, guide = st.store, st.guide
        meta = store.meta()
        from .threads import phone_thread
        print(f"{_fmt_t(float(meta.get('t_s', 0)))} · plan v{meta.get('plan_version')}")
        view = store.plan_view() or {}
        res = {r["id"]: r for r in store.snapshot()["resources"]}
        for p in store.phones():
            name = self.names.get(p["handle"])
            if name is None:
                continue
            thread = phone_thread(store, p)
            ready = "ready" if st.messenger.opted_in(p) or self.args.dry else "hasn't texted yet"
            if thread is None:
                print(f"  {name}: not placed yet ({ready}); waiting for their location")
                continue
            line = f"  {name}: "
            if "household_id" in thread:
                h = next((x for x in store.households() if x["household_id"] == thread["household_id"]), {})
                loc = json.loads(store.kv_get(f"located:{p['handle']}") or "{}")
                line += (f"household #{thread['household_id']} at {loc.get('label', h.get('label'))} · needs "
                         f"{h.get('needs')} · {h.get('status')}"
                         + (f" · deadline {h['deadline_s'] / 60:.0f} min" if h.get("deadline_s") is not None else ""))
            else:
                f = next((x for x in store.facilities() if x["id"] == thread["facility_id"]), {})
                line += f"{f.get('name')} · {f.get('state')}"
            mine = [a for a in view.get("assignments", []) if a["target"] == thread and a["status"] not in ("cancelled",)]
            for a in mine:
                line += (f"\n      {res.get(a['resource_id'], {}).get('name', a['resource_id'])}: {a['status']}, "
                         f"ETA {a['eta_s'] / 60:.0f} min")
            g = guide.state(store_key(thread))
            if g:
                line += (f"\n      step {g['sent'] + 1} of {g['steps']}"
                         + (" (finished)" if g["finished"] else " · waiting for DONE" if guide.awaiting_done(thread) else ""))
            print(line)
        nxt = await guide.next_event_t()
        if nxt is not None:
            print(f"  next step at {_fmt_t(nxt)}")

    async def plan(self) -> None:
        store = self.app.state.store
        view = store.plan_view() or {}
        from .threads import phone_thread
        threads = [t for p in store.phones() if self.names.get(p["handle"]) and (t := phone_thread(store, p))]
        for a in view.get("assignments", []):
            if a["target"] in threads:
                print(f"  {a['id']}: {a['status']}, ETA {a['eta_s'] / 60:.0f} min · {a['rationale']}")
        for u in view.get("unresolved", []):
            if u["target"] in threads:
                print(f"  unresolved {u['target']}: {u['blocked_by']}")

    async def move_clock(self, t: float) -> None:
        planner = self.app.state.planner
        t = min(max(t, planner.now()), planner.bridge.t_end_s)
        await planner.set_clock(t)
        print(f"clock → {_fmt_t(t)}", flush=True)

    async def command(self, line: str) -> bool:
        st = self.app.state
        line = line.strip()
        if not line:
            return True
        if line in ("quit", "exit", "q"):
            return False
        try:
            if line in ("help", "h", "?"):
                print(HELP)
            elif line in ("status", "s"):
                await self.status()
            elif line == "plan":
                await self.plan()
            elif line in ("next", "n"):
                t = await st.guide.next_event_t()
                await self.move_clock(t if t is not None and t > st.planner.now() else st.planner.now() + 300)
            elif line.startswith("+"):
                await self.move_clock(st.planner.now() + float(line[1:]) * 60)
            elif line.startswith("@"):
                name, _, text = line[1:].partition(" ")
                handle = next((h for h, n in self.names.items() if n == name), None)
                if handle is None or not text.strip():
                    print(f"usage: @r1 <text>  (participants: {', '.join(self.names.values())})")
                else:
                    await st.messenger.phone_inbound(handle, text)
            elif line.startswith("close "):
                street, _, cross = line[len("close "):].partition(" and ")
                edges = st.planner.bridge.resolve_road(street.strip(), cross.strip() or None, None)
                if not edges:
                    print("couldn't place that on the map; use: close <street> and <cross street>")
                else:
                    await st.planner.close_road(edges, note=f"drill console: {line[6:]} closed")
                    print(f"closed {len(edges)} road segment(s); replanned → v{st.store.meta().get('plan_version')}")
            elif line == "reset":
                await st.planner.bootstrap(0.0)
                await st.locator.welcome()
                print("reset: plan v1 at t=0; every resident texts their location again")
            else:
                print("unknown command; `help`")
        except Exception as e:  # noqa: BLE001 - keep the console alive
            logging.getLogger("residents.drill").exception("command failed")
            print(f"error: {e}")
        return True

    async def repl(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, input, "drill> ")
            except EOFError:
                break
            if not await self.command(line):
                break

    async def run(self) -> None:
        await self.start()
        try:
            await self.repl()
        finally:
            self.server.should_exit = True
            await self._serve


def preflight(port: int, photon: bool) -> list[str]:
    """The port must be free, and no other EMBER backend may be listening to Photon (both would answer
    every text). Checks our port and the default 8000."""
    import socket

    import httpx
    problems = []
    for p in sorted({port, 8000}):
        try:
            health = httpx.get(f"http://127.0.0.1:{p}/health", timeout=1.0).json()
        except (httpx.HTTPError, ValueError):
            health = None
        if health and health.get("photon") == "enabled" and photon:
            problems.append(f"Another EMBER backend with Photon on is running on port {p}: stop it first (Ctrl-C in "
                            f"its terminal, or `kill $(lsof -t -iTCP:{p} -sTCP:LISTEN)`), or both will answer every text.")
        elif p == port:
            with socket.socket() as sock:
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError:
                    problems.append(f"Port {port} is in use{' by an EMBER backend' if health else ''}: stop it or pass --port.")
    return problems


def store_key(thread: dict) -> str:
    from .db import thread_key
    return thread_key(thread)


def _phones(env: str) -> list[str]:
    return [x.strip() for x in os.environ.get(env, "").split(",") if x.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ember-drill", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resident", action="append", default=[], metavar="PHONE", help="a resident's phone (repeatable)")
    ap.add_argument("--operator", action="append", default=[], metavar="PHONE@FACILITY",
                    help="a facility operator, e.g. 6175550103@mt-auburn (repeatable)")
    ap.add_argument("--dry", action="store_true", help="no Photon: nothing is texted; type texts with @r1 …")
    ap.add_argument("--crowded", action="store_true",
                    help="also the scenario's 40 synthetic households, competing for the same vehicles (default: only the drill's people)")
    ap.add_argument("--keep", action="store_true", help="continue the last drill instead of starting from scratch")
    ap.add_argument("--manual-clock", action="store_true", help="the clock moves only with next / +N")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=str(PKG_ROOT / "drill.db"), help="its own DB (default residents/drill.db)")
    args = ap.parse_args(argv)
    args.resident = args.resident or _phones("DRILL_RESIDENTS")
    args.operator = args.operator or _phones("DRILL_OPERATORS")
    if args.dry and not args.resident and not args.operator:
        args.resident = ["+16175550101"]  # a pretend phone; type its texts with @r1
    setup_logging(Path(args.db).with_suffix(".log"))
    try:
        asyncio.run(Drill(args).run())
    except KeyboardInterrupt:
        pass


def setup_logging(log_path: Path) -> None:
    """Our log goes to a file; the console shows the conversation (and errors)."""
    logging.basicConfig(level=logging.INFO, filename=log_path, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.ERROR)
    logging.getLogger().addHandler(console)
    print(f"log: {log_path}")
    try:
        import readline  # noqa: F401  (line editing + history in the console)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
