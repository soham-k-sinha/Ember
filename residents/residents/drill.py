"""A whole run in one process, by calls and texts: `uv run ember-drill` (from residents/).

    uv run ember-drill --resident 6175550101                       # your phone is a resident (Photon on)
    uv run ember-drill --resident 6175550101 --resident 6175550102 --operator 6175550103@mt-auburn
    uv run ember-drill --dry                                       # no phones: type the residents' texts here
    uv run ember-drill --crowded ...                               # + the scenario's 40 synthetic households

It starts the backend (planner + Photon listener + the HTTP/WS API on :8000, so the web map can watch),
starts the run from scratch (unless --keep), registers the phones, and prints every text and call turn.
Residents say where they are and answer EMBER's one question; the pickup instruction and every later step come by
themselves (D100: nobody has to say YES or DONE). The sim clock moves with `next` / `+N` (or the web's playback), and
each step goes out when the clock reaches it. Console commands: `help`.
Phones also come from residents/.env: DRILL_RESIDENTS=6175550101,6175550102 and
DRILL_OPERATORS=6175550103@mt-auburn (keep real numbers out of git).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
  call r1               phone r1 now (ElevenLabs via the Photon number; with --dry: a pretend call, type
                        what they say with @r1 …)
  calls                 calls placed this run and the ones in progress
  questions             questions the plan couldn't answer (each already got the person's situation)
  tell r1 <text>        reply to r1 as the coordinator (texted as written)
  reset                 start over from scratch (everyone texts their location again)
  help | quit"""


class SetupError(Exception):
    """Why the drill can't start; printed as one line (no traceback)."""


def _fmt_t(t_s: float) -> str:
    return f"t={t_s / 60:5.1f} min"


