"""The text-driven drill (D56): a resident texts where they are, gets placed on the map, answers the plan's
question, says YES, then gets one text per step (go to the corner / board / ride / checked in) and
replies DONE; with auto_clock the sim clock jumps to the next step. Real allocator + simulator, fake LLM,
fake geocoder, no network."""
import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from ember_engine.state import validate_state
from residents.app import create_app
from residents.drill import Drill, SetupError, main as drill_main
from residents.engine_bridge import EngineBridge
from residents.extract import to_outcome
from residents.guide import STEP_DONE
from residents.locate import JOIN_LEAD_S
from residents.messaging import FULL
from residents.photon import parse_inbound
from residents.places import Place, parse_coords
from tests.fake_photon import FakePhoton, received
from tests.test_engine import SCENARIO, bridge  # noqa: F401
from tests.test_extract import FakeLLM, ex, fact
from tests.test_messaging import deliver

R1, R2, OP = "+16175550101", "+16175550102", "+16175550103"
GREEN = "corner of Green St and Sellers St"           # outside the forecast flood: shelter in place
PUTNAM = "Putnam Ave and Western Ave"                   # the flood reaches it (pickup by 135 min)
CALLENDER = "Callender St and Putnam Ave"               # also in the flood
EVERETT = "Everett St and Western Ave"
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


@pytest.fixture(scope="session")
def solo_bridge():
    """Only the drill's people need rescue (no synthetic households): offers come fast and are predictable."""
    return EngineBridge(SCENARIO, moves=10, solo=True)


def make(settings, b, auto=True, **kw):
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, auto_clock=auto, **kw)
    return TestClient(create_app(s, bridge=b, llm=FakeLLM(SCRIPT)))


@pytest.fixture
def drill(settings, solo_bridge):
    with make(settings, solo_bridge) as c:
        yield c


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


def outcome(c, thread):
    st = c.app.state
    plan = st.store.current_plan()
    a = next(x for x in plan["assignments"] if x["target"] == thread and x["status"] == "confirmed")
    return st.planner.bridge.outcomes(plan, st.store.reports())[a["id"]]


def place(c, tap, handle=R1, where=PUTNAM):
    text(c, handle, where)
    t = thread_of(c, handle)
    assert t is not None, tap.outs(handle)
    return t


# ---------- places ----------
def test_coordinates_from_maps_links_and_typed():
    assert parse_coords("https://maps.apple.com/?ll=42.3637,-71.1250&q=Dropped%20Pin") == (-71.125, 42.3637)
    assert parse_coords("https://www.google.com/maps/@42.3637,-71.125,17z") == (-71.125, 42.3637)
    assert parse_coords("I'm at 42.36371, -71.12500 near the river") == (-71.125, 42.36371)
    assert parse_coords("125 Western Ave") is None and parse_coords("2 of us") is None


async def test_locate_intersection_address_and_outside(solo_bridge):
    g = solo_bridge.places
    hit = await g.locate("Everett St and Western Ave", geocoder=None)
    assert isinstance(hit, Place) and hit.source == "intersection" and g.in_town(hit.lon, hit.lat)
    assert hit.label == "Everett Street and Western Avenue"
    seen = []

    async def geo(q, box):
        seen.append((q, box))
        return (hit.lon, hit.lat, "125 Western Ave, Allston") if "125" in q else None
    addr = await g.locate("125 western ave, allston", geocoder=geo)
    assert isinstance(addr, Place) and addr.source == "address" and addr.label == "125 Western Ave"
    assert seen[0][1] == g.box  # the lookup is bounded to the town
    assert await g.locate("Nowhere Street", geocoder=geo) is None
    assert await g.locate("42.0, -75.0", geocoder=geo) == "outside"


# ---------- extraction ----------
def test_location_and_done_facts_are_not_reports():
    o = to_outcome(ex(fact("location", address="125 Western Ave", cross_street=None)), role="resident",
                   thread={"household_id": 1}, text="125 Western Ave", pending=None, resolve_road=lambda *a: [],
                   last_assignment_id=None)
    assert o.location == {"address": "125 Western Ave", "cross_street": None} and o.reports == []
    o = to_outcome(ex(fact("done")), role="resident", thread={"household_id": 1}, text="at the corner",
                   pending=None, resolve_road=lambda *a: [], last_assignment_id="a-1")
    assert o.step_done and o.reports == []
    assert all(STEP_DONE.match(t) for t in ("DONE", "done.", "ok done", "Here!", "we're here", "aboard", "yes", "👍"))
    assert not any(STEP_DONE.match(t) for t in ("not done yet", "the corner is flooded", "where are you?"))


