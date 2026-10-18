"""Ember backend: FastAPI app. Run from residents/: `uv run uvicorn residents.app:app --reload`."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .bus import Hub
from .config import CONTRACTS, Settings
from .db import PhoneConflict, Store
from .engine_bridge import EngineBridge
from .extract import LLM, make_llm
from .guide import Guide
from .intake import Intake
from .locate import Locator
from .outbound import ASK_NEEDS, Outbound
from .messaging import DrillFull, Messenger
from .photon import PhotonClient, PhotonError, PhotonListener
from .planner import Planner, ReportError
from .threads import normalize_handle

log = logging.getLogger("residents")

DEFAULT_ASK = {"operator": "How many hours of backup power do you have left on site?", "resident": ASK_NEEDS}
if not logging.getLogger().handlers:  # uvicorn only configures its own loggers; make ours visible too
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     [%(name)s] %(message)s")


def state_contract_version() -> str:
    """The version contracts/state.schema.json pins (follows engine's bumps without a code change here)."""
    return json.loads((CONTRACTS / "state.schema.json").read_text())["properties"]["version"]["const"]


def load_seed(path: Path) -> dict:
    state = json.loads(Path(path).read_text())
    want = state_contract_version()
    if state.get("version") != want:
        raise RuntimeError(f"{path}: state version {state.get('version')!r}, contracts/state.schema.json is {want!r}")
    return state


def open_store(settings: Settings, engine_mode: bool) -> Store:
    store = Store(settings.db_path)
    if engine_mode:
        return store  # the planner decides whether to bootstrap (it knows the scenario)
    if settings.reset_on_start or store.is_empty():
        store.seed(load_seed(settings.seed_state))
        log.info("static mode: seeded %s from %s", settings.db_path, settings.seed_state)
    else:
        log.info("static mode: using existing %s (plan v%s)", settings.db_path, store.meta().get("plan_version"))
    return store


async def start_engine(settings: Settings, store: Store, planner: Planner) -> None:
    db_scenario = store.meta().get("scenario_id")
    if settings.reset_on_start or store.is_empty() or db_scenario != planner.bridge.scenario_id:
        if db_scenario and db_scenario != planner.bridge.scenario_id:
            log.warning("DB holds %s but SCENARIO is %s: reseeding", db_scenario, planner.bridge.scenario_id)
        state = await planner.bootstrap(settings.start_t_s)
        log.info("engine mode: %s plan v%s at t=%.0f s", state["scenario_id"], state["plan_version"], state["t_s"])
    else:
        log.info("engine mode: using existing %s (%s, plan v%s); RESET_ON_START=1 or POST /dev/reset to replan from scratch",
                 settings.db_path, db_scenario, store.meta().get("plan_version"))


class RespondIn(BaseModel):
    # module level, not inside create_app: with postponed annotations FastAPI resolves hints by name
    plan_version: int | None = Field(default=None, description="the plan version the person answered (stale check)")


class TargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["resident", "operator"]
    household_id: int | None = Field(default=None, ge=0)
    facility_id: str | None = Field(default=None, min_length=1)


class AskIn(TargetIn):
    question: str | None = Field(default=None, max_length=300,
                                 description="omit → the plan's open question for that thread, else a default")


class SimulateIn(BaseModel):
    planner: Literal["ember", "baseline"] = "ember"


class ClockIn(BaseModel):
    t_s: float = Field(ge=0)


class DisruptionIn(BaseModel):
    """Either close roads (town.json edge ids; the reverse direction is closed too) or set facility fields."""
    close_edges: list[int] | None = None
    facility_id: str | None = None
    set: dict | None = None
    note: str | None = Field(default=None, max_length=300)


class PhoneIn(TargetIn):
    handle: str = Field(min_length=3, description="the tester's phone, e.g. 4135550100 or +14135550100")
    locate: bool = Field(default=False, description="resident without a household: they text where they are (D56)")


class ThreadIn(BaseModel):
    household_id: int | None = None
    facility_id: str | None = None

    def as_thread(self) -> dict:
        if (self.household_id is None) == (self.facility_id is None):
            raise HTTPException(422, "thread needs exactly one of household_id / facility_id")
        return {"household_id": self.household_id} if self.household_id is not None else {"facility_id": self.facility_id}


class MessageIn(BaseModel):
    thread: ThreadIn
    text: str = Field(min_length=1, max_length=1000)
    plan_version: int | None = None
    assignment_id: str | None = None


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="the coordinator's reply, texted as written")