class Drill:
    def __init__(self, args: argparse.Namespace):
        for name, default in (("caller", []), ("voice", False)):  # options added later (D74)
            if not hasattr(args, name):
                setattr(args, name, default)
        self.args = args
        self.names: dict[str, str] = {}   # handle → r1 / op1
        self.app = None
        self.server = None
        self.callers: dict[str, str | None] = {}   # handle → their address (None: the call asks where they are)
        self.tunnel = None
        self.voice_server = None

    # ---------- setup ----------
    def settings(self) -> Settings:
        s = Settings()
        return replace(s, db_path=Path(self.args.db), reset_on_start=not self.args.keep,
                       photon_enabled=not self.args.dry, drill_solo=not self.args.crowded,
                       auto_clock=True, dev_endpoints=True, start_t_s=0.0,
                       elevenlabs_api_key="" if self.args.dry else s.elevenlabs_api_key)  # --dry never dials

    def check(self, s: Settings) -> list[str]:
        problems = []
        problems += preflight(self.args.port, s.photon_enabled)
        if not s.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is not set in residents/.env: EMBER can't read texts without it.")
        if s.photon_enabled and not (s.photon_api_key and s.photon_project_id):
            problems.append("PHOTON_API_KEY / PHOTON_PROJECT_ID missing in residents/.env (or run with --dry).")
        if (self.args.caller or self.args.voice) and not self.args.dry and not (
                s.elevenlabs_api_key and s.elevenlabs_agent_id and s.elevenlabs_phone_number_id):
            problems.append("Calls need ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID and ELEVENLABS_PHONE_NUMBER_ID in "
                            "residents/.env (or run with --dry for pretend calls).")
        if not (self.args.resident or self.args.operator or self.args.caller or self.args.voice):  # --voice: they call in
            problems.append("No phones: pass --resident PHONE (repeatable) and/or --operator PHONE@facility_id, "
                            "or set DRILL_RESIDENTS / DRILL_OPERATORS in residents/.env.")
        return problems

    async def start(self) -> None:
        import uvicorn

        from .app import create_app
        s = self.settings()
        problems = self.check(s)
        if problems:
            raise SetupError("\n".join(problems))
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
                raise SetupError(f"backend didn't start (is port {self.args.port} in use?)")
            await asyncio.sleep(0.1)
        st = self.app.state
        st.messenger.taps.append(self.on_message)
        if st.intake is not None:
            st.intake.escalation_hooks.append(self.on_question)
        await self.register()
        await st.locator.welcome()
        if self.args.voice or self.args.caller:
            await self.start_voice()
        if self.callers:
            await self.dial_callers()

    # ---------- calls (D74) ----------
    async def start_voice(self) -> None:
        """The voice app (ElevenLabs' Custom LLM) on its own port, a cloudflared tunnel to it, and the agent
        pointed at the tunnel. With --dry: only the local app (pretend calls need none of it)."""
        import secrets

        import uvicorn

        from .voice import configure_agent, create_voice_app, start_tunnel, wait_for_voice
        s = self.app.state.settings
        self._voice_token = token = secrets.token_urlsafe(24)
        vapp = create_voice_app(lambda: self.app.state.voice, token)
        self.voice_server = uvicorn.Server(uvicorn.Config(vapp, host="127.0.0.1", port=s.voice_port, log_level="warning"))
        self.voice_server.install_signal_handlers = lambda: None
        self._voice_serve = asyncio.create_task(self.voice_server.serve())
        while not self.voice_server.started:
            if self._voice_serve.done():
                raise SetupError(f"voice app didn't start (is port {s.voice_port} in use? set VOICE_PORT)")
            await asyncio.sleep(0.1)
        if self.args.dry:
            print("\nvoice: pretend calls (--dry). `call r1` starts one; type what they say with @r1 …")
            return
        self.tunnel, public = await start_tunnel(s.voice_port)
        if not await wait_for_voice(f"{public}/{token}/health"):
            raise SetupError("The public voice callback isn't reachable yet; no calls were placed. Try starting the voice session again.")
        server_url = f"{public}/{token}/v1"
        ok, detail = await configure_agent(s, server_url)
        print(f"\nvoice: tunnel {public} → :{s.voice_port} (only the voice endpoint is exposed)")
        if ok:
            print("voice: ElevenLabs agent now uses EMBER as its Custom LLM (calls in and out go through the plan)")
        else:
            print(f"voice: couldn't update the ElevenLabs agent automatically ({detail}). In ElevenLabs → Agents → "
                  f"EMBER → LLM → Custom LLM, set:\n  Server URL: {server_url}\n  Model ID: ember\n"
                  f"  and the system prompt to exactly:\n  EMBER-CALL caller={{{{system__caller_id}}}} "
                  f"called={{{{system__called_number}}}} conv={{{{system__conversation_id}}}}\n  then Publish.")
        if s.photon_voice_number:
            print(f"voice: residents can call {s.photon_voice_number}")

    async def dial_callers(self) -> None:
        """Callers with an address are placed there; only the ones the forecast flood reaches are called
        (the critical area). Callers without an address are called and asked where they are."""
        st = self.app.state
        for handle, address in self.callers.items():
            name = self.names.get(handle, handle)
            if address:
                where, _, cross = address.partition(" and ")
                found = await st.locator.places.locate(where.strip(), cross.strip() or None, st.locator.geocoder)
                if not hasattr(found, "lon"):
                    print(f"  {name}: couldn't place {address!r} in the area; not called")
                    continue
                st.voice.open(handle)  # what placing them would text goes into the call instead
                self._quiet = True     # (and isn't printed: the call opens with the situation below)
                try:
                    thread = await st.locator.place(st.store.phone(handle=handle), found)
                finally:
                    self._quiet = False
                st.voice.sessions[handle].outbox.clear()
                if thread is None:
                    st.voice.end(handle, reason="not placed")
                    print(f"  {name}: couldn't match {address!r} to a building; not called")
                    continue
                h = next((x for x in st.store.households() if x["household_id"] == thread["household_id"]), {})
                if h.get("deadline_s") is None:
                    st.voice.end(handle, reason="outside the flood")
                    print(f"  {name} at {found.label}: outside the forecast flood, so not called")
                    continue
                await self.call(name, "first_contact")  # where they are, when the water comes, the one question
                continue
            await self.call(name)

    async def call(self, name: str, reason: str = "console") -> None:
        st = self.app.state
        handle = next((h for h, n in self.names.items() if n == name), None)
        if handle is None:
            print(f"usage: call r1  (participants: {', '.join(self.names.values())})")
            return
        if self.args.dry:
            print(f"\n[pretend call to {name}] EMBER: {await st.voice.opening(handle, reason)}")
            st.voice.sessions[handle].outbox.clear()
            return
        try:
            rec = await st.voice.call(handle, reason=reason)
            print(f"calling {name} … (conversation {rec.get('conversation_id')})")
        except (RuntimeError, ValueError) as e:
            print(f"call to {name} failed: {e}")

    def wanted(self) -> list[tuple[str, str, str | None]]:
        """(handle, role, facility_id) for every phone on the command line, in order."""
        from .threads import normalize_handle
        out = [(normalize_handle(raw), "resident", None) for raw in self.args.resident]
        for spec in self.args.caller:
            raw, _, address = spec.partition("=")
            self.callers[normalize_handle(raw)] = address.strip() or None
            out.append((normalize_handle(raw), "resident", None))
        for spec in self.args.operator:
            raw, _, fid = spec.partition("@")
            out.append((normalize_handle(raw), "operator", fid or None))
        handles = [h for h, *_ in out]
        dupes = sorted({h for h in handles if handles.count(h) > 1})
        if dupes:
            raise SetupError(f"Each phone can play one part per run; listed more than once: {', '.join(dupes)}")
        return out

    def fit_phones(self, wanted: list[tuple[str, str, str | None]]) -> None:
        """Fresh run: the command line decides who plays what. Phones from earlier runs that aren't listed are
        dropped (they get nothing); listed phones in a different part are re-bound, keeping their Photon opt-in."""
        from .db import thread_key
        from .threads import resolve_thread
        store = self.app.state.store
        scenario = store.meta().get("scenario_id")
        want = {h: (role, fid) for h, role, fid in wanted}
        for p in store.phones():
            if p["handle"] not in want:
                store.delete_phone(p["handle"])
        for p in store.phones():
            role, fid = want[p["handle"]]
            if role == "resident":
                key = None
            else:
                t = resolve_thread(store, "operator", facility_id=fid)
                key = thread_key(t) if t else None
            if (p["role"], p["thread_key"]) != (role, key):
                store.rebind_phone(p["handle"], role, None, scenario)  # free its old target first
        for p in store.phones():
            role, fid = want[p["handle"]]
            if role == "operator":
                t = resolve_thread(store, "operator", facility_id=fid)
                store.rebind_phone(p["handle"], role, thread_key(t) if t else None, scenario)

    async def register(self) -> None:
        from .db import PhoneConflict
        st = self.app.state
        wanted = self.wanted()
        try:
            if not self.args.keep:
                self.fit_phones(wanted)
            rows = []
            n = {"resident": 0, "operator": 0}
            for handle, role, fid in wanted:
                n[role] += 1
                name = f"r{n[role]}" if role == "resident" else f"op{n[role]}"
                if role == "resident":
                    p = await st.messenger.register_phone("resident", handle, locate=True)
                else:
                    p = await st.messenger.register_phone("operator", handle, facility_id=fid)
                self.names[p["handle"]] = name
                rows.append((name, "resident" if role == "resident" else f"operator of {p.get('facility_id')}", p))
        except (PhoneConflict, ValueError) as e:
            raise SetupError(f"Can't register the phones: {e}"
                             + (" (--keep continues the last run with its phones as they were)" if self.args.keep else "")) from e
        print("\nparticipants:")
        for name, role, p in rows:
            line = f"  {name:4} {role:28} {p['handle']}"
            if not self.args.dry:
                line += f"  → texts {p.get('assigned_number') or '?'}  ({'ready' if p['opted_in'] else 'must text first'})"
            print(line)
        if not self.args.dry and any(not p["opted_in"] for *_, p in rows):
            print("\nEach phone that isn't ready: text HI to its number above (Photon only lets EMBER reply"
                  " after you text first).")
        print("\nResidents: EMBER asks where you are and one question (how many, anyone hurt or in a wheelchair) → the "
              "pickup instruction and each step come by themselves (`next` moves the clock).\nOperators: tell EMBER your "
              "power status (e.g. 'on backup, about 40 minutes left').")
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
        text = ev["text"]
        if ev["direction"] == "in":
            print(f"\n[{t}] {name} → EMBER: {text}", flush=True)
        elif ev["delivery"] == "voice":
            if not self.args.dry and not getattr(self, "_quiet", False):  # (pretend calls print the spoken reply as one line)
                from .speech import render
                print(f"\n[{t}] EMBER (call) → {name}: {render(text)}", flush=True)
        else:
            flag = "" if ev["delivery"] in ("sent", "dev", None) else f"   (delivery: {ev['delivery']})"
            print(f"\n[{t}] EMBER → {name}: {text}{flag}", flush=True)

    def on_question(self, q: dict) -> None:
        name = self._who(q["thread"]) or "someone"
        print(f"   ↳ for the coordinator: {name} asked something the plan can't answer. Reply with: tell {name} <text>",
              flush=True)

    # ---------- commands ----------
    async def questions(self) -> None:
        items = sorted((json.loads(v) for v in self.app.state.store.kv_prefix("question:").values()), key=lambda q: q["t_s"])
        if not items:
            print("  no questions for the coordinator")
        for q in items:
            state = f"answered: {q['answer']['text']}" if q.get("answer") else "open"
            print(f"  [{_fmt_t(q['t_s'])}] {self._who(q['thread']) or q['thread']}: {q['text']}  ({state})")

    async def tell(self, name: str, text: str) -> None:
        """The coordinator's own reply. Marks that person's open questions answered."""
        st = self.app.state
        handle = next((h for h, n in self.names.items() if n == name), None)
        if handle is None or not text.strip():
            print(f"usage: tell r1 <text>  (participants: {', '.join(self.names.values())})")
            return
        from .threads import phone_thread
        thread = phone_thread(st.store, st.store.phone(handle=handle))
        if thread is None:
            await st.messenger.send_to_phone(handle, text)
            return
        msg, delivery = await st.messenger.send_message(thread, text, st.store.meta().get("plan_version"))
        if delivery in ("sent", "dev", "failed"):
            for k, v in st.store.kv_prefix("question:").items():
                q = json.loads(v)
                if q["thread"] == thread and not q.get("answer"):
                    st.store.kv_set(k, json.dumps({**q, "answer": {"text": text, "message_id": msg["id"]}}))

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
                         + (" (finished)" if g["finished"] else ""))
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
            elif line.startswith("call "):
                await self.call(line[5:].strip())
            elif line == "calls":
                calls = st.voice.calls_view()
                for c in calls["live"]:
                    print(f"  live: {self.names.get(c['handle'], c['handle'])} ({c['reason']}) · {c['turns']} turn(s)")
                for c in calls["recent"]:
                    print(f"  {self.names.get(c['handle'], c['handle'])} ({c['reason']}): {c['outcome']} · {c['turns']} turn(s)")
                if not calls["live"] and not calls["recent"]:
                    print("  no calls yet")
            elif line in ("questions", "qs"):
                await self.questions()
            elif line.startswith("tell "):
                name, _, text = line[len("tell "):].partition(" ")
                await self.tell(name, text)
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
                elif st.voice is not None and st.voice.live(handle) is not None:
                    from .speech import render_all
                    said = await st.voice.turn(handle, None, text)  # what a call does with their words
                    if self.args.dry:
                        print(f"[call] EMBER → {name}: {render_all(said) or '(nothing)'}")
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
        try:
            await self.start()
            await self.repl()
        finally:
            if self.tunnel is not None:
                self.tunnel.terminate()
            if self.voice_server is not None:
                self.voice_server.should_exit = True
            if self.server is not None and not self._serve.done():
                self.server.should_exit = True  # a clean shutdown (lifespan closes Photon + the DB)
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ember-drill", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resident", action="append", default=[], metavar="PHONE", help="a resident's phone (repeatable)")
    ap.add_argument("--operator", action="append", default=[], metavar="PHONE@FACILITY",
                    help="a facility operator, e.g. 6175550103@mt-auburn (repeatable)")
    ap.add_argument("--caller", action="append", default=[], metavar="PHONE[=ADDRESS]",
                    help="a resident EMBER calls (repeatable). With an address (\"Putnam Ave and Western Ave\") they're "
                         "placed there and called only if the forecast flood reaches it; without, the call asks where they are")
    ap.add_argument("--voice", action="store_true", help="take calls: the voice app + a cloudflared tunnel for ElevenLabs")
    ap.add_argument("--dry", action="store_true", help="no Photon: nothing is texted; type texts with @r1 …")
    ap.add_argument("--crowded", action="store_true",
                    help="also the scenario's 40 synthetic households, competing for the same vehicles (default: only the drill's people)")
    ap.add_argument("--keep", action="store_true", help="continue the last drill instead of starting from scratch")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=str(PKG_ROOT / "drill.db"), help="its own DB (default residents/drill.db)")
    args = ap.parse_args(argv)
    env = Settings()
    args.resident = args.resident or list(env.drill_residents)
    args.operator = args.operator or list(env.drill_operators)
    if args.dry and not args.resident and not args.operator and not args.caller:
        args.resident = ["+16175550101"]  # a pretend phone; type its texts with @r1
    setup_logging(Path(args.db).with_suffix(".log"))
    try:
        asyncio.run(Drill(args).run())
    except SetupError as e:
        raise SystemExit(str(e)) from None
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
