"""WebSocket hub for the web app (WS /ws).

Every event is an envelope {type, seq, t_s, data} (draft schema: residents/ws-events.schema.json).
`seq` goes up by one per broadcast, so a client can tell it missed something and re-fetch GET /state.
The `state` event sent on connect carries the current seq without incrementing it: "this is the
state as of event N; the next broadcast is N+1".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("residents.bus")

EVENT_TYPES = ("state", "plan", "assignment", "message", "report", "scatter_point", "metrics")
SEND_TIMEOUT_S = 2.0  # a stuck browser tab must not stall the replan loop


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.seq = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def envelope(type_: str, data: Any, t_s: float, seq: int) -> dict:
        if type_ not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type_!r}")
        return {"type": type_, "seq": seq, "t_s": t_s, "data": data}

    async def connect(self, ws: WebSocket, state: dict) -> None:
        await ws.accept()
        async with self._lock:  # no broadcast can slip between the state event and joining the set
            await ws.send_json(self.envelope("state", state, state["t_s"], self.seq))
            self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, type_: str, data: Any, t_s: float) -> dict:
        async with self._lock:
            self.seq += 1
            msg = self.envelope(type_, data, t_s, self.seq)
            clients = list(self.clients)
            results = await asyncio.gather(
                *(asyncio.wait_for(c.send_json(msg), SEND_TIMEOUT_S) for c in clients), return_exceptions=True)
            for c, r in zip(clients, results):
                if isinstance(r, BaseException):
                    log.info("dropping ws client after failed send: %r", r)
                    self.clients.discard(c)
        return msg