class JoinIn(BaseModel):
    handle: str = Field(min_length=3, max_length=32, description="the player's phone, E.164 (e.g. +16175550123)")


class CallIn(BaseModel):
    handle: str = Field(min_length=3, description="a registered phone to call now (ElevenLabs via the Photon number)")


class DevInboundIn(TargetIn):
    text: str = Field(min_length=1, max_length=1000)
    handle: str | None = Field(default=None, description="as this registered phone (also before it has a household)")


def turn_writer(app: FastAPI, write):
    """Messenger's per-turn writer (D76): the conversation, the computed messages and a fact sheet → one reply."""
    from .db import thread_key
    from .reply import compose

    async def writer(handle: str, said: str, drafts: list[str], thread: dict | None) -> str | None:
        st = app.state
        store = st.store
        history = store.conversation(thread_key(thread), 8) if thread else [
            {"from": "them" if m["direction"] == "in" else "EMBER", "text": m["text"]}
            for m in st.messenger.lobby_log(handle)[-8:]]
        facts = []
        view = store.plan_view()
        if thread and view and st.outbound is not None:
            status = st.outbound.status_text(view, thread)
            if status:
                facts.append(status)
            if "household_id" in thread:
                h = next((x for x in store.households() if x["household_id"] == thread["household_id"]), {})
                facts.append(f"Their household: {h.get('label')}; needs as we have them: {h.get('needs')}")
        names = [r["name"] for r in store.snapshot()["resources"]] + [f["name"] for f in store.facilities()]
        channel = "phone call" if st.voice is not None and st.voice.live(handle) is not None else "text message"
        reply, why = await compose(write, said=said, history=history, drafts=drafts, facts=" ".join(facts),
                                   names=names, channel=channel)
        return reply

    return writer


