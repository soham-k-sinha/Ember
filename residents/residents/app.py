"""Ember backend: FastAPI app. Run from residents/: `uv run uvicorn residents.app:app --reload`."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .bus import Hub
from .config import CONTRACTS, Settings
from .db import Store
from .messaging import Messenger
from .photon import PhotonClient, PhotonError, PhotonListener

log = logging.getLogger("residents")
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


def open_store(settings: Settings) -> Store:
    store = Store(settings.db_path)
    if settings.reset_on_start or store.is_empty():
        store.seed(load_seed(settings.seed_state))
        log.info("seeded %s from %s", settings.db_path, settings.seed_state)
    else:
        log.info("using existing %s (plan v%s); RESET_ON_START=1 or POST /dev/reset to reseed",
                 settings.db_path, store.meta().get("plan_version"))
    return store


class PhoneIn(BaseModel):
    role: Literal["resident", "operator"]
    handle: str = Field(min_length=3, description="the tester's phone, e.g. 4135550100 or +14135550100")


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


class DevInboundIn(BaseModel):
    role: Literal["resident", "operator"]
    text: str = Field(min_length=1, max_length=1000)


def create_app(settings: Settings | None = None, photon_client: PhotonClient | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = open_store(settings)
        app.state.hub = Hub()
        photon = photon_client
        if photon is None and settings.photon_enabled:
            photon = PhotonClient(settings.photon_api_key, settings.photon_project_id)
        app.state.messenger = Messenger(app.state.store, app.state.hub, photon)
        app.state.listener = None
        if photon is not None and settings.photon_listen:
            app.state.listener = PhotonListener(photon, app.state.store, app.state.messenger.handle_inbound)
            await app.state.listener.start()
        try:
            yield
        finally:
            if app.state.listener is not None:
                await app.state.listener.stop()
            if photon is not None:
                await photon.aclose()
            app.state.store.close()

    app = FastAPI(title="Ember backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["*"], allow_headers=["*"])

    def store() -> Store:
        return app.state.store

    def messenger() -> Messenger:
        return app.state.messenger

    @app.get("/health")
    def health() -> dict:
        meta = store().meta()
        listener = app.state.listener
        return {"ok": True, "scenario_id": meta.get("scenario_id"), "plan_version": meta.get("plan_version"),
                "t_s": meta.get("t_s"), "photon": "enabled" if messenger().photon is not None else "disabled",
                "photon_listener": listener.status() if listener is not None else None}

    @app.get("/state")
    def get_state() -> dict:
        return store().snapshot()

    @app.get("/plan/current")
    def plan_current() -> dict:
        plan = store().current_plan()
        if plan is None:
            raise HTTPException(404, "no plan yet")
        return plan

    @app.get("/plan/{version}")
    def plan_version(version: int) -> dict:
        plan = store().plan(version)
        if plan is None:
            raise HTTPException(404, f"no plan version {version}; stored: {store().plan_versions()}")
        return plan

    @app.get("/phones")
    def get_phones() -> list[dict]:
        return messenger().phones_view()

    @app.post("/phones")
    async def post_phone(body: PhoneIn) -> dict:
        """Register a tester phone for a role (and create its Photon shared-line assignment). The tester
        must then text anything to `assigned_number` before EMBER can message them (Photon opt-in rule)."""
        try:
            await messenger().register_phone(body.role, body.handle)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except PhotonError as e:
            raise HTTPException(502, str(e)) from e
        return next(p for p in messenger().phones_view() if p["role"] == body.role)

    @app.post("/messages")
    async def post_message(body: MessageIn) -> dict:
        """Send a message on a thread (operator console / scripted prompts). Text gets the drill prefix."""
        msg, delivery = await messenger().send_message(body.thread.as_thread(), body.text, body.plan_version, body.assignment_id)
        return {"message": msg, "delivery": delivery}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        hub: Hub = app.state.hub
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
            seed = load_seed(settings.seed_state)
            await run_in_threadpool(store().seed, seed)
            state = await run_in_threadpool(store().snapshot)
            await app.state.hub.broadcast("state", state, state["t_s"])
            return {"ok": True, "plan_version": state["plan_version"]}

        @app.post("/dev/inbound")
        async def dev_inbound(body: DevInboundIn) -> dict:
            """Pretend a tester texted: same path as a real Photon message (store → WS → hooks)."""
            msg = await messenger().simulate_inbound(body.role, body.text)
            if msg is None:
                raise HTTPException(409, f"no {body.role} thread in the current state")
            return {"message": msg}

    return app


app = create_app()
