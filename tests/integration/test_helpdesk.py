"""Zendesk and Freshdesk end to end, against tools/fake_helpdesk in-process:
tag a ticket → signed webhook → analysis → exactly one private note."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from hartriage.helpdesk import zendesk
from hartriage.helpdesk.base import Attachment, HelpdeskError
from hartriage.helpdesk.zendesk import ZendeskClient
from tools.fake_helpdesk import app as fake

pytestmark = pytest.mark.integration
SAMPLE = Path(__file__).resolve().parents[1] / "golden" / "hars" / "chromium" / "checkout-story.har"
SIGNING_SECRET = "zendesk-" + "signing-" + "secret-for-tests"


def connect_zendesk(admin: Any, **extra: Any) -> dict[str, Any]:
    response = admin.post(
        "/v1/connections",
        json={
            "platform": "zendesk",
            "subdomain": "acme",
            "email": "agent@acme.test",
            "api_token": "zd-token-" + "123",
            "signing_secret": SIGNING_SECRET,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def connect_freshdesk(admin: Any) -> dict[str, Any]:
    response = admin.post(
        "/v1/connections",
        json={"platform": "freshdesk", "subdomain": "acme", "api_key": "fd-key-" + "456"},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def ticket(platform: str, tags: list[str] | None = None, filename: str = "checkout.har") -> int:
    t = fake.FakeTicket(
        next(fake._ids),
        platform,
        "acme",
        "Checkout is broken",
        ["har_analyze"] if tags is None else tags,
    )
    t.comments.append(
        fake.Comment(
            next(fake._ids),
            "See attached",
            True,
            [fake.FakeAttachment(next(fake._ids), filename, SAMPLE.read_bytes())],
        )
    )
    fake.TICKETS[(platform, "acme", t.id)] = t
    return t.id


def zendesk_hook(
    client: Any,
    conn: dict[str, Any],
    ticket_id: int,
    *,
    invocation: str = "inv-1",
    secret: str = SIGNING_SECRET,
    timestamp: datetime | None = None,
    body: bytes | None = None,
) -> Any:
    body = body if body is not None else json.dumps({"ticket_id": str(ticket_id)}).encode()
    ts = (timestamp or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return client.post(
        f"/v1/webhooks/zendesk/{conn['id']}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Zendesk-Webhook-Signature-Timestamp": ts,
            "X-Zendesk-Webhook-Signature": zendesk.sign(secret, ts, body),
            "X-Zendesk-Webhook-Invocation-Id": invocation,
        },
    )


def private_notes(platform: str, ticket_id: int) -> list[fake.Comment]:
    return [c for c in fake.TICKETS[(platform, "acme", ticket_id)].comments if not c.public]


def test_zendesk_tag_to_private_note(client: Any, admin: Any) -> None:
    conn = connect_zendesk(admin)
    assert conn["webhook_url"].endswith(f"/v1/webhooks/zendesk/{conn['id']}")
    assert any("Triggers" in step for step in conn["setup_steps"])
    tid = ticket("zendesk")
    response = zendesk_hook(client, conn, tid)
    assert response.status_code == 202, response.text
    [note] = private_notes("zendesk", tid)
    assert "Likely cause" in note.body and "HAR Triage analysis" in note.body
    assert "[REDACTED:" in note.body or "token" in note.body
    t = fake.TICKETS[("zendesk", "acme", tid)]
    assert "har_analyzed" in t.tags and "har_analyze" not in t.tags
    history = admin.get("/v1/analyses").json()["items"]
    assert history[0]["source"]["kind"] == "ticket"
    assert history[0]["source"]["ticket_url"] == f"https://acme.zendesk.com/agent/tickets/{tid}"


def test_duplicate_webhook_posts_one_note(client: Any, admin: Any) -> None:
    conn = connect_zendesk(admin)
    tid = ticket("zendesk")
    assert zendesk_hook(client, conn, tid).status_code == 202
    again = zendesk_hook(client, conn, tid)  # same invocation id: the helpdesk retried
    assert again.status_code == 200 and again.json() == {"status": "duplicate"}
    # A fresh delivery for the same ticket and the same attachment: still one note.
    fake.TICKETS[("zendesk", "acme", tid)].tags.append("har_analyze")
    assert zendesk_hook(client, conn, tid, invocation="inv-2").status_code == 202
    assert len(private_notes("zendesk", tid)) == 1


def test_bad_signatures_are_refused(client: Any, admin: Any) -> None:
    conn = connect_zendesk(admin)
    tid = ticket("zendesk")
    assert zendesk_hook(client, conn, tid, secret="wrong-secret").status_code == 401
    body = json.dumps({"ticket_id": str(tid)}).encode()
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tampered = client.post(
        f"/v1/webhooks/zendesk/{conn['id']}",
        content=body.replace(b"}", b" }"),
        headers={
            "X-Zendesk-Webhook-Signature-Timestamp": ts,
            "X-Zendesk-Webhook-Signature": zendesk.sign(SIGNING_SECRET, ts, body),
        },
    )
    assert tampered.status_code == 401
    stale = zendesk_hook(client, conn, tid, timestamp=datetime.now(UTC) - timedelta(hours=2))
    assert stale.status_code == 401
    assert private_notes("zendesk", tid) == []
    listed = admin.get("/v1/connections").json()["items"][0]
    assert listed["last_webhook_status"] == "rejected: bad signature"


def test_payload_is_not_trusted(client: Any, admin: Any) -> None:
    conn = connect_zendesk(admin)
    tid = ticket("zendesk", tags=[])  # the tag is not on the ticket
    assert zendesk_hook(client, conn, tid).status_code == 202  # signed, so accepted…
    assert private_notes("zendesk", tid) == []  # …but the API says no tag: nothing happens
    bad = zendesk_hook(client, conn, tid, body=b'{"ticket_id": "1; DROP TABLE"}', invocation="x")
    assert bad.status_code == 400
    assert (
        client.post(
            "/v1/webhooks/zendesk/00000000-0000-0000-0000-000000000000", content=b"{}"
        ).status_code
        == 404
    )


def test_freshdesk_secret_header_and_rate_limit_retry(client: Any, admin: Any) -> None:
    conn = connect_freshdesk(admin)
    secret = conn["webhook_secret"]
    tid = ticket("freshdesk")
    url = f"/v1/webhooks/freshdesk/{conn['id']}"
    body = json.dumps({"ticket_id": tid}).encode()
    assert (
        client.post(url, content=body, headers={"X-HarTriage-Secret": "guess"}).status_code == 401
    )
    assert client.post(url, content=body).status_code == 401
    fake.FAIL_NEXT["freshdesk"] = (429, 1)  # the first Freshdesk call is rate limited
    assert client.post(url, content=body, headers={"X-HarTriage-Secret": secret}).status_code == 202
    [note] = private_notes("freshdesk", tid)
    assert "Likely cause" in note.body
    assert fake.TICKETS[("freshdesk", "acme", tid)].tags == ["har_analyzed"]
    dup = client.post(url, content=body, headers={"X-HarTriage-Secret": secret})
    assert dup.json() == {"status": "duplicate"}


def test_note_is_not_posted_twice_after_a_crash(client: Any, admin: Any) -> None:
    """The worker posted the note, then died before recording it."""
    from hartriage.db.models import PostedNote
    from hartriage.db.session import session_scope
    from hartriage.helpdesk.tasks import post_note

    conn = connect_zendesk(admin)
    tid = ticket("zendesk")
    zendesk_hook(client, conn, tid)
    with session_scope() as db:
        note = db.scalars(select(PostedNote)).one()
        note.status, note.platform_comment_id = "pending", None  # the record of the post was lost
        analysis_id = str(note.analysis_id)
    post_note.apply(args=[analysis_id])
    assert len(private_notes("zendesk", tid)) == 1  # found on the ticket, not posted again
    with session_scope() as db:
        assert db.scalars(select(PostedNote)).one().status == "posted"


def test_original_attachment_is_replaced_when_enabled(client: Any, admin: Any) -> None:
    conn = connect_zendesk(admin, replace_attachments=True)
    tid = ticket("zendesk")
    zendesk_hook(client, conn, tid)
    t = fake.TICKETS[("zendesk", "acme", tid)]
    original = t.comments[0].attachments[0]
    assert original.redacted and original.content == b""
    [note] = private_notes("zendesk", tid)
    [clean] = note.attachments
    assert clean.filename == "checkout.redacted.har"
    assert (
        b"[REDACTED:" in clean.content
        and b"eyJhbGciOiJIUzI1NiIsICJ0eXAiOiAiSldUIn0" not in clean.content
    )


def test_freshdesk_replacement_deletes_the_original(client: Any, admin: Any) -> None:
    conn = connect_freshdesk(admin)
    admin.patch(f"/v1/connections/{conn['id']}", json={"replace_attachments": True})
    tid = ticket("freshdesk")
    client.post(
        f"/v1/webhooks/freshdesk/{conn['id']}",
        content=json.dumps({"ticket_id": tid}).encode(),
        headers={"X-HarTriage-Secret": conn["webhook_secret"]},
    )
    t = fake.TICKETS[("freshdesk", "acme", tid)]
    assert t.comments[0].attachments == []
    assert private_notes("freshdesk", tid)[0].attachments[0].filename == "checkout.redacted.har"


def test_connection_credentials_are_checked_and_encrypted(client: Any, admin: Any) -> None:
    from hartriage.db.models import HelpdeskConnection
    from hartriage.db.session import session_scope

    connect_zendesk(admin)
    with session_scope() as db:
        row = db.scalars(select(HelpdeskConnection)).one()
        assert (
            "zd-token-123" not in row.credentials_encrypted
            and row.credentials_encrypted.startswith("v1:")
        )
        assert SIGNING_SECRET not in row.webhook_secret_encrypted
    assert (
        admin.post(
            "/v1/connections",
            json={
                "platform": "zendesk",
                "subdomain": "evil.com/x",
                "oauth_token": "t",
                "signing_secret": "s",
            },
        ).status_code
        == 422
    )
    listed = admin.get("/v1/connections").json()["items"]
    assert "credentials" not in json.dumps(listed) and SIGNING_SECRET not in json.dumps(listed)
    assert admin.post(f"/v1/connections/{listed[0]['id']}/test").json() == {
        "ok": True,
        "account": "Fake Zendesk Agent",
    }


# ---------------------------------------------------------------- unit-level checks


def test_attachment_downloads_only_from_helpdesk_hosts() -> None:
    client = ZendeskClient("https://acme.zendesk.com", None, {}, 5)
    for url in (
        "https://169.254.169.254/latest",
        "http://acme.zendesk.com/x",
        "https://zendesk.com.evil.io/a",
    ):
        with pytest.raises(HelpdeskError):
            client.check_download_url(url)
    client.check_download_url("https://acme.zendesk.com/attachments/token/abc/?name=x.har")
    client.check_download_url("https://acme.zdusercontent.com/attachment/1/x.har")


def test_api_credentials_are_not_sent_to_the_download_host() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = request.headers.get("authorization")
        if request.url.host == "acme.zendesk.com":
            return httpx.Response(
                302, headers={"Location": "https://acme.zdusercontent.com/file/x.har"}
            )
        return httpx.Response(200, content=b'{"log": {"entries": []}}')

    creds = {"email": "a@b.c", "api_token": "t0ken-value"}
    client = ZendeskClient.build("acme", creds, 5, transport=httpx.MockTransport(handler))
    attachment = Attachment(
        "1", "x.har", 10, "application/json", "https://acme.zendesk.com/attachments/token/1"
    )
    with client.open_attachment(attachment, 1000) as stream:
        assert stream.read() == b'{"log": {"entries": []}}'
    assert seen["acme.zendesk.com"] is not None
    assert seen["acme.zdusercontent.com"] is None
    expected = "Basic " + base64.b64encode(b"a@b.c/token:t0ken-value").decode()
    assert seen["acme.zendesk.com"] == expected


def test_our_own_redacted_copy_is_never_analysed(client: Any, admin: Any) -> None:
    """Found in browser testing: with replacement on, re-tagging the ticket analysed
    the redacted copy attached to our note, and posted a second note."""
    conn = connect_zendesk(admin, replace_attachments=True)
    tid = ticket("zendesk")
    assert zendesk_hook(client, conn, tid).status_code == 202
    fake.TICKETS[("zendesk", "acme", tid)].tags.append("har_analyze")
    assert zendesk_hook(client, conn, tid, invocation="inv-again").status_code == 202
    notes = private_notes("zendesk", tid)
    assert len(notes) == 1
    assert [a.filename for a in notes[0].attachments] == ["checkout.redacted.har"]


def test_tag_is_cleared_when_there_is_nothing_new(client: Any, admin: Any) -> None:
    """Found in browser testing: re-tagging an already analysed ticket left the
    trigger tag on, with no sign the request was handled."""
    conn = connect_zendesk(admin)
    tid = ticket("zendesk")
    zendesk_hook(client, conn, tid)
    t = fake.TICKETS[("zendesk", "acme", tid)]
    t.tags = ["har_analyze"]
    zendesk_hook(client, conn, tid, invocation="inv-retag")
    assert t.tags == ["har_analyzed"]
    assert len(private_notes("zendesk", tid)) == 1


def test_freshdesk_tagged_tickets_are_found_by_polling(client: Any, admin: Any) -> None:
    """Found on a live Freshdesk trial: a "Ticket is updated" automation does not fire
    when an agent only adds a tag, so no webhook ever arrives. Polling finds the ticket."""
    from hartriage.helpdesk.tasks import poll_tagged_tickets

    connect_freshdesk(admin)
    tagged = ticket("freshdesk")
    untagged = ticket("freshdesk", tags=[])
    assert poll_tagged_tickets() == 1
    [note] = private_notes("freshdesk", tagged)
    assert "Likely cause" in note.body
    assert fake.TICKETS[("freshdesk", "acme", tagged)].tags == ["har_analyzed"]
    assert private_notes("freshdesk", untagged) == []
    # Polling again finds nothing new: the tag is gone, and nothing is posted twice.
    assert poll_tagged_tickets() == 0
    assert len(private_notes("freshdesk", tagged)) == 1


def test_polling_survives_a_rate_limited_helpdesk(client: Any, admin: Any) -> None:
    from hartriage.helpdesk.tasks import poll_tagged_tickets

    connect_freshdesk(admin)
    tid = ticket("freshdesk")
    fake.FAIL_NEXT["freshdesk"] = (429, 30)
    assert poll_tagged_tickets() == 0  # skipped this round, no crash
    assert poll_tagged_tickets() == 1
    assert len(private_notes("freshdesk", tid)) == 1


def test_zendesk_oauth_client_mints_and_renews_its_token(client: Any, admin: Any) -> None:
    """Found live: new Zendesk accounts can't create API tokens any more, so a
    confidential OAuth client (client_credentials grant) is how they connect."""
    from hartriage.helpdesk.zendesk import ClientCredentials

    ClientCredentials._cache.clear()
    response = admin.post(
        "/v1/connections",
        json={
            "platform": "zendesk",
            "subdomain": "acme",
            "oauth_client_id": "hartriage",
            "oauth_client_secret": "client-" + "secret",
            "signing_secret": SIGNING_SECRET,
        },
    )
    assert response.status_code == 201, response.text
    conn = response.json()
    assert conn["auth_type"] == "oauth_client"
    assert conn["account"] == "Fake Zendesk Agent"
    tid = ticket("zendesk")
    # Zendesk revokes the token; the next call is refused once, re-mints, and goes on.
    fake.ZD_TOKENS.clear()
    assert zendesk_hook(client, conn, tid).status_code == 202
    assert len(private_notes("zendesk", tid)) == 1
    assert sum(c.endswith("/oauth/tokens") for c in fake.CALLS) == 2


def test_zendesk_oauth_client_with_a_wrong_secret_is_refused(admin: Any) -> None:
    from hartriage.helpdesk.zendesk import ClientCredentials

    ClientCredentials._cache.clear()
    response = admin.post(
        "/v1/connections",
        json={
            "platform": "zendesk",
            "subdomain": "acme",
            "oauth_client_id": "hartriage",
            "oauth_client_secret": "",
        },
    )
    assert response.status_code == 422


def test_zendesk_can_connect_before_the_webhook_exists(client: Any, admin: Any) -> None:
    """The webhook needs the connection's URL before Zendesk shows its signing secret,
    so the secret is added afterwards. Until then every webhook is refused: an empty
    HMAC key is one anyone could sign with."""
    response = admin.post(
        "/v1/connections",
        json={"platform": "zendesk", "subdomain": "acme", "email": "a@acme.test", "api_token": "t"},
    )
    assert response.status_code == 201, response.text
    conn = response.json()
    assert conn["needs_signing_secret"] is True
    tid = ticket("zendesk")
    assert zendesk_hook(client, conn, tid, secret="").status_code == 401
    listed = admin.get("/v1/connections").json()["items"][0]
    assert listed["last_webhook_status"] == "rejected: no signing secret yet"
    patched = admin.patch(f"/v1/connections/{conn['id']}", json={"signing_secret": SIGNING_SECRET})
    assert patched.json()["needs_signing_secret"] is False
    assert zendesk_hook(client, conn, tid).status_code == 202
    assert len(private_notes("zendesk", tid)) == 1


def test_redacted_copies_in_the_old_layout_are_accepted_by_zendesk() -> None:
    """Found live: Zendesk refused .har uploads starting '{"log":{"entries":[' as a
    file-type mismatch. Copies stored before the HarWriter fix are re-laid-out."""
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return httpx.Response(201, json={"upload": {"token": "t"}})

    client = ZendeskClient.build(
        "acme",
        {"email": "a@b.c", "api_token": "x"},
        5,
        "https://acme.zendesk.com",
        httpx.MockTransport(handler),
    )
    old = b'{"log":{"entries":[\n{"request":{}}\n]}}'
    assert client._upload("file.redacted.har", old) == "t"
    assert seen[0].startswith(b'{\n"log":')
    assert json.loads(seen[0]) == json.loads(old)