# ---------- placing a resident by their text ----------
def test_resident_is_placed_where_they_text(drill, solo_bridge, town):
    tap = Tap(drill)
    p = register(drill)
    assert p["thread"] is None and "location" in p["action_needed"]
    text(drill, R1, "hi")
    assert "Where are you right now?" in tap.outs(R1)[-1]
    assert thread_of(drill, R1) is None
    text(drill, R1, GREEN)
    t = thread_of(drill, R1)
    hid = t["household_id"]
    outs = tap.outs(R1)
    assert outs[-2].startswith("Got it: we have you at Green Street and Sellers Street. Your street")  # their corner
    assert "Your street is outside the forecast flood area. (Drill tip: to test an evacuation, start over from a spot the water reaches, e.g. " in outs[-2]
    assert outs[-1] == "How many people are with you, and does anyone need a wheelchair-accessible vehicle?"
    st = drill.get("/state").json()
    h = next(x for x in st["households"] if x["household_id"] == hid)
    assert h["needs"] == "unknown" and h["label"] == "Green Street and Sellers Street (texted in)"
    assert validate_state(st, solo_bridge.scenario, town) == []  # the added household is a valid contract row
    thread_texts = [m["text"] for m in st["messages"] if m["thread"] == t]
    assert thread_texts[:2] == ["hi", "[EMBER drill] " + outs[0]]  # the pre-placement chat moved into the thread
    assert [h["household_id"] for h in solo_bridge.extra_households] == [hid]
    text(drill, R1, "2 of us")  # not threatened: the plan sends no vehicle, and we say so plainly
    assert "outside the forecast flood area, so no pickup is planned: stay where you are" in tap.outs(R1)[-1]


def test_flood_zone_placement_says_when_the_water_comes(drill, solo_bridge):
    tap = Tap(drill)
    register(drill)
    t = place(drill, tap)
    d = solo_bridge.deadline(t["household_id"])
    assert d is not None
    assert tap.outs(R1)[-2].endswith(f"Water is forecast to reach your street in about {round((d + 900) / 60)} min.")
    corners = solo_bridge.flood_corners(3)
    assert len(corners) == 3 and corners[0][0] <= corners[1][0] and " and " in corners[0][1]


def test_outside_or_unknown_place_asks_again(drill):
    tap = Tap(drill)
    register(drill)
    text(drill, R1, "42.0, -75.0")
    assert "outside the drill area" in tap.outs(R1)[-1]
    text(drill, R1, "somewhere in Ohio")  # geocoding off in tests → not found
    assert "couldn't find \"somewhere in Ohio\"" in tap.outs(R1)[-1]
    assert thread_of(drill, R1) is None and drill.get("/state").json()["households"] == []


def test_needs_said_with_the_location_are_kept(drill, solo_bridge):
    node = solo_bridge.places.nodes[next(iter(solo_bridge.places.streets))]

    async def geo(q, box):
        return node[0], node[1], q
    drill.app.state.locator.geocoder = geo
    tap = Tap(drill)
    register(drill)
    text(drill, R1, "125 Western Ave, my mom uses a wheelchair")
    t = thread_of(drill, R1)
    assert tap.outs(R1)[-2].startswith("Got it: we have you at 125 Western Ave.")
    text(drill, R1, "2 of us")  # completes the wheelchair need: no head count yet → pending
    h = next(x for x in drill.get("/state").json()["households"] if x["household_id"] == t["household_id"])
    assert h["needs"] == {"people": 2, "mobility": True, "accessible_vehicle": True}
    assert "will pick you up at your door" in tap.outs(R1)[-1]


def test_needs_before_the_location_lead_straight_to_an_offer(drill):
    tap = Tap(drill)
    register(drill)
    text(drill, R1, "2 of us")
    assert tap.outs(R1)[-1].startswith("Thanks, noted. Where are you right now?")
    place(drill, tap)
    outs = tap.outs(R1)
    assert outs[-2].startswith("Got it: we have you at Putnam Avenue and Western Avenue.")
    assert " will pick you up at " in outs[-1] and "How many people" not in " ".join(outs)


def test_two_phones_never_share_a_building(drill):
    register(drill, R1)
    register(drill, R2)
    text(drill, R1, EVERETT)
    text(drill, R2, EVERETT)
    assert thread_of(drill, R1) != thread_of(drill, R2)


