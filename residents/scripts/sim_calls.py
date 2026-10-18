"""Calls first (D99), end to end, without ElevenLabs, Photon or an LLM.

    cd residents && uv run python scripts/sim_calls.py [--out ../docs/voice_transcripts.md]

One run of allston_flood_v1 (its 40 scenario households plus five players), the real planner, the keyword parser in
place of the LLM (fallback.py), the sim clock moved a minute at a time. EMBER's call manager decides whom to call and
when (VOICE_MAX_CONCURRENT=3); the dial goes to a fake ElevenLabs (httpx.MockTransport) and every caller turn is posted
to the Custom-LLM endpoint, streamed, exactly as ElevenLabs posts it, re-sent and revised turns included (as seen live
on 2026-10-18). Prints each call as a timed transcript (EMBER's speech at 150 words a minute plus the measured reply
time; the caller's pauses are scripted) and each phone's text thread.

Who: three players join at once (Maria: wheelchair and oxygen; Dev: the live call's re-sent turns; Sam: busy, never says
yes or done), Lee joins while every line is busy and never picks up, Jordan calls the number and joins by voice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["EMBER_LOCAL_POOL"] = "1"  # never Daytona from the simulation

from residents import voice as voice_mod  # noqa: E402
from residents.app import create_app  # noqa: E402
from residents.config import Settings  # noqa: E402
from residents.engine_bridge import EngineBridge  # noqa: E402
from residents.voice import INBOUND, SYSTEM_PROMPT, create_voice_app  # noqa: E402

OURS = "+16175550199"  # the Photon voice number (placeholder)
TOKEN = "sim"
WPM = 150


@dataclass
class Person:
    name: str
    who: str
    handle: str
    calls: dict = field(default_factory=dict)   # call reason → [(pause s, words)], None: doesn't pick up
    texts: dict = field(default_factory=dict)   # what they text back after a missed call: {"missed": words}


MARIA = Person("Maria", "74, her mother uses a wheelchair and oxygen", "+16175550111", {
    "first_contact": [(3.0, "Hello?"), (2.0, "It's me and my mother. She's in a wheelchair and she needs her oxygen."),
                      (2.0, "Okay. Thank you.")],
    "pickup_changed": [(2.0, "Oh. Okay, thank you.")],
    "soon": [(2.0, "Thank you, dear.")]})
DEV = Person("Dev", "the live call's turns, re-sent and revised the way ElevenLabs posted them", "+16175550112", {
    "first_contact": [(1.0, "Um, there are four of us, and one needs a wheelchair."),
                      (2.0, "A walker."), (0.5, "A walker. I need my ankle."), (0.5, "A walker. I need my needle."),
                      (2.0, "I'm done."), (0.5, "I'm done. Okay, done."), (0.5, "A walker. I need my needle."),
                      (0.5, "I'm done."), (0.5, "I'm done.")],
    "soon": [(1.0, "Okay, bye.")]})
SAM = Person("Sam", "busy, never says yes or done", "+16175550113", {
    "first_contact": [(1.5, "Two.")],
    "soon": [(1.0, "Got it, bye.")]})
LEE = Person("Lee", "joins while every line is busy, never picks up", "+16175550114",
             {"first_contact": None, "soon": None}, {"missed": "2 of us"})
JORDAN = Person("Jordan", "calls the number, joins by voice", "+16175550115", {
    "inbound": [(1.0, "Hi, I saw the flood sign. Can I join?"), (1.5, "Just me."), (1.0, "Thanks, bye.")],
    "soon": [(1.0, "Okay, bye.")]})
PEOPLE = [MARIA, DEV, SAM, LEE, JORDAN]
HEADER = """# EMBER on the phone: calls first (simulated)

