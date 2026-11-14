"""Zendesk Support API client and webhook signature check.

Docs: developer.zendesk.com/api-reference/ticketing/ and
developer.zendesk.com/documentation/webhooks/verifying/ (signature = base64 of
HMAC-SHA256 over the timestamp header followed by the raw body).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import httpx

from hartriage.helpdesk.base import Attachment, HelpdeskClient, Ticket

SIGNATURE = "x-zendesk-webhook-signature"
TIMESTAMP = "x-zendesk-webhook-signature-timestamp"
INVOCATION = "x-zendesk-webhook-invocation-id"
MAX_AGE_SECONDS = 3600  # Zendesk retries failed deliveries; the receipt table stops replays


def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_signature(
    secret: str, headers: dict[str, str], body: bytes, now: datetime | None = None
) -> bool:
    signature, timestamp = headers.get(SIGNATURE, ""), headers.get(TIMESTAMP, "")
    if not signature or not timestamp:
        return False
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        return False
    try:
        sent = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=UTC)
    age = ((now or datetime.now(UTC)) - sent).total_seconds()
    return -300 <= age <= MAX_AGE_SECONDS


def delivery_key(headers: dict[str, str], body: bytes) -> str:
    invocation = headers.get(INVOCATION, "")
    if invocation:
        return f"inv:{invocation[:150]}"
    return "sig:" + hashlib.sha256(headers.get(TIMESTAMP, "").encode() + body).hexdigest()


class ZendeskClient(HelpdeskClient):
    platform = "zendesk"
    allowed_download_hosts = ("zendesk.com", "zdusercontent.com", "zdassets.com")

    @classmethod
    def build(
        cls,
        subdomain: str,
        credentials: dict[str, str],
        timeout: float,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> ZendeskClient:
        auth: httpx.Auth | None
        headers = {"Accept": "application/json"}
        if credentials.get("oauth_token"):
            headers["Authorization"] = f"Bearer {credentials['oauth_token']}"
            auth = None
        else:
            auth = httpx.BasicAuth(f"{credentials['email']}/token", credentials["api_token"])
        url = base_url or f"https://{subdomain}.zendesk.com"
        return cls(
            url, auth, headers, timeout, transport, trust_any_download_host=base_url is not None
        )

    def verify(self) -> str:
        user = self.request("GET", "/api/v2/users/me.json").json().get("user") or {}
        if not user.get("id"):
            raise_auth()
        return str(user.get("name") or user.get("email") or "Zendesk user")

    def get_ticket(self, ticket_id: str) -> Ticket:
        data = self.request("GET", f"/api/v2/tickets/{ticket_id}.json").json()["ticket"]
        ticket = Ticket(
            id=str(data["id"]),
            subject=str(data.get("subject") or ""),
            tags=[str(t) for t in data.get("tags") or []],
        )
        url: str | None = f"/api/v2/tickets/{ticket_id}/comments.json"
        pages = 0
        while url and pages < 20:
            page = self.request("GET", url).json()
            for comment in page.get("comments") or []:
                for a in comment.get("attachments") or []:
                    ticket.attachments.append(
                        Attachment(
                            id=str(a["id"]),
                            filename=str(a.get("file_name") or ""),
                            size=int(a.get("size") or 0),
                            content_type=str(a.get("content_type") or ""),
                            url=str(a.get("content_url") or ""),
                            comment_id=str(comment.get("id")),
                        )
                    )
            url = page.get("next_page")
            pages += 1
        return ticket

    def _upload(self, filename: str, content: bytes) -> str:
        response = self.request(
            "POST",
            "/api/v2/uploads.json",
            params={"filename": filename},
            content=content,
            headers={"Content-Type": "application/binary"},
        )
        return str(response.json()["upload"]["token"])

    def post_private_note(
        self, ticket: Ticket, html: str, attachment: tuple[str, bytes] | None
    ) -> str:
        comment: dict[str, Any] = {"html_body": html, "public": False}
        if attachment is not None:
            comment["uploads"] = [self._upload(*attachment)]
        body = {"ticket": {"comment": comment}}
        data = self.request("PUT", f"/api/v2/tickets/{ticket.id}.json", json=body).json()
        for event in (data.get("audit") or {}).get("events") or []:
            if event.get("type") == "Comment":
                return str(event.get("id"))
        return str((data.get("audit") or {}).get("id") or "")

    def find_note(self, ticket_id: str, marker: str) -> str | None:
        url: str | None = f"/api/v2/tickets/{ticket_id}/comments.json"
        pages = 0
        while url and pages < 20:
            page = self.request("GET", url).json()
            for comment in page.get("comments") or []:
                text = f"{comment.get('html_body') or ''} {comment.get('body') or ''}"
                if marker in text:
                    return str(comment.get("id"))
            url = page.get("next_page")
            pages += 1
        return None

    def swap_tags(self, ticket: Ticket, remove: str, add: str) -> None:
        # additional_tags/remove_tags change only these two tags, so concurrent edits survive.
        self.request(
            "PUT",
            f"/api/v2/tickets/{ticket.id}.json",
            json={"ticket": {"additional_tags": [add], "remove_tags": [remove]}},
        )

    def remove_attachment(self, ticket: Ticket, attachment: Attachment) -> None:
        self.request(
            "PUT",
            f"/api/v2/tickets/{ticket.id}/comments/{attachment.comment_id}"
            f"/attachments/{attachment.id}/redact.json",
        )


def raise_auth() -> None:
    from hartriage.helpdesk.base import AuthFailed

    raise AuthFailed("zendesk did not accept the credentials")