# ---------- step-by-step directions ----------
def test_guided_rescue_moves_the_clock_one_step_at_a_time(drill):
    tap = Tap(drill)
    register(drill)
    t = place(drill, tap)
    text(drill, R1, "2 of us")
    offer = tap.outs(R1)[-1]
    assert " will pick you up at the corner of " in offer and "Reply YES" in offer
    text(drill, R1, "yes")
    o = outcome(drill, t)
    assert 0 < o["arrive_t"] < o["pickup_t"] < o["complete_t"]
    step1 = tap.outs(R1)[-1]
    assert step1.startswith("Confirmed: ") and "Step 1 of 4: Pack medications" in step1 and "the pickup point" in step1
    assert clock(drill) == 0.0
    text(drill, R1, "we're at the corner now")  # in their words (LLM "done") → clock → the vehicle arrives
    assert clock(drill) == o["arrive_t"] and tap.outs(R1)[-1].startswith("Step 2 of 4: ")
    text(drill, R1, "done")                     # aboard → the pickup is complete
    assert clock(drill) == o["pickup_t"] and tap.outs(R1)[-1].startswith("Step 3 of 4: You're on your way to ")
    text(drill, R1, "DONE")                     # arrived → checked in
    assert clock(drill) == o["complete_t"] and tap.outs(R1)[-1].startswith("Step 4 of 4: You're checked in at ")
    h = next(x for x in drill.get("/state").json()["households"] if x["household_id"] == t["household_id"])
    assert h["status"] == "safe"
    g = drill.app.state.guide.state(f"household:{t['household_id']}")
    assert g["finished"] and g["done"] == [0, 1, 2]
    n = len(tap.outs(R1))
    drill.post("/replan")  # a later replan must not tell them their (finished) ride is "no longer coming"
    assert not any("no longer coming" in x for x in tap.outs(R1)[n:])
    drill.app.state.intake.llm.script["thanks"] = ex(fact("other"))
    text(drill, R1, "done")      # nothing left to do: where they stand, not silence
    text(drill, R1, "thanks")
    assert all(x.startswith("You're checked in at ") for x in tap.outs(R1)[-2:]), tap.outs(R1)[-2:]


def test_walking_directions_to_the_corner(drill, solo_bridge):
    import re
    g = solo_bridge.places
    # a flood-zone building whose pickup corner is a real walk away (the road graph is intersections only)
    lon, lat = next((hl, ha) for hid, hl, ha, n in g.households
                    if 80 < g.dist_m(hl, ha, *g.nodes[n]) < 300 and len(g.streets.get(n, ())) >= 2
                    and solo_bridge.deadline(hid) is not None)

    async def geo(q, box):
        return lon, lat, q
    drill.app.state.locator.geocoder = geo
    script = drill.app.state.intake.llm.script
    script["10 Putnam Ave"] = ex(fact("location", address="10 Putnam Ave"))
    tap = Tap(drill)
    register(drill)
    text(drill, R1, "10 Putnam Ave")
    t = thread_of(drill, R1)
    node = solo_bridge.household_node(t["household_id"])
    text(drill, R1, "2 of us")
    text(drill, R1, "yes")
    step1 = next(x for x in tap.outs(R1) if "Step 1 of 4" in x)
    m = re.search(r"walk to the pickup point: (the corner of .+?), about (\d+) m (\S+) of you \(about (\d+) min on foot\)", step1)
    assert m, step1
    nlon, nlat = g.nodes[node]
    assert m.group(1) == g.corner_label(node) and m.group(3) == g.bearing(lon, lat, nlon, nlat)
    assert abs(int(m.group(2)) - g.dist_m(lon, lat, nlon, nlat) * 1.3) <= 10


def test_wheelchair_pickup_is_at_the_door(drill):
    tap = Tap(drill)
    register(drill)
    place(drill, tap)
    text(drill, R1, "me and my dad, he uses a wheelchair")
    assert "Accessible Van 3 will pick you up at your door" in tap.outs(R1)[-1]
    text(drill, R1, "yes")
    assert any("Step 1 of 4: Stay inside at Putnam Avenue and Western Avenue" in x for x in tap.outs(R1))


def test_manual_clock_waits_for_the_clock(settings, solo_bridge):
    with make(settings, solo_bridge, auto=False) as c:
        tap = Tap(c)
        register(c)
        t = place(c, tap)
        text(c, R1, "2 of us")
        text(c, R1, "yes")
        o = outcome(c, t)
        text(c, R1, "done")
        assert clock(c) == 0.0
        assert tap.outs(R1)[-1] == f"Thanks. We'll text you the next step in about {round(o['arrive_t'] / 60)} min."
        c.post("/clock", json={"t_s": o["arrive_t"]})  # the web's playback reaches the arrival
        assert tap.outs(R1)[-1].startswith("Step 2 of 4: ")