Written by `residents/scripts/sim_calls.py` (D99): the real planner on the Allston flood (40 scenario households plus
the players), the clock moved a minute at a time. A player who joins is called right away; EMBER calls again for the
pickup that changed and "2 minutes away"; everything else goes out as one short text after the call, on the plan's
clock, with no YES or DONE needed. At most 3 calls at once, earliest flood deadline first; a missed call is tried once
more 2 sim-min later, then texted. **Synthetic:** the people, their words, the flood timing, the fleet. No model: the
keyword parser reads every reply. Speech at 150 words a minute; "ms" is EMBER's reply time (a replan when needs change).
"""


def secs(text: str) -> float:
    return len(text.split()) * 60 / WPM


def clock(t_s: float) -> str:
    return f"{int(t_s // 3600)}:{int(t_s % 3600 // 60):02d}"


class Sim:
    def __init__(self, bridge: EngineBridge, db: Path):
        settings = replace(Settings(), db_path=db, reset_on_start=True, photon_enabled=False, extract_enabled=False,
                           anthropic_api_key="", chalk_router_key="", photon_api_key="",
                           reply_enabled=False, geocode_enabled=False, auto_clock=False, start_t_s=0.0,
                           photon_voice_number=OURS, elevenlabs_api_key="sim", elevenlabs_agent_id="agent",
                           elevenlabs_phone_number_id="phone", voice_max_concurrent=3, voice_poll_s=0.0)
        self.app = create_app(settings, bridge=bridge)  # no model: the keyword parser
        self.vapp = create_voice_app(lambda: self.app.state.voice, TOKEN)
        self.dials: list[dict] = []
        self.status: dict[str, str] = {}  # conversation id → what the fake ElevenLabs reports
        self.sections: dict[str, list[str]] = {}  # name → its lines (calls), "texts:<name>" → its text thread
        self.out: list[str] = []
        self.texts: dict[str, list[str]] = {p.handle: [] for p in PEOPLE}
        self.tried: dict[str, int] = {}

    # ---------- the fake ElevenLabs and the record ----------
    def eleven(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/outbound-call"):
            conv = f"conv_{len(self.status) + 1}"
            body = json.loads(req.content)
            self.dials.append({"conv": conv, "to": body["to_number"],
                               "first": body["conversation_initiation_client_data"]["dynamic_variables"]["opening"]})
            self.status[conv] = "in-progress"
            return httpx.Response(200, json={"success": True, "conversation_id": conv, "sip_call_id": "sip"})
        return httpx.Response(200, json={"status": self.status.get(req.url.path.rsplit("/", 1)[-1], "in-progress")})

    def on_message(self, ev: dict) -> None:
        if ev["direction"] != "out" or ev["delivery"] == "voice":
            return
        who = ev["who"]
        if not isinstance(who, str):
            from residents.threads import phone_for_thread
            p = phone_for_thread(self.app.state.store, who)
            who = p["handle"] if p else None
        if who in self.texts:
            self.texts[who].append(f"- `{clock(self.now())}` {ev['text']}")

    def now(self) -> float:
        return self.app.state.planner.now()

    def print(self, line: str = "", section: str | None = None) -> None:
        print(line, flush=True)
        self.out.append(line)
        if section is not None:
            self.sections.setdefault(section, []).append(line)

    def person(self, handle: str) -> Person:
        return next(p for p in PEOPLE if p.handle == handle)

    def pickup(self, handle: str) -> str:
        """Their household in the current plan: needs, vehicle, status and pickup time (computed fields)."""
        st = self.app.state
        hid = st.voice._household_id(handle)
        if hid is None:
            return "not placed yet"
        plan = st.store.current_plan()
        a = min((x for x in plan["assignments"] if x["target"].get("household_id") == hid
                 and x["status"] not in ("cancelled", "rejected", "done")), key=lambda x: x["eta_s"], default=None)
        h = next(x for x in st.store.households() if x["household_id"] == hid)
        needs = ", ".join(f"{k}={v}" for k, v in (h["needs"] if isinstance(h["needs"], dict) else {}).items() if v)
        deadline = f", out by {clock(h['deadline_s'])}" if h.get("deadline_s") is not None else ""
        if a is None:
            return f"plan v{plan['version']}: needs {needs or 'unknown'}{deadline}; no vehicle"
        names = {r["id"]: r["name"] for r in st.store.snapshot()["resources"]}
        return (f"plan v{plan['version']}: needs {needs or 'unknown'}{deadline}; {names[a['resource_id']]} "
                f"{a['status']}, pickup at {clock(a['eta_s'])}")

    # ---------- a call ----------
    async def post(self, handle: str, conv: str, words: str, outbound: bool) -> tuple[str, float]:
        """One caller turn through the Custom-LLM endpoint, streamed, as ElevenLabs posts it."""
        caller, called = (OURS, handle) if outbound else (handle, OURS)
        system = (SYSTEM_PROMPT.replace("{{system__caller_id}}", caller).replace("{{system__called_number}}", called)
                  .replace("{{system__conversation_id}}", conv))
        body = {"model": "ember", "stream": True,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": words}]}
        t0 = time.perf_counter()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.vapp), base_url="http://voice") as c:
            r = await c.post(f"/{TOKEN}/v1/chat/completions", json=body)
        chunks = [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: {")]
        return "".join(ch["choices"][0]["delta"].get("content", "") for ch in chunks), time.perf_counter() - t0

    def inbound_count(self, handle: str) -> int:
        hid = self.app.state.voice._household_id(handle)
        return sum(m["direction"] == "in" for m in self.app.state.store.thread_messages(f"household:{hid}")) if hid else 0

    async def converse(self, p: Person, conv: str, opening: str, reason: str) -> None:
        st = self.app.state
        outbound = reason != "inbound"
        sec = f"{p.name}:{reason}"
        what = {"first_contact": "first contact", "soon": "2 minutes away", "pickup_changed": "pickup changed",
                "instruction": "the pickup"}.get(reason, reason)
        self.print(f"\n### {p.name} ({p.who}): {'EMBER calls, ' + what if outbound else 'calls EMBER'}, sim {clock(self.now())}",
                   sec)
        self.print(f"Before: {self.pickup(p.handle)}\n", sec)
        t = 0.0
        self.print(f"- `{t:5.1f}s` **EMBER** ({secs(opening):.1f} s): {opening}", sec)
        t += secs(opening)
        v = st.voice
        for pause, words in p.calls[reason]:
            t += pause
            s = v.sessions.get(p.handle)
            kind, _ = v._boundary(s, voice_mod._words(words), time.monotonic()) if s else (None, None)
            n = self.inbound_count(p.handle)
            note = {"repeat": " _(re-sent)_", "revision": " _(revised)_"}.get(kind, "")
            self.print(f"- `{t:5.1f}s` *{p.name}*: {words}{note}", sec)
            t += secs(words)
            said, took = await self.post(p.handle, conv, words, outbound)
            if kind == "repeat":
                assert self.inbound_count(p.handle) == n
                self.print(f"- `{t:5.1f}s` **EMBER** ({took * 1000:.0f} ms): the same reply again, not processed again", sec)
            elif said:
                t += took
                self.print(f"- `{t:5.1f}s` **EMBER** ({took * 1000:.0f} ms, {secs(said):.1f} s): {said}", sec)
                t += secs(said)
        self.status[conv] = "done"  # they hang up: ElevenLabs reports the conversation done
        n = len(self.texts[p.handle])
        await v.check()
        for line in self.texts[p.handle][n:]:
            self.print(f"- after the call, by text: {line.split('` ', 1)[1]}", sec)
        rec = v.recent[-1]
        self.print(f"\nOutcome: **{rec['outcome']}**, {rec['turns']} turns in {t:.0f} s. After: {self.pickup(p.handle)}", sec)

    async def missed(self, p: Person, conv: str, opening: str, reason: str) -> None:
        self.tried[p.handle] = self.tried.get(p.handle, 0) + 1
        self.print(f"\n_sim {clock(self.now())}: EMBER calls {p.name} ({reason.replace('_', ' ')}, try "
                   f"{self.tried[p.handle]}): \"{opening}\" No answer._")
        self.status[conv] = "done"
        n = len(self.texts[p.handle])
        await self.app.state.voice.check()
        new = self.texts[p.handle][n:]
        self.print(f"_{'Texted: ' + new[-1].split('` ', 1)[1] if new else 'A retry is due in 2 sim-min.'}_")
        if new and p.texts.get("missed") and reason == "first_contact":
            self.print(f"_{p.name} texts back: \"{p.texts['missed']}\"_")
            await self.app.state.messenger.phone_inbound(p.handle, p.texts["missed"])

    async def calls_due(self) -> None:
        """The calls EMBER placed since we last looked, answered (or not) one after another."""
        while self.dials:
            d = self.dials.pop(0)
            p = self.person(d["to"])
            reason = self.app.state.voice.sessions[d["to"]].reason
            if p.calls.get(reason) is None:
                await self.missed(p, d["conv"], d["first"], reason)
            else:
                await self.converse(p, d["conv"], d["first"], reason)

    # ---------- the run ----------
    async def join(self, people: list[Person]) -> None:
        """POST /join, then each texts JOIN EMBER at the same moment (D89); one replan for the burst."""
        st = self.app.state
        for p in people:
            await st.messenger.register_player(p.handle)
        await asyncio.gather(*(st.messenger.phone_inbound(p.handle, "JOIN EMBER") for p in people))
        if st.locator.replan_task is not None:
            await st.locator.replan_task

    async def run(self) -> None:
        st = self.app.state
        voice_mod.REAP_EVERY_S = 0.0
        voice_mod.RETRY_WALL_S = 1e9  # only the sim clock decides when a missed call is tried again
        st.voice.http = httpx.AsyncClient(transport=httpx.MockTransport(self.eleven))
        st.messenger.taps.append(self.on_message)
        await self.join([MARIA, DEV, SAM])
        self.print(f"\n_sim 0:00: Maria, Dev and Sam join at once; EMBER dials all three (3 lines): "
                   f"{', '.join(self.person(d['to']).name for d in self.dials)}._")
        first, self.dials = self.dials, []
        await self.join([LEE])
        queued = [s.handle for s in st.voice.sessions.values() if not s.dialed]
        self.print(f"_sim 0:00: Lee joins; every line is busy, so Lee's call waits in the queue "
                   f"({', '.join(self.person(h).name for h in queued)})._")
        self.dials = first + self.dials
        await self.calls_due()
        for minute in range(1, 121):
            await st.planner.set_clock(minute * 60.0)
            await self.calls_due()
            if minute == 4:
                self.status["in_1"] = "in-progress"
                await self.converse(JORDAN, "in_1", INBOUND, "inbound")
                await self.calls_due()
            if all((g := st.guide.state(f"household:{st.voice._household_id(p.handle)}")) and g["finished"] for p in PEOPLE):
                self.print(f"\n_sim {clock(self.now())}: everyone is checked in at the shelter._")
                break
        for p in PEOPLE:
            self.print(f"\n### {p.name}'s texts", f"texts:{p.name}")
            for line in self.texts[p.handle]:
                self.print(line, f"texts:{p.name}")

    def doc(self) -> str:
        """The short version for docs/voice_transcripts.md: three calls and one text thread."""
        keep = ["Maria:first_contact", "Dev:first_contact", "Jordan:inbound", "texts:Lee"]
        return HEADER + "\n".join(line for k in keep for line in self.sections.get(k, [])) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="also write three calls and one text thread here (Markdown)")
    args = ap.parse_args()
    bridge = EngineBridge(Settings().scenario)
    with tempfile.TemporaryDirectory() as tmp:
        sim = Sim(bridge, Path(tmp) / "sim.db")
        logging.disable(logging.ERROR)  # the transcript only
        async with sim.app.router.lifespan_context(sim.app):
            await sim.run()
    if args.out:
        args.out.write_text(sim.doc())


if __name__ == "__main__":
    asyncio.run(main())
