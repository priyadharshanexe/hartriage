"""A stand-in for the parts of the Zendesk and Freshdesk APIs that HAR Triage uses.

    uvicorn tools.fake_helpdesk.app:app --port 8290     (docker compose runs it)

* Zendesk lives under /zendesk/<subdomain>/api/v2/..., Freshdesk under
  /freshdesk/<domain>/api/v2/..., with the same paths and response shapes as the
  real APIs for the calls the clients make.
* /_admin/... creates tickets with attachments, adds the trigger tag and fires the
  webhook (signed like Zendesk does, or with the secret header Freshdesk sends),
  and can make the next call fail with 429 to exercise retries.
* / is a small page for demos: create a ticket from a sample HAR, tag it, and
  watch the private note arrive.

State is in memory. This is test tooling, not a mock of everything either API does.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import itertools
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

app = FastAPI(title="Fake helpdesk")
_ids = itertools.count(1001)
SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "samples"


@dataclass
class FakeAttachment:
    id: int
    filename: str
    content: bytes
    content_type: str = "application/json"
    redacted: bool = False


@dataclass
class Comment:
    id: int
    body: str
    public: bool
    attachments: list[FakeAttachment] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class FakeTicket:
    id: int
    platform: str
    account: str
    subject: str
    tags: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)


TICKETS: dict[tuple[str, str, int], FakeTicket] = {}
UPLOADS: dict[str, FakeAttachment] = {}
FAIL_NEXT: dict[str, tuple[int, int]] = {}  # platform -> (status, retry_after)
CALLS: list[str] = []


def _ticket(platform: str, account: str, ticket_id: int) -> FakeTicket | None:
    return TICKETS.get((platform, account, ticket_id))


def _gate(platform: str, request: Request) -> Response | None:
    CALLS.append(f"{request.method} {request.url.path}")
    if not request.headers.get("authorization"):
        return JSONResponse({"error": "Couldn't authenticate you"}, 401)
    if platform in FAIL_NEXT:
        status, retry = FAIL_NEXT.pop(platform)
        return JSONResponse({"error": "rate limited"}, status, headers={"Retry-After": str(retry)})
    return None


def _not_found() -> JSONResponse:
    return JSONResponse({"error": "RecordNotFound"}, 404)


# ------------------------------------------------------------------------ Zendesk


def _zd_attachment(account: str, a: FakeAttachment, base: str) -> dict[str, Any]:
    return {
        "id": a.id,
        "file_name": "redacted.txt" if a.redacted else a.filename,
        "content_url": f"{base}/zendesk/{account}/attachments/{a.id}/{a.filename}",
        "content_type": a.content_type,
        "size": len(a.content),
    }


@app.get("/zendesk/{account}/api/v2/users/me.json")
def zd_me(account: str, request: Request) -> Response:
    return _gate("zendesk", request) or JSONResponse(
        {"user": {"id": 42, "name": "Fake Zendesk Agent"}}
    )


@app.get("/zendesk/{account}/api/v2/tickets/{ticket_id}.json")
def zd_ticket(account: str, ticket_id: int, request: Request) -> Response:
    if (gate := _gate("zendesk", request)) is not None:
        return gate
    t = _ticket("zendesk", account, ticket_id)
    if t is None:
        return _not_found()
    return JSONResponse({"ticket": {"id": t.id, "subject": t.subject, "tags": t.tags}})


@app.get("/zendesk/{account}/api/v2/tickets/{ticket_id}/comments.json")
def zd_comments(account: str, ticket_id: int, request: Request) -> Response:
    if (gate := _gate("zendesk", request)) is not None:
        return gate
    t = _ticket("zendesk", account, ticket_id)
    if t is None:
        return _not_found()
    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "comments": [
                {
                    "id": c.id,
                    "body": c.body,
                    "html_body": c.body,
                    "public": c.public,
                    "attachments": [_zd_attachment(account, a, base) for a in c.attachments],
                }
                for c in t.comments
            ],
            "next_page": None,
        }
    )


@app.put("/zendesk/{account}/api/v2/tickets/{ticket_id}.json")
async def zd_update(account: str, ticket_id: int, request: Request) -> Response:
    if (gate := _gate("zendesk", request)) is not None:
        return gate
    t = _ticket("zendesk", account, ticket_id)
    if t is None:
        return _not_found()
    data = (await request.json()).get("ticket", {})
    events: list[dict[str, Any]] = []
    if "comment" in data:
        c = data["comment"]
        attachments = [UPLOADS.pop(token) for token in c.get("uploads", []) if token in UPLOADS]
        comment = Comment(
            next(_ids),
            c.get("html_body") or c.get("body") or "",
            bool(c.get("public", True)),
            attachments,
        )
        t.comments.append(comment)
        events.append({"id": comment.id, "type": "Comment", "public": comment.public})
    for tag in data.get("remove_tags", []):
        if tag in t.tags:
            t.tags.remove(tag)
    for tag in data.get("additional_tags", []):
        if tag not in t.tags:
            t.tags.append(tag)
    return JSONResponse(
        {"ticket": {"id": t.id, "tags": t.tags}, "audit": {"id": next(_ids), "events": events}}
    )


@app.post("/zendesk/{account}/api/v2/uploads.json")
async def zd_upload(account: str, filename: str, request: Request) -> Response:
    if (gate := _gate("zendesk", request)) is not None:
        return gate
    token = uuid.uuid4().hex
    UPLOADS[token] = FakeAttachment(next(_ids), filename, await request.body())
    return JSONResponse({"upload": {"token": token}}, 201)


@app.put(
    "/zendesk/{account}/api/v2/tickets/{ticket_id}/comments/{comment_id}/attachments/{attachment_id}/redact.json"
)
def zd_redact(
    account: str, ticket_id: int, comment_id: int, attachment_id: int, request: Request
) -> Response:
    if (gate := _gate("zendesk", request)) is not None:
        return gate
    t = _ticket("zendesk", account, ticket_id)
    for c in t.comments if t else []:
        for a in c.attachments:
            if a.id == attachment_id and c.id == comment_id:
                a.redacted, a.content = True, b""
                return JSONResponse({"attachment": {"id": a.id, "file_name": "redacted.txt"}})
    return _not_found()


@app.get("/zendesk/{account}/attachments/{attachment_id}/{name}")
def zd_download(account: str, attachment_id: int, name: str) -> Response:
    for t in TICKETS.values():
        for c in t.comments:
            for a in c.attachments:
                if a.id == attachment_id:
                    return Response(a.content, media_type=a.content_type)
    return _not_found()


# ---------------------------------------------------------------------- Freshdesk


def _fd_attachment(account: str, a: FakeAttachment, base: str) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.filename,
        "content_type": a.content_type,
        "size": len(a.content),
        "attachment_url": f"{base}/freshdesk/{account}/files/{a.id}",
    }


@app.get("/freshdesk/{account}/api/v2/agents/me")
def fd_me(account: str, request: Request) -> Response:
    return _gate("freshdesk", request) or JSONResponse(
        {"id": 7, "contact": {"name": "Fake Freshdesk Agent"}}
    )


@app.get("/freshdesk/{account}/api/v2/tickets/{ticket_id}")
def fd_ticket(account: str, ticket_id: int, request: Request) -> Response:
    if (gate := _gate("freshdesk", request)) is not None:
        return gate
    t = _ticket("freshdesk", account, ticket_id)
    if t is None:
        return _not_found()
    base = str(request.base_url).rstrip("/")
    first = t.comments[0] if t.comments else None
    return JSONResponse(
        {
            "id": t.id,
            "subject": t.subject,
            "tags": t.tags,
            "attachments": [
                _fd_attachment(account, a, base) for a in (first.attachments if first else [])
            ],
        }
    )


@app.get("/freshdesk/{account}/api/v2/tickets/{ticket_id}/conversations")
def fd_conversations(account: str, ticket_id: int, request: Request, page: int = 1) -> Response:
    if (gate := _gate("freshdesk", request)) is not None:
        return gate
    t = _ticket("freshdesk", account, ticket_id)
    if t is None:
        return _not_found()
    base = str(request.base_url).rstrip("/")
    items = (
        [
            {
                "id": c.id,
                "body": c.body,
                "private": not c.public,
                "attachments": [_fd_attachment(account, a, base) for a in c.attachments],
            }
            for c in t.comments[1:]
        ]
        if page == 1
        else []
    )
    return JSONResponse(items)


@app.post("/freshdesk/{account}/api/v2/tickets/{ticket_id}/notes")
async def fd_note(account: str, ticket_id: int, request: Request) -> Response:
    if (gate := _gate("freshdesk", request)) is not None:
        return gate
    t = _ticket("freshdesk", account, ticket_id)
    if t is None:
        return _not_found()
    attachments: list[FakeAttachment] = []
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        body = str(form.get("body") or "")
        private = str(form.get("private")) == "true"
        for item in form.getlist("attachments[]"):
            if hasattr(item, "read"):
                attachments.append(
                    FakeAttachment(next(_ids), getattr(item, "filename", "file"), await item.read())
                )
    else:
        data = await request.json()
        body, private = str(data.get("body") or ""), bool(data.get("private"))
    comment = Comment(next(_ids), body, not private, attachments)
    t.comments.append(comment)
    return JSONResponse({"id": comment.id, "body": body, "private": private}, 201)


@app.put("/freshdesk/{account}/api/v2/tickets/{ticket_id}")
async def fd_update(account: str, ticket_id: int, request: Request) -> Response:
    if (gate := _gate("freshdesk", request)) is not None:
        return gate
    t = _ticket("freshdesk", account, ticket_id)
    if t is None:
        return _not_found()
    data = await request.json()
    if "tags" in data:
        t.tags = list(data["tags"])
    return JSONResponse({"id": t.id, "tags": t.tags})


@app.delete("/freshdesk/{account}/api/v2/attachments/{attachment_id}")
def fd_delete_attachment(account: str, attachment_id: int, request: Request) -> Response:
    if (gate := _gate("freshdesk", request)) is not None:
        return gate
    for t in TICKETS.values():
        for c in t.comments:
            for a in list(c.attachments):
                if a.id == attachment_id:
                    c.attachments.remove(a)
                    return Response(status_code=204)
    return _not_found()


@app.get("/freshdesk/{account}/files/{attachment_id}")
def fd_download(account: str, attachment_id: int) -> Response:
    for t in TICKETS.values():
        for c in t.comments:
            for a in c.attachments:
                if a.id == attachment_id:
                    return Response(a.content, media_type=a.content_type)
    return _not_found()


# --------------------------------------------------------------------------- admin


@app.post("/_admin/tickets")
async def create_ticket(request: Request) -> JSONResponse:
    data = await request.json()
    attachments = []
    for a in data.get("attachments", []):
        content = (
            base64.b64decode(a["content_b64"])
            if "content_b64" in a
            else (SAMPLES / a["sample"]).read_bytes()
        )
        attachments.append(FakeAttachment(next(_ids), a["filename"], content))
    t = FakeTicket(
        next(_ids),
        data["platform"],
        data["account"],
        data.get("subject", "Page is broken"),
        list(data.get("tags", [])),
    )
    t.comments.append(
        Comment(
            next(_ids),
            data.get("description", "Please see the attached HAR file."),
            True,
            attachments,
        )
    )
    TICKETS[(t.platform, t.account, t.id)] = t
    return JSONResponse({"id": t.id}, 201)


def sign_zendesk(secret: str, timestamp: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    ).decode()


@app.post("/_admin/tickets/{platform}/{account}/{ticket_id}/tag")
async def tag_and_fire(
    platform: str, account: str, ticket_id: int, request: Request
) -> JSONResponse:
    """Add the tag, then deliver the webhook `repeat` times, as the trigger would."""
    data = await request.json()
    t = _ticket(platform, account, ticket_id)
    if t is None:
        return _not_found()
    if data.get("tag", "har_analyze") not in t.tags:
        t.tags.append(data.get("tag", "har_analyze"))
    body = json.dumps({"ticket_id": str(t.id) if platform == "zendesk" else t.id}).encode()
    invocation = uuid.uuid4().hex
    results = []
    url = data["webhook_url"].replace(
        "http://localhost:8200",
        os.environ.get("FAKE_HELPDESK_WEBHOOK_BASE", "http://localhost:8200"),
    )
    for _ in range(int(data.get("repeat", 1))):
        headers = {"Content-Type": "application/json"}
        if platform == "zendesk":
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            headers.update(
                {
                    "X-Zendesk-Webhook-Signature-Timestamp": ts,
                    "X-Zendesk-Webhook-Signature": sign_zendesk(data["secret"], ts, body),
                    "X-Zendesk-Webhook-Invocation-Id": invocation,
                }
            )
        else:
            headers["X-HarTriage-Secret"] = data["secret"]
        response = httpx.post(url, content=body, headers=headers, timeout=10)
        results.append(response.status_code)
    return JSONResponse({"delivered": results})


@app.get("/_admin/tickets/{platform}/{account}/{ticket_id}")
def show_ticket(platform: str, account: str, ticket_id: int) -> JSONResponse:
    t = _ticket(platform, account, ticket_id)
    if t is None:
        return _not_found()
    return JSONResponse(
        {
            "id": t.id,
            "tags": t.tags,
            "comments": [
                {
                    "id": c.id,
                    "public": c.public,
                    "body": c.body,
                    "attachments": [
                        {
                            "id": a.id,
                            "filename": a.filename,
                            "redacted": a.redacted,
                            "size": len(a.content),
                        }
                        for a in c.attachments
                    ],
                }
                for c in t.comments
            ],
        }
    )


@app.post("/_admin/fail-next")
async def fail_next(request: Request) -> JSONResponse:
    data = await request.json()
    FAIL_NEXT[data["platform"]] = (int(data.get("status", 429)), int(data.get("retry_after", 1)))
    return JSONResponse({"ok": True})


@app.post("/_admin/reset")
def reset() -> JSONResponse:
    TICKETS.clear()
    UPLOADS.clear()
    FAIL_NEXT.clear()
    CALLS.clear()
    return JSONResponse({"ok": True})


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    rows = []
    for t in TICKETS.values():
        notes = "".join(
            f"<details><summary>{'public' if c.public else '<b>private note</b>'} #{c.id}"
            f" ({len(c.attachments)} attachment(s))</summary><div class='note'>"
            f"{c.body if not c.public else html.escape(c.body)}</div></details>"
            for c in t.comments
        )
        rows.append(
            f"<tr><td>{t.platform}</td><td>{html.escape(t.account)}</td><td>#{t.id}</td>"
            f"<td>{html.escape(t.subject)}</td><td>{html.escape(', '.join(t.tags))}</td><td>{notes}</td></tr>"
        )
    samples = "".join(f"<option>{p.name}</option>" for p in sorted(SAMPLES.glob("*.har")))
    return f"""<!doctype html><meta charset=utf-8><title>Fake helpdesk</title>
