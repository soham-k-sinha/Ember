"""Six phone calls end to end, without ElevenLabs or an LLM (D80).

    cd residents && uv run python scripts/sim_calls.py [--out ../docs/voice_transcripts.md]

One run of allston_flood_v1 (its 40 scenario households plus six residents who text in), the real planner, the
keyword parser in place of the LLM (fallback.py), the sim clock moved 5 min at a time. EMBER's call manager decides
whom to call and why; the dial goes to a fake ElevenLabs (httpx.MockTransport) and every caller turn is posted to
the Custom-LLM endpoint, streamed, exactly as ElevenLabs posts it. Prints each call as a timed transcript (EMBER's
speech at 150 words a minute plus the measured reply time; the caller's pauses are scripted) and what it changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from residents import voice as voice_mod  # noqa: E402
from residents.app import create_app  # noqa: E402
from residents.config import Settings  # noqa: E402
from residents.engine_bridge import EngineBridge  # noqa: E402
from residents.voice import INBOUND, SYSTEM_PROMPT, create_voice_app  # noqa: E402

OURS = "+16175550199"  # the Photon voice number (placeholder)
TOKEN = "sim"
WPM = 150

# name, who they are, phone, where they text from (None: they call in), their texts, what they say on the call
PEOPLE = [
    ("Margaret", "84, uses a wheelchair, slow to answer", "+16175550111", "Flagg St and Memorial Dr",
     ["just me, I use a wheelchair"],
     [(4.0, "Hello?"), (3.0, "Who is this?"), (5.0, "Oh. Yes, yes please."), (4.0, "Thank you, dear.")]),
    ("Dev", "panics", "+16175550112", "Banks St and Flagg St", [],
     [(0.5, "Oh my god, is the water coming? What do I do?"), (1.0, "Okay. Okay. It's me and my two kids, three of us."),
      (0.8, "Yes. Yes, please hurry."), (1.5, "Okay, we're ready.")]),
    ("Rosa", "says she's fine, but the water reaches her street", "+16175550113", "Putnam Ave and Western Ave",
     ["2 of us"],
     [(1.5, "No, I'm fine, we're staying put."), (2.0, "We're on the second floor, we'll be okay."),
      (2.0, "Okay. Yes, send it.")]),
    ("Sam", "said yes by text, then the pickup changed", "+16175550114", "Callender St and Putnam Ave",
     ["just me", "yes"],
     [(1.0, "Oh, okay. What changed?"), (1.0, "Okay, got it.")]),
    ("Lee", "garbled and off-topic answers", "+16175550115", "Hingham St and Putnam Ave", [],
     [(2.0, "Sorry, what? The dog is going crazy here."), (2.0, "Uh, the purple one, by the window."),
      (1.5, "Two of us."), (1.0, "Yes.")]),
    ("Jordan", "calls in with questions", "+16175550116", None, [],
     [(1.0, "I got a flood alert. What's going on?"), (1.0, "Memorial Drive and River Street."),
      (1.0, "Where would you take us?"), (1.0, "Just me and my cat."), (1.0, "Can I bring my cat?"), (1.0, "Yes."),
      (1.0, "Thanks, bye.")]),
]
FLOODED = "Callender St"  # a neighbour reports it flooded at 0:05: Sam's van has to go around
HEADER = """# EMBER on the phone: simulated calls