def test_clock_waits_until_everyone_is_done(drill):
    tap = Tap(drill)
    for h in (R1, R2):
        register(drill, h)
    place(drill, tap, R1, PUTNAM)
    place(drill, tap, R2, CALLENDER)
    for h in (R1, R2):
        text(drill, h, "just me")
        text(drill, h, "yes")
    guide = drill.app.state.guide
    assert len(guide.awaiting()) == 2
    text(drill, R1, "done")
    assert clock(drill) == 0.0 and tap.outs(R1)[-1].startswith("Thanks. We'll text you the next step")
    text(drill, R2, "done")
    assert clock(drill) > 0.0  # the last one EMBER waited on → the next event


def test_confirm_on_the_console_texts_step_one(drill):
    tap = Tap(drill)
    register(drill)
    t = place(drill, tap)
    text(drill, R1, "2 of us")
    a = next(x for x in drill.get("/plan/current").json()["assignments"] if x["target"] == t)
    r = drill.post(f"/assignments/{a['id']}/confirm", json={})
    assert r.status_code == 200, r.text
    assert "Step 1 of 4" in tap.outs(R1)[-1]


def test_operator_gets_generator_steps(drill):
    tap = Tap(drill)
    assert drill.post("/phones", json={"role": "operator", "handle": OP, "facility_id": "mt-auburn"}).status_code == 200
    text(drill, OP, "on backup, 40 minutes of fuel left", role="operator")
    offer = tap.outs(OP)[-1]
    assert "is on its way to you" in offer and "Reply YES" in offer
    text(drill, OP, "yes", role="operator")
    assert "Step 1 of 3: Have someone meet the crew" in tap.outs(OP)[-1]
    text(drill, OP, "done", role="operator")
    assert tap.outs(OP)[-1].startswith("Step 2 of 3: ") and "to connect it" in tap.outs(OP)[-1]
    text(drill, OP, "done", role="operator")
    assert tap.outs(OP)[-1].startswith("Step 3 of 3: Mount Auburn Hospital is on ")
    drill.app.state.intake.llm.script["thanks"] = ex(fact("other"))
    text(drill, OP, "thanks", role="operator")
    assert tap.outs(OP)[-1].startswith("Mount Auburn Hospital is on Generator")


# ---------- runs: reset and restart ----------
def test_reset_starts_from_scratch(drill, solo_bridge):
    tap = Tap(drill)
    register(drill)
    t = place(drill, tap)
    drill.post("/dev/reset")
    assert thread_of(drill, R1) is None and solo_bridge.extra_households == []
    assert all(h["household_id"] != t["household_id"] for h in drill.get("/state").json()["households"])
    assert drill.app.state.store.kv_prefix("located:") == {} and drill.app.state.store.kv_get("extra_households") is None
    assert tap.outs(R1)[-1].startswith("Welcome to the EMBER flood drill.")  # asked again (dev delivery)
    assert place(drill, tap) == t  # and placed again


def test_restart_keeps_the_people_who_texted_in(settings, solo_bridge):
    with make(settings, solo_bridge) as c:
        tap = Tap(c)
        register(c)
        t = place(c, tap)
        text(c, R1, "2 of us")
        text(c, R1, "yes")
    solo_bridge.set_extra_households([])  # as if the process restarted with a fresh engine
    with make(settings, solo_bridge) as c:  # same DB, no reset
        assert [h["household_id"] for h in solo_bridge.extra_households] == [t["household_id"]]
        assert thread_of(c, R1) == t
        assert any(h["household_id"] == t["household_id"] for h in c.get("/state").json()["households"])
        assert c.app.state.guide.awaiting() == [f"household:{t['household_id']}"]