def create_app(settings: Settings | None = None, photon_client: PhotonClient | None = None,
               bridge: EngineBridge | None = None, llm: LLM | None = None, writer=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        engine_mode = bridge is not None or settings.scenario is not None
        app.state.store = open_store(settings, engine_mode)
        app.state.hub = Hub()
        app.state.planner = None
        if engine_mode:
            b = bridge or await run_in_threadpool(EngineBridge, settings.scenario, None, 0, settings.engine_moves,
                                                  settings.drill_solo)
            app.state.planner = Planner(app.state.store, app.state.hub, b)
            await app.state.planner.restore_households()
        photon = photon_client
        if photon is None and settings.photon_enabled:
            photon = PhotonClient(settings.photon_api_key, settings.photon_project_id)
        app.state.messenger = Messenger(app.state.store, app.state.hub, photon, settings.max_players)
        app.state.outbound = app.state.guide = app.state.locator = None
        if app.state.planner is not None:
            app.state.outbound = Outbound(app.state.store, app.state.messenger, app.state.planner.bridge)
            app.state.planner.plan_hooks.append(app.state.outbound.on_plan)
            # after outbound: a changed instruction is texted before the next step of the old one
            app.state.guide = Guide(app.state.store, app.state.messenger, app.state.planner)
            app.state.planner.plan_hooks.append(app.state.guide.on_plan)
            app.state.planner.clock_hooks.append(app.state.guide.tick)
            app.state.outbound.guide = app.state.guide  # "what do I do?" includes the step they're on
        app.state.intake = None
        if app.state.planner is not None:  # no model (no key, or EXTRACT_ENABLED=0): texts go to the keyword parser
            model = None
            if settings.extract_enabled and (llm is not None or settings.anthropic_api_key):
                model = llm or make_llm(settings)
            app.state.intake = Intake(app.state.store, app.state.messenger, app.state.planner, model,
                                      app.state.outbound, app.state.guide)
            app.state.messenger.inbound_hooks.append(app.state.intake.on_inbound)
            from .places import nominatim
            app.state.locator = Locator(app.state.store, app.state.messenger, app.state.planner, model,
                                        nominatim if settings.geocode_enabled else None, drill_tips=settings.auto_clock)
            app.state.messenger.lobby_hooks.append(app.state.locator.on_lobby)
            app.state.planner.plan_hooks.append(app.state.locator.on_plan)
        from .voice import Voice
        app.state.voice = Voice(app.state.store, app.state.messenger, app.state.outbound, settings)
        app.state.voice.locator = app.state.locator  # someone who calls the voice number joins by voice (D100)
        if app.state.planner is not None:  # last: a call opens with what the other hooks just decided (D80, D100)
            app.state.planner.plan_hooks.append(app.state.voice.check)
            app.state.planner.clock_hooks.append(app.state.voice.check)
        if app.state.planner is not None and settings.reply_enabled and (writer is not None or (
                settings.anthropic_api_key and settings.extract_enabled)):
            from .reply import make_writer
            app.state.messenger.writer = turn_writer(app, writer or make_writer(settings))
        if app.state.planner is not None:  # after messenger + hooks exist: a fresh plan v1 texts its open questions
            await start_engine(settings, app.state.store, app.state.planner)
        app.state.listener = None
        if photon is not None and settings.photon_listen:
            app.state.listener = PhotonListener(photon, app.state.store, app.state.messenger.handle_inbound)
            await app.state.listener.start()
        retry_task = None
        if photon is not None:
            async def retry_loop() -> None:
                while True:
                    await asyncio.sleep(settings.retry_every_s)
                    try:
                        n = await app.state.messenger.retry_failed()
                        if n:
                            log.info("re-sent %d failed message(s)", n)
                    except Exception:  # noqa: BLE001 - keep retrying
                        log.exception("retry loop")
            retry_task = asyncio.create_task(retry_loop())
        poll_task = None
        if app.state.planner is not None and app.state.voice.configured() and settings.voice_poll_s > 0:
            async def voice_poll() -> None:  # calls that ended, retries due, queued calls (D100), even with the clock paused
                while True:
                    await asyncio.sleep(settings.voice_poll_s)
                    try:
                        await app.state.voice.check()
                    except Exception:  # noqa: BLE001 - keep polling
                        log.exception("voice poll")
            poll_task = asyncio.create_task(voice_poll())
        if app.state.planner is not None:
            async def warm_pool() -> None:  # sandboxes up before the first /optimize (D82)
                try:
                    await run_in_threadpool(app.state.planner.bridge.warm_pool)
                except Exception:  # noqa: BLE001 - /optimize starts them again, or runs locally
                    log.exception("warming the robustness pool failed")
            app.state.warm_task = asyncio.create_task(warm_pool())
        try:
            yield
        finally:
            for task in (retry_task, poll_task):
                if task is not None:
                    task.cancel()
            if app.state.listener is not None:
                await app.state.listener.stop()
            if photon is not None:
                await photon.aclose()
            if app.state.planner is not None:
                await run_in_threadpool(app.state.planner.bridge.close_pool)
            app.state.store.close()

    app = FastAPI(title="Ember backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origin_regex=settings.cors_origin_regex,
                       allow_methods=["*"], allow_headers=["*"])

    def store() -> Store:
        return app.state.store

    def messenger() -> Messenger:
        return app.state.messenger

    def planner() -> Planner:
        if app.state.planner is None:
            raise HTTPException(503, "static mode (SCENARIO unset): no engine")
        return app.state.planner

    @app.get("/health")
    def health() -> dict:
        meta = store().meta()
        listener = app.state.listener
        return {"ok": True, "scenario_id": meta.get("scenario_id"), "plan_version": meta.get("plan_version"),
                "t_s": meta.get("t_s"), "mode": "engine" if app.state.planner is not None else "static",
                "extraction": "on" if app.state.intake and app.state.intake.llm else "off", "photon": "enabled" if messenger().photon is not None else "disabled",
                "photon_listener": listener.status() if listener is not None else None,
                "max_players": settings.max_players, "players": len(store().kv_prefix("player:"))}

    @app.get("/state")
    async def get_state() -> dict:
        if app.state.planner is not None:
            async with app.state.planner.lock:
                return await run_in_threadpool(store().snapshot)
        return await run_in_threadpool(store().snapshot)

    @app.get("/plan/current")
    def plan_current() -> dict:
        plan = store().plan_view()
        if plan is None:
            raise HTTPException(404, "no plan yet")
        return plan

    @app.get("/plan/{version}")
    def plan_version(version: int) -> dict:
        plan = store().plan(version)
        if plan is None:
            raise HTTPException(404, f"no plan version {version}; stored: {store().plan_versions()}")
        return plan

    @app.post("/reports")
    async def post_report(body: dict) -> dict:
        """A structured fact (report.schema.json). `id`, `observed_at_t_s` (= the clock), `confidence`,
        `resolved` default; facts (need / closure_report / facility_status) trigger a replan."""
        try:
            report, plan = await planner().submit_report(body)
        except ReportError as e:
            raise HTTPException(422, str(e)) from e
        return {"report": report, "plan_version": store().meta().get("plan_version"),
                "changes": plan.get("changes", []) if plan else [], "replanned": plan is not None}

    @app.post("/replan")
    async def post_replan() -> dict:
        plan = await planner().replan("manual replan")
        return {"plan_version": plan["version"], "changes": plan.get("changes", [])}

    @app.post("/disruption")
    async def post_disruption(body: DisruptionIn) -> dict:
        """The judge's map controls: close a road, or change a facility (e.g. {"backup_endurance_s": 600})."""
        try:
            if body.close_edges and body.facility_id is None:
                report, plan = await planner().close_road(body.close_edges, note=body.note)
            elif body.facility_id and body.set and not body.close_edges:
                report, plan = await planner().set_facility(body.facility_id, body.set, note=body.note)
            else:
                raise ReportError("send either close_edges, or facility_id + set")
        except ReportError as e:
            raise HTTPException(422, str(e)) from e
        return {"report": report, "plan_version": store().meta().get("plan_version"),
                "changes": plan.get("changes", []) if plan else []}

    async def respond(assignment_id: str, decision: str, body: RespondIn | None) -> dict:
        res = await planner().respond(assignment_id, decision, body.plan_version if body else None)
        if res["stale"]:
            raise HTTPException(409, res["reason"])
        if not res["applied"] and res["reason"] and not res["reason"].startswith("already"):
            raise HTTPException(409, res["reason"])
        if res["applied"] and decision == "confirm" and app.state.guide is not None:
            await app.state.guide.tick()  # confirmed on the console: their phone gets step 1
        return {**res, "plan_version": store().meta().get("plan_version")}

    @app.post("/assignments/{assignment_id}/confirm")
    async def confirm(assignment_id: str, body: RespondIn | None = None) -> dict:
        """The person accepted the offer (web operator console; texts go through the same path)."""
        return await respond(assignment_id, "confirm", body)

    @app.post("/assignments/{assignment_id}/reject")
    async def reject(assignment_id: str, body: RespondIn | None = None) -> dict:
        """The person declined: status `rejected`, replan; that vehicle is never re-offered to them."""
        return await respond(assignment_id, "reject", body)

    @app.post("/simulate")
    async def post_simulate(body: SimulateIn) -> dict:
        """Projected outcome of the current plan ("ember") or the incident-by-incident baseline."""
        return await planner().simulate(body.planner)

    @app.post("/ask")
    async def post_ask(body: AskIn) -> dict:
        """Scripted prompt from the operator console (Task 6), e.g. "What's your backup endurance now?".
        The answer comes back as a text → extraction → facility_status report → replan."""
        from .threads import select_thread
        try:
            thread = select_thread(store(), body.role, body.household_id, body.facility_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        if thread is None:
            raise HTTPException(409, f"no {body.role} thread in the current state")
        view = store().plan_view()
        q = None
        if body.question is None and app.state.outbound is not None and view:
            q = app.state.outbound.next_info_request(view, thread)
        text = body.question or (Outbound.ask(q) if q else DEFAULT_ASK[body.role])
        msg, delivery = await messenger().send_message(thread, text, store().meta().get("plan_version"))
        if q and delivery in ("sent", "dev", "failed"):
            store().kv_set(f"asked:{q['id']}", str(view["version"]))
        return {"message": msg, "delivery": delivery, "info_request": q["id"] if q else None,
                **messenger().delivery_details(thread, delivery)}

    @app.post("/optimize", status_code=202)
    async def post_optimize(seeds: int = 50, k: int = 4) -> dict:
        """Start the robust fan-out in the background; watch WS `scatter_point` events, then `plan`.
        GET /optimize for the outcome. 409 while one is running."""
        p = planner()
        if not (1 <= seeds <= 2000 and 1 <= k <= 8):  # paired worlds per plan; distinct candidates determine total runs
            raise HTTPException(422, "seeds must be 1..2000 and k 1..8")
        if p.optimizing:
            raise HTTPException(409, "an optimization is already running")

        async def run() -> None:
            try:
                await p.optimize(seeds, k)
            except Exception:  # noqa: BLE001 - recorded in last_optimize
                log.exception("optimize failed")

        app.state.optimize_task = asyncio.create_task(run())
        await asyncio.sleep(0)  # let it take the flag before we answer
        return {"status": "started", "seeds": seeds, "k": k}

    @app.get("/optimize")
    def get_optimize() -> dict:
        p = planner()
        return {"running": p.optimizing, "last": p.last_optimize}

    @app.post("/clock")
    async def post_clock(body: ClockIn) -> dict:
        """Move the sim clock (play / scrub). Broadcasts `state`."""
        try:
            state = await planner().set_clock(body.t_s)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"t_s": state["t_s"], "plan_version": state["plan_version"]}

    @app.get("/comparison")
    async def get_comparison(seeds: int = 5) -> dict:
        """Baseline vs EMBER (contracts/comparison.schema.json), cached per plan version."""
        if not 1 <= seeds <= 20:
            raise HTTPException(422, "seeds must be 1..20")
        return await planner().comparison(seeds)

    @app.get("/playback")
    async def get_playback(which: Literal["ember", "baseline"] = "ember") -> dict:
        """The map's replay of the current plan or the baseline (contracts/playback.schema.json)."""
        return await planner().playback(which)

    @app.get("/phones")
    def get_phones() -> list[dict]:
        return messenger().phones_view()

    @app.post("/phones")
    async def post_phone(body: PhoneIn) -> dict:
        """Register a tester phone for a role (and create its Photon shared-line assignment). The tester
        must then text anything to `assigned_number` before EMBER can message them (Photon opt-in rule)."""
        try:
            phone = await messenger().register_phone(body.role, body.handle, body.household_id, body.facility_id,
                                                     locate=body.locate)
        except PhoneConflict as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except PhotonError as e:
            raise HTTPException(502, str(e)) from e
        return phone

    @app.post("/join")
    async def post_join(body: JoinIn) -> dict:
        """Multiplayer (D89): register a phone as a player on the shared iMessage line. The phone must then
        text anything (the QR pre-fills "JOIN EMBER") to `assigned_number`; that first text places it as Player N, and
        EMBER calls it (D100). Anyone can also just call the voice number and join by voice.
        Idempotent per handle; 409 when the drill is full (MAX_PLAYERS) or the phone is a team phone."""
        try:
            return await messenger().register_player(body.handle)
        except DrillFull as e:
            raise HTTPException(409, "drill is full") from e
        except PhoneConflict as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except PhotonError as e:
            raise HTTPException(502, str(e)) from e

    @app.post("/messages")
    async def post_message(body: MessageIn) -> dict:
        """Send a message on a thread (operator console / scripted prompts), as written (a phone's first text in a run
        gets the one-line simulation notice, D100)."""
        msg, delivery = await messenger().send_message(body.thread.as_thread(), body.text, body.plan_version, body.assignment_id)
        return {"message": msg, "delivery": delivery, **messenger().delivery_details(msg["thread"], delivery)}

    def question_queue() -> list[dict]:
        from .threads import phone_for_thread
        items = sorted((json.loads(v) for v in store().kv_prefix("question:").values()), key=lambda q: q["t_s"])
        for q in items:
            phone = phone_for_thread(store(), q["thread"])
            q["handle"] = phone["handle"] if phone else None
        return items

    @app.get("/questions")
    def get_questions(open_only: bool = False) -> list[dict]:
        """Questions the plan couldn't answer (D60): each already got the person's situation; a coordinator
        can reply with POST /questions/{report_id}/answer."""
        return [q for q in question_queue() if not (open_only and q["answer"])]

    @app.post("/questions/{report_id}/answer")
    async def answer_question(report_id: str, body: AnswerIn) -> dict:
        raw = store().kv_get(f"question:{report_id}")
        if raw is None:
            raise HTTPException(404, f"no question {report_id} in this run")
        q = json.loads(raw)
        msg, delivery = await messenger().send_message(q["thread"], body.text, store().meta().get("plan_version"))
        if delivery in ("sent", "dev", "failed"):  # failed is retried; anything else wasn't delivered
            store().kv_set(f"question:{report_id}", json.dumps({**q, "answer": {"text": body.text, "message_id": msg["id"]}}))
        return {"message": msg, "delivery": delivery, **messenger().delivery_details(q["thread"], delivery)}

    @app.get("/calls")
    def get_calls() -> dict:
        """Calls in progress and finished ones (D80): who, why, how many turns, and what each changed."""
        return app.state.voice.calls_view()

    @app.post("/calls")
    async def post_call(body: CallIn) -> dict:
        """Call a registered phone now (D74). The call opens with what the thread most needs from them."""
        try:
            return await app.state.voice.call(body.handle, reason="console")
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except RuntimeError as e:
            raise HTTPException(502, str(e)) from e

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        hub: Hub = app.state.hub
        if app.state.planner is not None:
            async with app.state.planner.lock:
                await hub.connect(websocket, await run_in_threadpool(store().snapshot))
        else:
            await hub.connect(websocket, await run_in_threadpool(store().snapshot))
        try:
            while True:  # clients don't send anything we act on; this just notices the disconnect
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(websocket)

    if settings.dev_endpoints:
        @app.post("/dev/reset")
        async def dev_reset() -> dict:
            """Reseed from SEED_STATE (rehearsals) and push the fresh state to every client."""
            if app.state.planner is not None:
                state = await app.state.planner.bootstrap(settings.start_t_s)
            else:
                await run_in_threadpool(store().seed, load_seed(settings.seed_state))
                state = await run_in_threadpool(store().snapshot)
            await app.state.hub.broadcast("state", state, state["t_s"])
            return {"ok": True, "plan_version": state["plan_version"]}

        @app.post("/dev/inbound")
        async def dev_inbound(body: DevInboundIn) -> dict:
            """Pretend a tester texted: same path as a real Photon message (store → WS → hooks)."""
            try:
                if body.handle is not None:
                    msg = await messenger().phone_inbound(body.handle, body.text)
                    if msg is None:  # no household yet: handled by the Locator (location first)
                        return {"message": None, "lobby": messenger().lobby_log(normalize_handle(body.handle))}
                else:
                    msg = await messenger().simulate_inbound(body.role, body.text, body.household_id, body.facility_id)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            if msg is None:
                raise HTTPException(409, f"no {body.role} thread in the current state")
            return {"message": msg}

    return app


app = create_app()
