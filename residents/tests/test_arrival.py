"""Pause on arrival (D112): the clock stops where a player's vehicle reaches them, the player is called, and the clock
waits there until that call ends or the operator resumes. Real allocator and simulator, fake ElevenLabs, no network."""
from dataclasses import replace

import pytest

from residents.contracts import errors
from tests.helpers import CALLENDER, R1, R2, make, register, text, thread_of
from tests.test_voice import OURS, configure, dials, fake_eleven, join, over, say, spoken


@pytest.fixture
def vd(drill):
    configure(drill)  # calls configured, so EMBER calls on its own (D100): never the real ElevenLabs
    drill.seen = []
    drill.app.state.voice.http = fake_eleven(drill.seen, [])
    return drill


def arrivals(c) -> list[dict]:
    """Every `arrival` envelope the backend broadcasts from now on (each checked against the contract)."""
    hub, seen = c.app.state.hub, []
    real = hub.broadcast

    async def broadcast(type_, data, t_s):
        env = await real(type_, data, t_s)
        if type_ == "arrival":
            assert not errors("ws-events", env), errors("ws-events", env)
            seen.append(env)
        return env
    hub.broadcast = broadcast
    return seen


def arrive(c, handle) -> tuple[float, dict]:
    """(when the plan's vehicle reaches this phone's household, that assignment)."""
    st, t = c.app.state, thread_of(c, handle)
    plan = st.store.current_plan()
    a = next(x for x in plan["assignments"] if x["target"] == t and x["status"] not in ("cancelled", "rejected"))
    return st.planner.bridge.outcomes(plan, st.store.reports())[a["id"]]["arrive_t"], a


def clock(c, t_s, **kw) -> dict:
    r = c.post("/clock", json={"t_s": t_s, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_clock_waits_at_a_players_door_until_the_call_ends(vd, monkeypatch):
    c = vd
    seen = arrivals(c)
    join(c, R1)
    spoken(say(c, "2 of us", caller=OURS, called=R1, conv="conv_9"))
    over(c, monkeypatch)
    c.portal.call(c.app.state.voice.check)                              # the first-contact call is over
    c.app.state.voice.http = fake_eleven(c.seen, [])                    # the next call stays on
    t, a = arrive(c, R1)
    n = len(dials(c))
    r = clock(c, t + 600)                                               # the web's playback runs past the arrival
    want = {"t_s": t, "household_id": thread_of(c, R1)["household_id"], "resource_id": a["resource_id"],
            "resource_name": next(x["name"] for x in c.get("/state").json()["resources"] if x["id"] == a["resource_id"]),
            "player": 1, "call": True}
    assert r["t_s"] == t and r["held_by"] == want
    assert [(e["t_s"], e["data"]) for e in seen] == [(t, want)]
    [(to, first)] = dials(c)[n:]                                        # the vehicle is outside: their phone rings
    assert to == R1 and " now. Tell the driver your address and that you are 2, then get in." in first, first
    assert c.get("/health").json()["hold"] == want
    assert clock(c, t + 900)["t_s"] == t and len(seen) == 1             # still on the call: held, no second event
    over(c, monkeypatch)
    c.portal.call(c.app.state.voice.check)                              # they hung up
    assert c.get("/health").json()["hold"] is None
    assert clock(c, t + 900) == {"t_s": t + 900, "plan_version": c.get("/health").json()["plan_version"], "held_by": None}


def test_resume_releases_it_once_and_only_players_hold(drill):
    """No calls configured: the step is texted and the clock waits until the operator presses play (resume). A phone
    without a player number never stops the clock, and a passed arrival never stops it again."""
    c = drill
    seen = arrivals(c)
    join(c, R1)
    text(c, R1, "2 of us")
    register(c, R2)                                                     # a team phone, not a player
    text(c, R2, CALLENDER)
    text(c, R2, "2 of us")
    t, _ = arrive(c, R1)
    end = c.app.state.planner.bridge.t_end_s
    r = clock(c, end)
    assert r["t_s"] == t and r["held_by"]["call"] is False and r["held_by"]["player"] == 1
    assert clock(c, end)["t_s"] == t                                    # waits for the operator
    assert clock(c, 0)["held_by"] is not None                           # scrubbing back keeps the hold
    assert clock(c, end, resume=True) == {"t_s": end, "plan_version": r["plan_version"], "held_by": None}
    assert [e["data"]["household_id"] for e in seen] == [thread_of(c, R1)["household_id"]]
    assert clock(c, 0)["t_s"] == 0 and clock(c, end)["t_s"] == end and len(seen) == 1


def test_several_players_hold_at_the_earliest_each_in_turn(drill):
    c = drill
    seen = arrivals(c)
    for h in (R1, R2):
        join(c, h)
        text(c, h, "2 of us")
    times = sorted({arrive(c, h)[0] for h in (R1, R2)})
    end = c.app.state.planner.bridge.t_end_s
    assert [clock(c, end, resume=i > 0)["t_s"] for i in range(len(times))] == times
    assert sorted(e["data"]["player"] for e in seen) == [1, 2] and [e["t_s"] for e in seen] == sorted(e["t_s"] for e in seen)
    assert clock(c, end, resume=True)["t_s"] == end


def test_auto_hold_off_never_stops_the_clock(settings, solo_bridge):
    with make(replace(settings, auto_hold=False), solo_bridge) as c:
        seen = arrivals(c)
        join(c, R1)
        text(c, R1, "2 of us")
        end = c.app.state.planner.bridge.t_end_s
        assert clock(c, end) == {"t_s": end, "plan_version": c.get("/health").json()["plan_version"], "held_by": None}
        assert seen == []