# ---------- Photon: the lobby opts the phone in and replies on the shared line ----------
def test_unplaced_phone_opts_in_and_is_answered_over_photon(settings, solo_bridge, monkeypatch):
    async def no_wait(*args):
        pass
    monkeypatch.setattr("residents.photon._backoff", no_wait)
    fp = FakePhoton()
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, auto_clock=True, photon_enabled=True, photon_listen=False)
    with TestClient(create_app(s, photon_client=fp.client(), bridge=solo_bridge, llm=FakeLLM(SCRIPT))) as c:
        p = register(c)
        assert p["assigned_number"] and not p["opted_in"] and p["action_needed"].startswith(f"Text HI from {R1}")
        deliver(c, received("m-1", R1, "hi"))
        assert c.get("/phones").json()[0]["opted_in"] is True
        assert "Where are you right now?" in fp.sends()[-1]["content"]["text"]
        deliver(c, received("m-1", R1, "hi"))  # redelivery: not answered twice
        assert len(fp.sends()) == 1
        deliver(c, received("m-2", R1, GREEN))
        texts = [x["content"]["text"] for x in fp.sends()]
        assert texts[-2].startswith("[EMBER drill] Got it: we have you at Green Street and Sellers Street.")
        assert texts[-1].startswith("[EMBER drill] How many people are with you")
        assert thread_of(c, R1) is not None


# ---------- the console ----------
def test_console_commands(drill, capsys):
    import argparse
    d = Drill(argparse.Namespace(dry=True, crowded=False, keep=False, manual_clock=False, port=0, db="x.db",
                                 resident=[R1], operator=[]))
    d.app = drill.app
    register(drill)
    d.names[R1] = "r1"
    run = lambda line: drill.portal.call(d.command, line)  # noqa: E731
    assert run(f"@r1 {PUTNAM}") and thread_of(drill, R1) is not None
    run("@r1 2 of us")
    run("@r1 yes")
    run("status")
    out = capsys.readouterr().out
    assert "r1: household #" in out and "step 1 of 4 · waiting for DONE" in out
    run("+5")
    assert clock(drill) == 300.0
    run("n")
    assert clock(drill) > 300.0
    run("close Green Street and Sellers Street")
    assert "closed" in capsys.readouterr().out
    assert run("quit") is False


def test_console_needs_phones_or_dry(monkeypatch):
    monkeypatch.delenv("DRILL_RESIDENTS", raising=False)
    monkeypatch.delenv("DRILL_OPERATORS", raising=False)
    import residents.drill as d
    seen = {}

    async def fake_run(self):
        seen["args"] = self.args
    monkeypatch.setattr(d.Drill, "run", fake_run)
    monkeypatch.setattr(d, "setup_logging", lambda path: None)
    drill_main(["--dry"])
    assert seen["args"].resident == ["+16175550101"]  # a pretend phone for a dry run
    drill_main(["--resident", "6175550199", "--operator", "6175550198@mt-auburn"])
    assert seen["args"].resident == ["6175550199"] and seen["args"].operator == ["6175550198@mt-auburn"]


# ---------- what we say while no vehicle is free ----------
class _Store:
    def __init__(self, needs, deadline):
        self.h = {"household_id": 7, "needs": needs, "deadline_s": deadline, "status": "needs"}

    def households(self):
        return [self.h]

    def facilities(self):
        return []

    def meta(self):
        return {"t_s": 0.0}

    def snapshot(self):
        return {"resources": []}

    def kv_get(self, key, default=None):
        return default


@pytest.mark.parametrize("needs,deadline,want,not_want", [
    ({"people": 2, "mobility": True}, 9000.0, "Until one is: shelter in place above ground floor. ", "walk"),
    ({"people": 2}, 9000.0, "Until one is: shelter in place above ground floor or walk to the nearest dry pickup point if able. ", None),
    ({"people": 2}, None, "outside the forecast flood area, so no pickup is planned: stay where you are", "No suitable vehicle"),
])
def test_blocked_status_uses_the_engines_alternatives(needs, deadline, want, not_want):
    from residents.outbound import Outbound
    view = {"version": 3, "assignments": [], "unresolved": [{
        "target": {"household_id": 7}, "need": "2 people", "blocked_by": "every eligible vehicle is committed to earlier deadlines",
        "would_unblock": "release reserve Van 1",
        "alternatives": ["shelter in place above ground floor", "walk to the nearest dry pickup point if able"]}]}
    text = Outbound(_Store(needs, deadline), messenger=None).status_text(view, {"household_id": 7})
    assert want in text and (not_want is None or not_want not in text), text


# ---------- a new run: the command line decides who plays what ----------
def _drill_for(c, residents=(), operators=(), keep=False):
    import argparse
    d = Drill(argparse.Namespace(dry=True, crowded=False, keep=keep, manual_clock=False, port=0, db="x.db",
                                 resident=list(residents), operator=list(operators)))
    d.app = c.app
    return d


