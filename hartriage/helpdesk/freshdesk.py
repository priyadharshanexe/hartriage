"""Freshdesk API v2 client and webhook check.

Freshdesk automation webhooks are not signed. Each connection gets its own random
secret, which the admin puts in a custom header of the automation rule. The
secret is compared in constant time, and even then the payload is only used for
the ticket id: everything else is re-read from the Freshdesk API.
"""

from __future__ import annotations

import hashlib
import re
import time

import httpx

from hartriage.core.security import constant_time_equals
from hartriage.helpdesk.base import Attachment, AuthFailed, HelpdeskClient, Ticket

TAG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SECRET_HEADER = "x-hartriage-secret"  # noqa: S105 - a header name, not a secret


def verify_secret(secret: str, headers: dict[str, str]) -> bool:
    supplied = headers.get(SECRET_HEADER, "")
    return bool(supplied) and constant_time_equals(supplied, secret)


def delivery_key(body: bytes, now: float | None = None) -> str:
    # No delivery id from Freshdesk: identical bodies within 10 minutes count as one
    # delivery. A new attachment on the same ticket is still analysed: it is a new
    # artifact, and notes are unique per analysis.
    bucket = int((now if now is not None else time.time()) // 600)
    return f"body:{hashlib.sha256(body).hexdigest()}:{bucket}"


class FreshdeskClient(HelpdeskClient):
    platform = "freshdesk"
    allowed_download_hosts = (
        "freshdesk.com",
        "freshworks.com",
        "amazonaws.com",
        "freshdeskusercontent.com",
        "freshdeskusercontent-euc.com",
    )

    @classmethod
    def build(
        cls,
        domain: str,
        credentials: dict[str, str],
        timeout: float,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> FreshdeskClient:
        auth = httpx.BasicAuth(credentials["api_key"], "X")
        url = base_url or f"https://{domain}.freshdesk.com"
        return cls(
            url,
            auth,
            {"Accept": "application/json"},
            timeout,
            transport,
            trust_any_download_host=base_url is not None,
        )

    def verify(self) -> str:
        me = self.request("GET", "/api/v2/agents/me").json()
        contact = me.get("contact") or {}
        if not me.get("id"):
            raise AuthFailed("freshdesk did not accept the API key")
        return str(contact.get("name") or contact.get("email") or "Freshdesk agent")

    def _attachments(
        self, items: list[dict[str, object]], conversation_id: str | None
    ) -> list[Attachment]:
        return [
            Attachment(
                id=str(a.get("id")),
                filename=str(a.get("name") or ""),
                size=int(str(a.get("size") or 0)),
                content_type=str(a.get("content_type") or ""),
                url=str(a.get("attachment_url") or ""),
                comment_id=conversation_id,
            )
            for a in items
        ]

    def get_ticket(self, ticket_id: str) -> Ticket:
        data = self.request("GET", f"/api/v2/tickets/{ticket_id}").json()
        ticket = Ticket(
            id=str(data["id"]),
            subject=str(data.get("subject") or ""),
            tags=[str(t) for t in data.get("tags") or []],
        )
        ticket.attachments.extend(self._attachments(data.get("attachments") or [], None))
        for page in range(1, 21):
            items = self.request(
                "GET",
                f"/api/v2/tickets/{ticket_id}/conversations",
                params={"page": page, "per_page": 100},
            ).json()
            for conversation in items:
                ticket.attachments.extend(
                    self._attachments(
                        conversation.get("attachments") or [], str(conversation.get("id"))
                    )
                )
            if len(items) < 100:
                break
        return ticket

    def post_private_note(
        self, ticket: Ticket, html: str, attachment: tuple[str, bytes] | None
    ) -> str:
        if attachment is None:
            data = self.request(
                "POST", f"/api/v2/tickets/{ticket.id}/notes", json={"body": html, "private": True}
            ).json()
        else:
            name, content = attachment
            data = self.request(
                "POST",
                f"/api/v2/tickets/{ticket.id}/notes",
                data={"body": html, "private": "true"},
                files={"attachments[]": (name, content, "application/json")},
            ).json()
        return str(data.get("id"))

    def find_note(self, ticket_id: str, marker: str) -> str | None:
        for page in range(1, 21):
            items = self.request(
                "GET",
                f"/api/v2/tickets/{ticket_id}/conversations",
                params={"page": page, "per_page": 100},
            ).json()
            for conversation in items:
                if marker in str(conversation.get("body") or ""):
                    return str(conversation.get("id"))
            if len(items) < 100:
                break
        return None

    def swap_tags(self, ticket: Ticket, remove: str, add: str) -> None:
        # Freshdesk replaces the whole tag list, so re-read it right before writing.
        current = self.request("GET", f"/api/v2/tickets/{ticket.id}").json().get("tags") or []
        tags = [t for t in current if t != remove]
        if add not in tags:
            tags.append(add)
        self.request("PUT", f"/api/v2/tickets/{ticket.id}", json={"tags": tags})

    def tagged_tickets(self, tag: str) -> list[tuple[str, str]]:
        """Found live: a Freshdesk "Ticket is updated" automation does not fire when an
        agent only adds a tag, so tagging alone never sends the webhook. The search
        API finds tagged tickets within seconds instead."""
        if not TAG.match(tag):
            raise ValueError("tags may only contain letters, digits, _ and -")
        found: list[tuple[str, str]] = []
        for page in range(1, 11):  # the search API stops at 10 pages of 30
            data = self.request(
                "GET", "/api/v2/search/tickets", params={"query": f"\"tag:'{tag}'\"", "page": page}
            ).json()
            results = data.get("results") or []
            found.extend((str(t["id"]), str(t.get("updated_at") or "")) for t in results)
            if len(results) < 30:
                break
        return found

    def remove_attachment(self, ticket: Ticket, attachment: Attachment) -> None:
        self.request("DELETE", f"/api/v2/attachments/{attachment.id}")
