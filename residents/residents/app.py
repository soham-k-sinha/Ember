"""Ember backend: FastAPI app. Run from residents/: `uv run uvicorn residents.app:app --reload`."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from .bus import Hub
from .config import CONTRACTS, Settings
from .db import Store

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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = open_store(settings)
        app.state.hub = Hub()
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="Ember backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["*"], allow_headers=["*"])

    def store() -> Store:
        return app.state.store

    @app.get("/health")
    def health() -> dict:
        meta = store().meta()
        return {"ok": True, "scenario_id": meta.get("scenario_id"), "plan_version": meta.get("plan_version"),
                "t_s": meta.get("t_s"), "photon": "enabled" if settings.photon_enabled else "disabled"}

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

    return app


app = create_app()