def test_new_run_rebinds_phones_from_the_last_run(drill, capsys):
    """Regression (live, 2026-10-17): R2 was the hospital operator last run and a resident now → PhoneConflict crash."""
    store = drill.app.state.store
    assert drill.post("/phones", json={"role": "operator", "handle": R2, "facility_id": "mt-auburn"}).status_code == 200
    register(drill, R1)
    register(drill, OP)                           # in the last run, not in this one
    store.upsert_phone(R2, "operator", space_id="sp", agent_user_id="ag", last_inbound_at="2026-10-17T10:00:00Z")
    d = _drill_for(drill, residents=[R1, R2])
    drill.portal.call(d.register)
    phones = {p["handle"]: p for p in drill.get("/phones").json()}
    assert set(phones) == {R1, R2}                # OP dropped: it gets nothing this run
    assert phones[R2]["role"] == "resident" and phones[R2]["thread"] is None and phones[R2]["opted_in"]  # opt-in kept
    assert d.names == {R1: "r1", R2: "r2"}
    tap = Tap(drill)
    text(drill, R2, PUTNAM)                       # and it can be placed like any resident
    assert thread_of(drill, R2) is not None and tap.outs(R2)[-1].startswith("How many people")
    # and back: a resident from the last run plays the hospital now
    d = _drill_for(drill, residents=[R1], operators=[f"{R2}@mt-auburn"])
    drill.portal.call(d.register)
    phones = {p["handle"]: p for p in drill.get("/phones").json()}
    assert phones[R2]["role"] == "operator" and phones[R2]["thread"] == {"facility_id": "mt-auburn"}


def test_same_phone_twice_is_a_clear_error(drill):
    d = _drill_for(drill, residents=[R1], operators=[f"{R1}@mt-auburn"])
    with pytest.raises(SetupError, match="listed more than once"):
        drill.portal.call(d.register)
    d = _drill_for(drill, operators=[f"{R1}@mt-auburn", f"{R2}@mt-auburn"])
    with pytest.raises(SetupError, match="Can't register the phones"):
        drill.portal.call(d.register)


# ---------- the plan around other people, in words (D57) ----------
STADIUM = "Stadium Rd and Western Ave"
NEIGHBORS = {
    STADIUM: ex(fact("location", address="Stadium Rd", cross_street="Western Ave")),
    "4 people and we need a wheelchair": ex(fact("need", people=4, mobility=True, accessible_vehicle=True)),
    "3 people and we need 2 wheelchairs": ex(fact("need", people=3, mobility=True, accessible_vehicle=True)),
    "HOW MUCH TIME": ex(fact("question", question_topic="eta")),
    "no, we want to travel with others, is there another person near me?":
        ex(fact("reject"), fact("question", question_topic="others")),
    "are there other vans?": ex(fact("question", question_topic="vehicles")),
    "where do we go?": ex(fact("question", question_topic="pickup_place")),
    "what should we bring?": ex(fact("question", question_topic="bring")),
    "is the bridge open?": ex(fact("question", question_topic="other")),
    "no": ex(fact("reject")),
    "4 people and we need a Welch's": ex(fact("need", people=4), confidence=0.6,
                                        q="Did you mean you need a wheelchair-accessible vehicle?"),
}


@pytest.fixture
def pair(drill):
    """Two neighbours at the same corner who both need the fleet's only wheelchair-accessible vehicle
    (the 2026-10-17 two-phone run, replayed with what the model returned)."""
    drill.app.state.intake.llm.script.update(NEIGHBORS)
    drill.app.state.locator.llm.script.update(NEIGHBORS)
    tap = Tap(drill)
    for h in (R1, R2):
        register(drill, h)
    t2 = place(drill, tap, R2, STADIUM)
    t1 = place(drill, tap, R1, STADIUM)
    text(drill, R2, "4 people and we need a wheelchair")
    text(drill, R1, "3 people and we need 2 wheelchairs")
    return drill, tap, t1, t2


def test_offers_say_why_and_who_is_ahead(pair):
    c, tap, t1, t2 = pair
    assert t1 != t2
    o2, o1 = next(x for x in reversed(tap.outs(R2)) if "will pick you up" in x), tap.outs(R1)[-1]
    assert o2.startswith("Accessible Van 3 will pick you up at your door")
    assert "Your street isn't forecast to flood, so this is a precaution; reply NO if you'd rather stay put." in o2
    assert "Accessible Van 3 is the only wheelchair-accessible vehicle that fits 3 people; it picks up 1 other household first" in o1, o1
    assert "at your corner" in o1