<style>body{{font:14px system-ui;margin:2rem;max-width:1100px}}td{{border-top:1px solid #ddd;padding:6px;vertical-align:top}}
.note{{background:#fffbe6;padding:8px;border:1px solid #f0e2a0}}</style>
<h1>Fake helpdesk</h1><p>A stand-in for Zendesk and Freshdesk. Notes posted by HAR Triage appear below
(private notes are rendered as the helpdesk would render them).</p>
<form onsubmit="event.preventDefault();create()">Platform <select id=p><option>zendesk</option><option>freshdesk</option></select>
account <input id=a value=acme size=8> sample <select id=s>{samples}</select> <button>Create ticket</button></form>
<form onsubmit="event.preventDefault();tag()" style="margin-top:8px">Ticket id <input id=t size=6> webhook URL
<input id=u size=60> secret <input id=k size=20> <button>Add tag har_analyze</button></form>
<table><tr><th>platform</th><th>account</th><th>ticket</th><th>subject</th><th>tags</th><th>conversation</th></tr>{"".join(rows)}</table>
<script>
async function create(){{await fetch('/_admin/tickets',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{platform:p.value,account:a.value,subject:'Checkout page is broken',attachments:[{{filename:s.value,sample:s.value}}]}})}});location.reload()}}
async function tag(){{await fetch(`/_admin/tickets/${{p.value}}/${{a.value}}/${{t.value}}/tag`,{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{webhook_url:u.value,secret:k.value}})}});setTimeout(()=>location.reload(),3000)}}
</script>"""
