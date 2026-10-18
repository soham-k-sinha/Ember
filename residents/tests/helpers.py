"""Shared test helpers: phones, places, the scripted model and the app factories (conftest imports these too)."""
from dataclasses import replace

from fastapi.testclient import TestClient

from residents.app import create_app
from residents.config import REPO_ROOT
from residents.extract import Extraction, Fact, to_outcome
from residents.photon import parse_inbound

SCENARIO = REPO_ROOT / "scenarios" / "allston_flood_v1" / "scenario.json"
JUDGE = 10296
R1, R2 = "+16175550101", "+16175550102"
GREEN = "corner of Green St and Sellers St"           # outside the forecast flood: shelter in place
PUTNAM = "Putnam Ave and Western Ave"                   # the flood reaches it (pickup by 135 min)
CALLENDER = "Callender St and Putnam Ave"               # also in the flood
EVERETT = "Everett St and Western Ave"
NONE = dict(people=None, mobility=None, accessible_vehicle=None, medical=None, road_hint=None, cross_street=None, address=None,
            endurance_min=None, facility_state=None, question_topic=None)


def fact(kind, **kw):
    return Fact(kind=kind, **{**NONE, **kw})


def ex(*facts, confidence=0.9, q=None):
    return Extraction(facts=list(facts), confidence=confidence, clarifying_question=q)


def outcome(e, role="resident", thread=None, pending=None, roads=None, last_assignment=None):
    return to_outcome(e, role=role, thread=thread or {"household_id": JUDGE}, text="msg", pending=pending,
                      resolve_road=lambda h, c, hid: (roads or {}).get(h, []), last_assignment_id=last_assignment)


class FakeLLM:
    def __init__(self, script):
        self.script, self.prompts = script, []

    async def __call__(self, system, user):
        self.prompts.append(user)
        text = user.split("Message:\n", 1)[1]
        r = self.script[text]
        if isinstance(r, Exception):
            raise r
        return r


SCRIPT = {
    "hi": ex(fact("other")),
    GREEN: ex(fact("location", address="Green St", cross_street="Sellers St")),
    EVERETT: ex(fact("location", address="Everett St", cross_street="Western Ave")),
    PUTNAM: ex(fact("location", address="Putnam Ave", cross_street="Western Ave")),
    CALLENDER: ex(fact("location", address="Callender St", cross_street="Putnam Ave")),
    "125 Western Ave, my mom uses a wheelchair": ex(fact("location", address="125 Western Ave"),
                                                    fact("need", mobility=True, accessible_vehicle=True)),
    "somewhere in Ohio": ex(fact("location", address="somewhere in Ohio")),
    "42.0, -75.0": ex(fact("location", address="42.0, -75.0")),
    "2 of us": ex(fact("need", people=2)),
    "just me": ex(fact("need", people=1)),
    "me and my dad, he uses a wheelchair": ex(fact("need", people=2, mobility=True, accessible_vehicle=True)),
    "yes": ex(fact("confirm")),
    "we're at the corner now": ex(fact("done")),
    "done": ex(fact("done")),  # only reaches the model when no step is waiting on them
    "on backup, 40 minutes of fuel left": ex(fact("facility_status", facility_state="backup", endurance_min=40)),
}


def judge_need(**payload):
    return {"source": "judge", "kind": "need", "household_id": JUDGE, "text": "we are 2, one wheelchair",
            "payload": {"people": 2, "mobility": True, "accessible_vehicle": True, **payload}}


def make(settings, b, auto=True, **kw):
    """The text-driven drill app: real allocator and simulator, the scripted model, the auto clock."""
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, auto_clock=auto, **kw)
    return TestClient(create_app(s, bridge=b, llm=FakeLLM(SCRIPT)))


def deliver(client, obj):
    """What the Photon listener does with a message.received event."""
    return client.portal.call(client.app.state.messenger.handle_inbound, parse_inbound(obj))


class Tap:
    """Every text in/out, per phone handle (what the drill console prints)."""

    def __init__(self, c):
        self.c, self.events = c, []
        c.app.state.messenger.taps.append(self.events.append)

    def outs(self, handle):
        from residents.threads import phone_for_thread
        out = []
        for e in self.events:
            who = e["who"]
            if not isinstance(who, str):
                p = phone_for_thread(self.c.app.state.store, who)
                who = p["handle"] if p else None
            if who == handle and e["direction"] == "out":
                out.append(e["text"].removeprefix("[EMBER drill] "))
        return out


def register(c, handle=R1, **kw):
    r = c.post("/phones", json={"role": "resident", "handle": handle, "locate": True, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def text(c, handle, msg, role="resident"):
    r = c.post("/dev/inbound", json={"role": role, "handle": handle, "text": msg})
    assert r.status_code == 200, r.text
    return r.json()


def thread_of(c, handle):
    return next(p["thread"] for p in c.get("/phones").json() if p["handle"] == handle)


def clock(c):
    return c.get("/health").json()["t_s"]


def place(c, tap, handle=R1, where=PUTNAM):
    text(c, handle, where)
    t = thread_of(c, handle)
    assert t is not None, tap.outs(handle)
    return t