Written by `residents/scripts/sim_calls.py` (D80). One run of the Allston flood drill: the real planner and its
40 scenario households, six residents who text in, the sim clock moved 5 minutes at a time. EMBER decides on its own
whom to call and why (no reply while the water is close, a wheelchair or medical need not yet confirmed, a pickup
that changed), most at-risk first, at most two calls at once. Every caller turn goes through the same endpoint
ElevenLabs uses; every instruction EMBER says is the one its texts would say, rendered for speech. **Synthetic:** the six
people and their words, the flood timing, the fleet. The keyword parser stands in for the LLM, so no model is in these
calls. Times: EMBER speaks at 150 words a minute; "ms" is how long EMBER took to answer (a replan when needs change).
"""


async def no_llm(system, user):
    raise RuntimeError("no LLM in this simulation: the keyword parser reads every reply")


def secs(text: str) -> float:
    return len(text.split()) * 60 / WPM


def clock(t_s: float) -> str:
    return f"{int(t_s // 3600)}:{int(t_s % 3600 // 60):02d}"


class Sim:
    def __init__(self, bridge: EngineBridge, db: Path):
        settings = replace(Settings(), db_path=db, reset_on_start=True, photon_enabled=False, extract_enabled=True,
                           reply_enabled=False, geocode_enabled=False, auto_clock=False, start_t_s=0.0,
                           photon_voice_number=OURS, elevenlabs_api_key="sim", elevenlabs_agent_id="agent",
                           elevenlabs_phone_number_id="phone", voice_max_concurrent=2)
        self.app = create_app(settings, bridge=bridge, llm=no_llm)
        self.vapp = create_voice_app(lambda: self.app.state.voice, TOKEN)
        self.dials: list[dict] = []
        self.status: dict[str, str] = {}  # conversation id → what the fake ElevenLabs reports
        self.out: list[str] = []

    def eleven(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/outbound-call"):
            conv = f"conv_{len(self.status) + 1}"
            self.dials.append({"conv": conv, **json.loads(req.content)})
            self.status[conv] = "in-progress"
            return httpx.Response(200, json={"success": True, "conversation_id": conv, "sip_call_id": "sip"})
        return httpx.Response(200, json={"status": self.status.get(req.url.path.rsplit("/", 1)[-1], "in-progress")})

    def print(self, line: str = "") -> None:
        print(line, flush=True)
        self.out.append(line)

    def person(self, handle: str) -> tuple:
        return next(p for p in PEOPLE if p[2] == handle)

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

    async def turn(self, handle: str, conv: str, words: str, outbound: bool) -> tuple[str, float]:
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

    async def converse(self, handle: str, conv: str, opening: str, reason: str) -> None:
        st = self.app.state
        name, who, *_, lines = self.person(handle)
        outbound = reason != "inbound"
        self.print(f"\n### {name} ({who}): {'EMBER calls, ' + reason.replace('_', ' ') if outbound else 'calls EMBER'}, "
                   f"sim {clock(st.planner.now())}")
        self.print(f"Before: {self.pickup(handle)}\n")
        t = 0.0
        self.print(f"- `{t:5.1f}s` **EMBER** ({secs(opening):.1f} s): {opening}")
        t += secs(opening)
        for pause, words in lines:
            t += pause
            self.print(f"- `{t:5.1f}s` *{name}*: {words}")
            t += secs(words)
            said, took = await self.turn(handle, conv, words, outbound)
            if said:
                t += took
                self.print(f"- `{t:5.1f}s` **EMBER** ({took * 1000:.0f} ms, {secs(said):.1f} s): {said}")
                t += secs(said)
        self.status[conv] = "done"  # they hang up: ElevenLabs reports the conversation done
        hid = st.voice._household_id(handle)
        n = len(st.store.thread_messages(f"household:{hid}"))
        await st.voice.reap()
        for m in st.store.thread_messages(f"household:{hid}")[n:]:
            self.print(f"- after the call, by text: {m['text']}")
        rec = st.voice.recent[-1]
        self.print(f"\nOutcome: **{rec['outcome']}**, {rec['turns']} turns in {t:.0f} s. After: {self.pickup(handle)}")

    async def calls_due(self) -> None:
        """The calls EMBER placed since we last looked, talked through one after another."""
        while self.dials:
            d = self.dials.pop(0)
            await self.converse(d["to_number"], d["conv"], d["conversation_initiation_client_data"]["dynamic_variables"]
                                ["opening"], self.app.state.voice.sessions[d["to_number"]].reason)

    async def run(self) -> None:
        st = self.app.state
        voice_mod.REAP_EVERY_S = 0.0
        st.voice.http = httpx.AsyncClient(transport=httpx.MockTransport(self.eleven))
        for _, _, handle, where, texts, _ in PEOPLE:
            if where is not None:
                await st.messenger.register_phone("resident", handle, locate=True)
                for words in [where, *texts]:
                    await st.messenger.phone_inbound(handle, words)
        for t in range(5, 125, 5):
            await st.planner.set_clock(t * 60.0)
            await self.calls_due()
            if t == 5:
                self.print(f"\n_sim {clock(t * 60)}: a neighbour reports {FLOODED} flooded; EMBER replans._")
                sam = PEOPLE[3][2]
                await st.planner.close_road(st.planner.bridge.resolve_road(FLOODED, None, st.voice._household_id(sam)),
                                            source="resident", note=f"{FLOODED} is flooded")
                await self.calls_due()
            if t == 60:
                jordan = PEOPLE[5][2]
                self.status["in_1"] = "in-progress"
                await self.converse(jordan, "in_1", INBOUND, "inbound")
                await self.calls_due()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="also write the transcripts here (Markdown)")
    args = ap.parse_args()
    bridge = EngineBridge(Settings().scenario)
    with tempfile.TemporaryDirectory() as tmp:
        sim = Sim(bridge, Path(tmp) / "sim.db")
        logging.disable(logging.ERROR)  # the keyword parser stands in for the LLM: no outage errors
        async with sim.app.router.lifespan_context(sim.app):
            await sim.run()
    if args.out:
        args.out.write_text(HEADER + "\n".join(sim.out) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
