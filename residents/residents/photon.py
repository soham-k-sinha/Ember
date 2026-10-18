"""Photon 2.0 (Beta) transport: REST over httpx + the Socket.IO event stream + a polling fallback.

Shapes are from https://api.photon.codes/openapi.json and photon.codes/docs/beta/websocket/*
(checked 2026-10-17). Everything is project-scoped: /v1/projects/{projectId}/...
- Assign a tester:  POST platforms/imessage/assignments {handle} → {assignmentId, assignedPhoneNumber}
- Send:             POST messages {spaceId, senderId, content:{type:"text", format:"plain", text}}
                    (Idempotency-Key required; a shared line may only reply to a peer who texted it first)
- Receive:          Socket.IO at path /v1/projects/{id}/events/ws, emit `subscribe {startSeq}` on every
                    connect, then `delivery(event, {seq})`. Events can be redelivered → dedupe by message id.
                    Process serially; persist `seq` only after the handler succeeded.
- Fallback:         GET messages?direction=received&createdSince=… every 2 s while the socket is down.
- Joining (D89):    a shared iMessage line only delivers texts from handles assigned to it, so a player is
                    registered first (POST /join → create_assignment), then texts the line.

This module knows nothing about Ember state; `messaging.py` decides what an inbound message means.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger("residents.photon")

API = "https://api.photon.codes"
API_VERSION = "2026-07-01"
RETRY_STATUS = {429, 500, 502, 503, 504}


async def _backoff(seconds: float) -> None:
    """Retry waits go through here so tests can skip them without patching the global asyncio.sleep."""
    await asyncio.sleep(seconds)


class PhotonError(RuntimeError):
    def __init__(self, status: int, body: Any):
        self.status, self.body = status, body
        code = body.get("code") if isinstance(body, dict) else None
        super().__init__(f"Photon HTTP {status}{f' {code}' if code else ''}: {str(body)[:300]}")


@dataclass(frozen=True)
class Inbound:
    """A text a tester sent to our line, reduced to what the backend needs."""
    external_id: str        # Photon message id (dedupe key)
    handle: str             # sender, E.164
    text: str
    space_id: str           # the direct chat; needed to reply
    peer_user_id: str       # Photon user id of the sender
    agent_user_id: str | None  # Photon user id of our line (the reply's senderId)
    created_at: str | None


def parse_inbound(obj: dict) -> Inbound | None:
    """A Photon message object (event.data.object or a GET /messages item) → Inbound, or None if it
    isn't a received text (read receipts, typing indicators, attachments, our own sends)."""
    if obj.get("status") != "received":
        return None
    content = obj.get("content") or {}
    if content.get("type") != "text" or not (content.get("text") or "").strip():
        return None
    sent_by = obj.get("sentBy") or {}
    space = obj.get("space") or {}
    peer = sent_by.get("id")
    agent = (obj.get("receivedBy") or {}).get("id")
    if agent is None:  # direct chat: the other participant is our line
        agent = next((p for p in space.get("participantIds", []) if p != peer), None)
    if not (obj.get("id") and sent_by.get("handle") and space.get("id") and peer):
        log.warning("received message missing ids, ignored: %s", str(obj)[:300])
        return None
    return Inbound(external_id=obj["id"], handle=sent_by["handle"], text=content["text"], space_id=space["id"],
                   peer_user_id=peer, agent_user_id=agent, created_at=obj.get("createdAt"))


