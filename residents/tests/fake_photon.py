"""A fake Photon API at the HTTP layer: the real PhotonClient runs; only the network is replaced."""
import json

import httpx

from residents.photon import PhotonClient

PROJECT = "pho_prj_0test00000000000000000000000"
LINE = "+16175550000"  # the shared line Photon assigns


class FakePhoton:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.fail_sends = 0          # next N sends return 503
        self.reject_sends = False    # sends return 403
        self.received_items: list[dict] = []
        self.n_sent = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        path = req.url.path.removeprefix(f"/v1/projects/{PROJECT}/")
        if path == "platforms/imessage/assignments" and req.method == "POST":
            body = json.loads(req.content)
            return httpx.Response(201, json={"assignmentId": f"asg-{body['handle'][-4:]}", "assignedPhoneNumber": LINE,
                                             "handle": body["handle"], "platform": "imessage", "projectId": PROJECT,
                                             "createdAt": "2026-10-17T00:00:00Z", "updatedAt": "2026-10-17T00:00:00Z"})
        if path.startswith("platforms/imessage/assignments/") and req.method == "DELETE":
            return httpx.Response(200, json={"assignmentId": path.rsplit("/", 1)[-1], "releasedAt": "2026-10-17T00:10:00Z"})
        if path == "messages" and req.method == "POST":
            if self.reject_sends:
                return httpx.Response(403, json={"code": "SHARED_LINE_NOT_OPTED_IN"})
            if self.fail_sends > 0:
                self.fail_sends -= 1
                return httpx.Response(503, json={"code": "unavailable"})
            self.n_sent += 1
            return httpx.Response(202, json={"id": f"pho_msg_out{self.n_sent}", "status": "accepted"})
        if path == "messages" and req.method == "GET":
            return httpx.Response(200, json={"items": self.received_items})
        return httpx.Response(404, json={"code": "not_found", "path": path})

    def client(self) -> PhotonClient:
        return PhotonClient("pho_sk_test", PROJECT, base_url="https://photon.test",
                            transport=httpx.MockTransport(self.handler), max_attempts=3)

    def sends(self) -> list[dict]:
        return [json.loads(r.content) | {"_key": r.headers.get("idempotency-key")}
                for r in self.requests if r.method == "POST" and r.url.path.endswith("/messages")]


def received(msg_id: str, handle: str, text: str, created: str | None = None, content_type="text") -> dict:
    """A Photon ReceivedImessageMessage (fields per openapi). `created` defaults to now (UTC), so it is
    never "before this run" (Messenger ignores texts sent before the last reset)."""
    if created is None:
        from datetime import datetime, timezone
        created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    content = {"type": content_type, "format": "plain", "text": text} if content_type == "text" else {"type": content_type}
    return {"id": msg_id, "projectId": PROJECT, "platform": "imessage", "status": "received", "content": content,
            "sentBy": {"id": f"pho_usr_{handle[-4:]}", "handle": handle, "platform": "imessage"},
            "receivedBy": {"id": "pho_usr_line", "handle": LINE, "platform": "imessage"},
            "space": {"id": f"pho_spc_{handle[-4:]}", "participantIds": ["pho_usr_line", f"pho_usr_{handle[-4:]}"]},
            "metadata": {}, "createdAt": created, "updatedAt": created, "timestamps": {"receivedAt": created}}
