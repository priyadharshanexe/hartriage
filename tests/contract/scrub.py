"""Make recorded helpdesk traffic safe to commit.

Applied to every request and response before a cassette is written, and to every
request before it is matched on replay, so the recorded and replayed sides agree.
Removes credentials, OAuth tokens, signed download links, the trial accounts'
subdomains, and any email address or name that is not obviously fake.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any

PLACEHOLDER_SUBDOMAIN = "acme"

SECRET_HEADERS = [
    "authorization",
    "cookie",
    "set-cookie",
    "x-zendesk-api-token",
    "x-request-id",
    "x-zendesk-origin-server",
    "cf-ray",
    "report-to",
    "nel",
]

_SIGNED_QUERY = re.compile(
    r"(?i)\b(X-Amz-[A-Za-z-]+|Signature|Expires|Key-Pair-Id|Policy|token)=[^&\"'\s<>\\]+"
)
_ATTACHMENT_TOKEN = re.compile(r"/attachments/token/[^/\"'\s?]+")
# Any JSON field named token or *_token: OAuth access tokens, Zendesk upload tokens,
# the agent's authenticity (CSRF) token in /users/me.
_ACCESS_TOKEN = re.compile(r'("(?:[A-Za-z]+_)?token"\s*:\s*")[^"]+(")')
_UPLOADS = re.compile(r'("uploads"\s*:\s*\[)[^\]]*(\])')
_CLIENT_SECRET = re.compile(r'("client_secret"\s*:\s*")[^"]+(")')
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _private_words() -> list[tuple[str, str]]:
    """Real names that must not reach the repository (from the environment)."""
    pairs: list[tuple[str, str]] = []
    for var in ("ZENDESK_SUBDOMAIN", "FRESHDESK_DOMAIN"):
        value = os.environ.get(var, "")
        value = value.replace("https://", "").split(".")[0]
        if value:
            pairs.append((value, PLACEHOLDER_SUBDOMAIN))
    for name in os.environ.get("HARTRIAGE_SCRUB_WORDS", "").split(","):
        if name.strip():
            pairs.append((name.strip(), "Test Agent"))
    # Longest first, so "first last" goes before "first".
    return sorted(pairs, key=lambda p: -len(p[0]))


def scrub_text(text: str) -> str:
    for real, fake in _private_words():
        text = re.sub(re.escape(real), fake, text, flags=re.IGNORECASE)
    text = _SIGNED_QUERY.sub(lambda m: f"{m.group(1)}=SCRUBBED", text)
    text = _ATTACHMENT_TOKEN.sub("/attachments/token/SCRUBBED", text)
    text = _ACCESS_TOKEN.sub(r"\1SCRUBBED\2", text)
    text = _UPLOADS.sub(r'\1"SCRUBBED"\2', text)
    text = _CLIENT_SECRET.sub(r"\1SCRUBBED\2", text)
    return _EMAIL.sub(
        lambda m: (
            m.group(0)
            if m.group(0).lower().endswith(("@example.com", ".test"))
            else "agent@example.com"
        ),
        text,
    )


def _scrub_body(body: Any) -> Any:
    if body is None:
        return body
    if isinstance(body, bytes):
        try:
            return scrub_text(body.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            return body
    if isinstance(body, str):
        return scrub_text(body)
    return body


def before_record_request(request: Any) -> Any:
    request.uri = scrub_text(request.uri)
    request.body = _scrub_body(request.body)
    for name in list(request.headers):
        value = request.headers[name]
        if isinstance(value, str):
            request.headers[name] = scrub_text(value)
    return request


def before_record_response(response: dict[str, Any]) -> dict[str, Any]:
    body = response.get("body") or {}
    if "string" in body:
        body["string"] = _scrub_body(body["string"])
    headers = response.get("headers") or {}
    for name in list(headers):
        if name.lower() in SECRET_HEADERS:
            del headers[name]
        elif name.lower() == "location":
            headers[name] = [scrub_text(v) for v in headers[name]]
    return response


def assert_clean(path: str, forbidden: list[str]) -> None:
    """Fail the recording if anything private survived the scrubbing."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    leaks = [word for word in forbidden if word and word.lower() in text.lower()]
    leaks += re.findall(r'"(?:[A-Za-z]+_)?token"\s*:\s*"(?!SCRUBBED")', text)
    leaks += re.findall(r"(?i)(?:X-Amz-Signature|Signature)=(?!SCRUBBED)", text)
    if leaks:
        raise AssertionError(f"{path} still contains {len(leaks)} private value(s)")


def sidecar(path: str) -> Callable[[dict[str, Any] | None], dict[str, Any]]:
    """Read or write the small JSON file that tells a replay which ticket was used."""

    def use(data: dict[str, Any] | None = None) -> dict[str, Any]:
        if data is not None:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return data
        with open(path, encoding="utf-8") as f:
            return dict(json.load(f))

    return use