class PhotonClient:
    def __init__(self, api_key: str, project_id: str, base_url: str = API,
                 transport: httpx.AsyncBaseTransport | None = None, max_attempts: int = 4):
        if not api_key or not project_id:
            raise ValueError("PHOTON_API_KEY and PHOTON_PROJECT_ID are required")
        self.api_key, self.project_id, self.base_url = api_key, project_id, base_url
        self.max_attempts = max_attempts
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=15.0,
                                       headers={"Authorization": f"Bearer {api_key}"})

    async def aclose(self) -> None:
        await self._http.aclose()

    def _p(self, path: str) -> str:
        return f"/v1/projects/{self.project_id}/{path}"

    async def _request(self, method: str, path: str, *, json: dict | None = None,
                       params: dict | None = None, idempotency_key: str | None = None) -> Any:
        """Retries 429/5xx/network errors with backoff, reusing the same Idempotency-Key so a retry
        can never send a text twice."""
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = await self._http.request(method, self._p(path), json=json, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt == self.max_attempts:
                    raise
                log.info("photon %s %s: %r, retrying", method, path, e)
            else:
                if r.status_code < 300:
                    return r.json() if r.content else None
                body: Any
                try:
                    body = r.json()
                except ValueError:
                    body = r.text
                if r.status_code not in RETRY_STATUS or attempt == self.max_attempts:
                    raise PhotonError(r.status_code, body)
                retry_after = r.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    await _backoff(min(float(retry_after), 10.0))
                    continue
            await _backoff(min(0.5 * 2 ** (attempt - 1), 4.0) * (1 + random.random() * 0.2))
        raise AssertionError("unreachable")

    # ---------- REST ----------
    async def create_assignment(self, handle: str, generation: int = 0) -> dict:
        """Map a tester's phone onto a shared iMessage line (one seat). Idempotent per handle and generation: after a
        release the next generation creates a new assignment instead of replaying the released one."""
        return await self._request("POST", "platforms/imessage/assignments", json={"handle": handle},
                                   idempotency_key=f"ember-assign-{handle}" + (f"-{generation}" if generation else ""))

    async def release_assignment(self, assignment_id: str) -> dict:
        """Free an assignment's seat and handle (DELETE; repeating it is safe)."""
        return await self._request("DELETE", f"platforms/imessage/assignments/{assignment_id}")

    async def send_text(self, space_id: str, sender_id: str, text: str, idempotency_key: str) -> dict:
        return await self._request("POST", "messages", idempotency_key=idempotency_key, json={
            "spaceId": space_id, "senderId": sender_id,
            "content": {"type": "text", "format": "plain", "text": text}})

    async def list_received(self, since: datetime) -> list[dict]:
        """Received messages on every line created at/after `since`, oldest first
        (first page only; we poll every 2 s)."""
        res = await self._request("GET", "messages", params={
            "direction": "received", "orderBy": "created_at", "order": "asc",
            "pageSize": 100, "createdSince": since.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")})
        return res.get("items", [])


OnMessage = Callable[[Inbound], Awaitable[Any]]


class PhotonListener:
    """Socket.IO event stream with a durable cursor, plus REST polling while the socket is down.
    Both paths call `on_message`; it must be idempotent (dedupe by Inbound.external_id)."""

    CURSOR_KEY = "photon_cursor"
    POLL_SINCE_KEY = "photon_poll_since"
    MAX_LOOKBACK_S = 600.0  # polling never fetches texts older than this, however stale the marker is

    def __init__(self, client: PhotonClient, store: Any, on_message: OnMessage,
                 poll_interval_s: float = 2.0, poll_after_down_s: float = 5.0, sio_factory: Callable[[], Any] | None = None):
        self.client, self.store, self.on_message = client, store, on_message
        self.poll_interval_s, self.poll_after_down_s = poll_interval_s, poll_after_down_s
        self._sio_factory = sio_factory
        self.subscribed = False
        self.down_since: float | None = None
        self.events_seen = 0
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._tasks: list[asyncio.Task] = []
        self._sio: Any = None
        self._http_session: Any = None

    @property
    def cursor(self) -> int:
        return int(self.store.kv_get(self.CURSOR_KEY, "0"))

    def status(self) -> dict:
        return {"socket": "subscribed" if self.subscribed else "down", "cursor": self.cursor,
                "events_seen": self.events_seen, "polling": self._polling_active()}

    # ---------- lifecycle ----------
    async def start(self) -> None:
        if self.store.kv_get(self.POLL_SINCE_KEY) is None:
            self.store.kv_set(self.POLL_SINCE_KEY, datetime.now(timezone.utc).isoformat())
        self.down_since = time.monotonic()
        self._tasks = [asyncio.create_task(self._worker(), name="photon-worker"),
                       asyncio.create_task(self._poller(), name="photon-poller"),
                       asyncio.create_task(self._socket(), name="photon-socket")]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._close_sio()

    # ---------- socket ----------
    def _make_sio(self) -> Any:
        if self._sio_factory:
            return self._sio_factory()
        import ssl

        import aiohttp
        import certifi
        import socketio
        # certifi's CA bundle, not the OS store: python.org builds on macOS ship without CA certs, so
        # aiohttp's default context fails with CERTIFICATE_VERIFY_FAILED (httpx already uses certifi).
        self._http_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())))
        return socketio.AsyncClient(reconnection=True, reconnection_delay=1, reconnection_delay_max=10,
                                    logger=False, http_session=self._http_session)

    def _wire(self, sio: Any) -> None:
        @sio.event
        async def connect():
            asyncio.create_task(self._subscribe(sio))

        @sio.event
        async def disconnect(*_):
            self._mark_down()

        @sio.on("delivery")
        async def delivery(event, metadata=None):
            await self._queue.put((event, metadata or {}))

        @sio.event
        async def connect_error(data=None):
            log.warning("photon socket connect_error: %s", data)

        @sio.on("delivery_error")
        async def delivery_error(err):
            log.warning("photon delivery_error: %s", err)

    async def _socket(self) -> None:
        """Connect, and keep trying forever. Socket.IO's own reconnection only covers drops after a
        successful connect; a first connect that times out (Photon slow for a moment) used to leave us on
        polling for the rest of the run."""
        delay = 1.0
        while True:
            sio = self._sio = self._make_sio()
            self._wire(sio)
            try:
                await sio.connect(self.client.base_url, socketio_path=f"/v1/projects/{self.client.project_id}/events/ws",
                                  transports=["websocket"], headers={"Authorization": f"Bearer {self.client.api_key}"},
                                  wait_timeout=10)
                delay = 1.0
                await sio.wait()  # returns only if the client gives up for good
                log.warning("photon socket closed; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - polling covers the gap; try again
                log.warning("photon socket connect failed: %r; retrying in %.0fs (polling meanwhile)", e, delay)
            self._mark_down()
            await self._close_sio()
            await _backoff(delay)
            delay = min(delay * 2, 30.0)

    async def _close_sio(self) -> None:
        if self._sio is not None:
            try:
                await self._sio.disconnect()
            except Exception:  # noqa: BLE001
                pass
        if self._http_session is not None:
            try:
                await self._http_session.close()
            except Exception:  # noqa: BLE001
                pass
            self._http_session = None

    async def _subscribe(self, sio: Any) -> None:
        try:
            res = await sio.call("subscribe", {"startSeq": self.cursor, "apiVersion": API_VERSION}, timeout=10)
        except Exception as e:  # noqa: BLE001
            log.warning("photon subscribe failed: %r; reconnecting", e)
            await sio.disconnect()
            return
        if isinstance(res, dict) and res.get("ok"):
            self.subscribed, self.down_since = True, None
            self._mark_polled_now()  # the socket's cursor covers everything from here
            log.info("photon subscribed (cursor %s, connection %s)", self.cursor, res.get("connectionId"))
        else:
            log.error("photon subscribe rejected: %s", res)

    def _mark_down(self) -> None:
        if self.subscribed or self.down_since is None:
            self.down_since = time.monotonic()
        self.subscribed = False

    async def _worker(self) -> None:
        """Serial: one delivery at a time, cursor saved only after it's handled."""
        while True:
            event, meta = await self._queue.get()
            seq = meta.get("seq")
            try:
                if isinstance(seq, int) and seq <= self.cursor:
                    continue  # replayed after a reconnect
                self.events_seen += 1
                if event.get("type") == "message.received":
                    inbound = parse_inbound((event.get("data") or {}).get("object") or {})
                    if inbound:
                        await self._handle(inbound)
                elif event.get("type") in ("message.failed",):
                    log.warning("photon %s: %s", event.get("type"), str(event.get("data"))[:300])
                if isinstance(seq, int):
                    self.store.kv_set(self.CURSOR_KEY, str(seq))
            finally:
                self._queue.task_done()

    async def _handle(self, inbound: Inbound) -> None:
        for attempt in range(3):
            try:
                await self.on_message(inbound)
                return
            except Exception:  # noqa: BLE001 - one bad message must not stop the stream
                log.exception("inbound handler failed (attempt %d) for %s", attempt + 1, inbound.external_id)
                await _backoff(0.2 * (attempt + 1))
        log.error("dropping inbound %s after 3 failures: %r", inbound.external_id, inbound.text[:80])

    # ---------- polling fallback ----------
    def _polling_active(self) -> bool:
        if self.subscribed or self.down_since is None:
            return False
        return time.monotonic() - self.down_since >= self.poll_after_down_s

    def _mark_polled_now(self) -> None:
        self.store.kv_set(self.POLL_SINCE_KEY, datetime.now(timezone.utc).isoformat())

    async def _poller(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval_s)
            if self.subscribed:
                self._mark_polled_now()  # keep the fallback's window fresh while the socket is healthy
                continue
            if not self._polling_active():
                continue
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("photon poll failed: %r", e)

    async def poll_once(self) -> int:
        since = datetime.fromisoformat(self.store.kv_get(self.POLL_SINCE_KEY))
        floor = datetime.now(timezone.utc) - timedelta(seconds=self.MAX_LOOKBACK_S)
        since = max(since, floor)
        items = await self.client.list_received(since - timedelta(seconds=5))  # overlap; dedupe makes it safe
        newest = since
        n = 0
        for obj in items:
            inbound = parse_inbound(obj)
            if inbound:
                await self._handle(inbound)
                n += 1
            if obj.get("createdAt"):
                newest = max(newest, datetime.fromisoformat(obj["createdAt"].replace("Z", "+00:00")))
        self.store.kv_set(self.POLL_SINCE_KEY, newest.isoformat())
        return n