def test_questions_are_answered_from_the_plan(pair):
    c, tap, t1, t2 = pair
    text(c, R2, "yes")
    text(c, R2, "HOW MUCH TIME")
    ans = tap.outs(R2)[-1]
    assert ans.startswith("Accessible Van 3 ") and " you should be at " in ans and "Reply YES" not in ans, ans
    status = c.app.state.outbound.status_text(c.app.state.store.plan_view(), t2)  # already said YES: never "Reply YES"
    assert status.startswith("Your pickup is confirmed: Accessible Van 3"), status
    text(c, R1, "are there other vans?")
    v = tap.outs(R1)[-1]
    assert v.startswith("Vehicles that fit 3 people with a wheelchair: Accessible Van 3 (assigned to you, after 1 other pickup).")
    assert "Not suitable:" in v and "Van 1" in v and "Van 2" in v
    text(c, R1, "where do we go?")
    assert tap.outs(R1)[-1].startswith("Stay inside at Stadium Road and Western Avenue: the crew comes to your door")
    text(c, R1, "what should we bring?")
    assert tap.outs(R1)[-1].startswith("Bring medications")
    text(c, R1, "is the bridge open?")  # labelled `other`: a coordinator, and where they stand meanwhile (D60)
    assert tap.outs(R1)[-1].startswith("Our plan doesn't cover that, so we've passed your question to a coordinator, "
                                       "who will reply here. Meanwhile, here's where you stand: Accessible Van 3 is "
                                       "assigned to pick you up"), tap.outs(R1)[-1]


def test_no_to_the_only_vehicle_is_checked_and_the_question_answered(pair):
    c, tap, t1, t2 = pair
    n = len(tap.outs(R1))
    text(c, R1, "no, we want to travel with others, is there another person near me?")
    new = tap.outs(R1)[n:]
    assert new[0].startswith("1 other household in this drill is within 300 m of you (1 at your pickup corner).")
    assert "Accessible Van 3 also picks up 1 of them (1 before you, 0 after)" in new[0]
    # engine D59 shares trips, but 4 + 3 people don't fit the van's 6 seats: say so, not "one household per trip"
    assert "on separate trips: together you'd be 7 people and it has 6 seats." in new[0], new[0]
    assert new[1].startswith("Accessible Van 3 is the only wheelchair-accessible vehicle that can take 3 people with a wheelchair.")
    assert c.app.state.store.kv_get(f"rejected:household:{t1['household_id']}") is None  # not banned
    text(c, R1, "yes")  # keep it
    assert any("Confirmed: Accessible Van 3 is coming to your door" in x for x in tap.outs(R1)[n:])


def test_declined_anyway_then_yes_takes_it_back(pair):
    c, tap, t1, t2 = pair
    text(c, R1, "no")
    text(c, R1, "no")   # decline anyway
    key = f"rejected:household:{t1['household_id']}"
    assert c.app.state.store.kv_get(key) == '["van-3"]'
    text(c, R1, "are there other vans?")
    assert "Accessible Van 3 (you declined it)" in tap.outs(R1)[-1]
    status = c.app.state.outbound.status_text(c.app.state.store.plan_view(), t1)
    assert status.startswith("You declined Accessible Van 3, the only vehicle that can take 3 people, wheelchair-accessible vehicle")
    assert "Reply YES if you want Accessible Van 3 after all" in status
    text(c, R1, "yes")
    assert c.app.state.store.kv_get(key) == "[]"
    assert any("Confirmed: Accessible Van 3 is coming to your door" in x for x in tap.outs(R1)[-3:]), tap.outs(R1)[-3:]


def test_no_with_another_vehicle_free_declines_at_once(drill):
    tap = Tap(drill)
    drill.app.state.intake.llm.script.update(NEIGHBORS)
    register(drill)
    t = place(drill, tap)
    text(drill, R1, "2 of us")
    first = next(a for a in drill.get("/plan/current").json()["assignments"] if a["target"] == t)
    text(drill, R1, "no")   # vans that fit 2 people: several → no check, it's declined
    assert drill.app.state.store.kv_get(f"rejected:household:{t['household_id']}") == json.dumps([first["resource_id"]])


def test_garbled_need_plans_what_is_clear_and_asks_about_the_rest(drill):
    """Live 2026-10-17: "we need a Welch's" (autocorrected wheelchair) was silently dropped."""
    drill.app.state.intake.llm.script.update(NEIGHBORS)
    tap = Tap(drill)
    register(drill)
    place(drill, tap)
    text(drill, R1, "4 people and we need a Welch's")
    outs = tap.outs(R1)
    assert " will pick you up at " in outs[-2]
    assert outs[-1] == "Did you mean you need a wheelchair-accessible vehicle?"


# ---------- multiplayer: strangers text JOIN EMBER (D78) ----------
@pytest.fixture
def lobby(settings, solo_bridge, monkeypatch):
    async def no_wait(*args):
        pass
    monkeypatch.setattr("residents.photon._backoff", no_wait)
    fp = FakePhoton()
    s = replace(settings, scenario=SCENARIO, extract_enabled=True, photon_enabled=True, photon_listen=False)
    with TestClient(create_app(s, photon_client=fp.client(), bridge=solo_bridge, llm=FakeLLM(SCRIPT))) as c:
        yield c, fp


def settle(c):
    """Wait for the replan a burst of joins scheduled."""
    if (task := c.app.state.locator.replan_task) is not None:
        c.portal.call(lambda: task)


def join(c, *handles):
    """Each handle texts "Join Ember" at the same moment."""
    async def burst():
        await asyncio.gather(*(c.app.state.messenger.handle_inbound(parse_inbound(received(f"j-{h}", h, "Join Ember please")))
                               for h in handles))
    c.portal.call(burst)
    settle(c)


def players(c):
    return {p["handle"]: p for p in c.get("/phones").json() if p["player"] is not None}


def test_three_phones_join_at_once(lobby, solo_bridge):
    c, fp = lobby
    phones = ["+16175550201", "+16175550202", "+16175550203"]
    join(c, *phones)
    ps = players(c)
    assert sorted(p["player"] for p in ps.values()) == [1, 2, 3]
    hids = [ps[h]["household_id"] for h in phones]
    assert None not in hids and len(set(hids)) == 3
    assert len({solo_bridge.household_node(h) for h in hids}) == 3          # three different pickup corners
    assert all(solo_bridge.deadline(h) > JOIN_LEAD_S for h in hids)         # in the flood, still savable
    labels = {h["household_id"]: h["label"] for h in c.get("/state").json()["households"]}
    assert sorted(labels[h] for h in hids) == ["Player 1", "Player 2", "Player 3"]
    assert c.app.state.store.plan_versions() == [1, 2]                      # one replan for the burst
    for h in phones:
        texts = [x["content"]["text"] for x in fp.sends() if x["spaceId"] == f"pho_spc_{h[-4:]}"]
        assert texts[0].startswith(f"[EMBER drill] Welcome to the EMBER flood drill. You're Player {ps[h]['player']}:")
        assert "How many people are with you" in texts[-1]                  # the plan asks its own question


def test_the_31st_player_is_told_the_drill_is_full(lobby):
    c, fp = lobby
    phones = [f"+161755503{i:02d}" for i in range(31)]
    join(c, *phones[:30])
    join(c, phones[30])
    assert len(players(c)) == 30 and phones[30] not in {p["handle"] for p in c.get("/phones").json()}
    last = fp.sends()[-1]
    assert last["spaceId"] == "pho_spc_0330" and last["content"]["text"] == f"[EMBER drill] {FULL}"
    # a stranger's text without the join phrase is still ignored
    assert c.portal.call(c.app.state.messenger.handle_inbound, parse_inbound(received("x-1", "+16175550999", "hi"))) is None
    assert c.app.state.store.phone(handle="+16175550999") is None


def test_reset_places_players_again(lobby):
    c, fp = lobby
    join(c, "+16175550201", "+16175550202")
    before = {h: p["household_id"] for h, p in players(c).items()}
    c.post("/dev/reset")
    settle(c)
    assert {h: p["household_id"] for h, p in players(c).items()} == before  # placed again (same choice on a fresh run)
    assert c.app.state.store.plan_versions() == [1, 2]
    texts = [x["content"]["text"] for x in fp.sends()]
    assert not any("Where are you right now?" in t for t in texts)          # never asked where they are
    assert sum("You're Player 1:" in t for t in texts) == 2


def test_the_console_joins_an_unknown_phone(lobby):
    c, _ = lobby
    r = c.post("/dev/inbound", json={"role": "resident", "handle": "+16175550201", "text": "JOIN EMBER"})
    settle(c)
    assert r.json()["message"] is None and players(c)["+16175550201"]["household_id"] is not None
    assert c.post("/dev/inbound", json={"role": "resident", "handle": "+16175550202", "text": "hi"}).status_code == 422
