"""Facts read from an entry *before* redaction, after which the secret itself is discarded.

Redaction removes the values a support engineer would otherwise squint at: was a
token sent at all, had it expired, which request id did the server return? This
module answers those questions first and keeps only the answers:

* which kinds of credentials were present (never their values);
* for each JWT: ``exp``, ``iat``, ``nbf`` and ``aud``, decoded without verifying
  the signature (we only need the claims, and we hold no keys), plus the token's
  redaction marker so the claims can be tied to the redacted request;
* correlation ids such as ``x-request-id`` and ``cf-ray``, for escalations;
* byte sizes of headers and cookies (a 431 is often a cookie the size of a novel).

The result is stored on the redacted entry as ``_hartriage``.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from hartriage.har.redactor import Redactor, is_sensitive_header, is_sensitive_name

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]*")

CORRELATION_HEADERS = (
    "x-request-id",
    "x-correlation-id",
    "request-id",
    "x-amzn-requestid",
    "x-amz-request-id",
    "x-amz-cf-id",
    "cf-ray",
    "traceparent",
    "x-b3-traceid",
    "x-cloud-trace-context",
    "x-ms-request-id",
    "x-github-request-id",
    "x-trace-id",
)


@dataclass
class JwtClaims:
    location: str
    marker: str
    exp: float | None = None
    iat: float | None = None
    nbf: float | None = None
    aud: list[str] = field(default_factory=list)


@dataclass
class EntryMeta:
    credentials: list[str] = field(default_factory=list)
    jwts: list[JwtClaims] = field(default_factory=list)
    correlation_ids: dict[str, str] = field(default_factory=dict)
    request_header_bytes: int = 0
    cookie_header_bytes: int = 0
    request_body_bytes: int = 0

    @property
    def credentials_present(self) -> bool:
        return bool(self.credentials)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["credentials_present"] = self.credentials_present
        return data

    @classmethod
    def from_dict(cls, data: Any) -> EntryMeta:
        if not isinstance(data, dict):
            return cls()
        jwts = []
        for j in data.get("jwts") or []:
            if isinstance(j, dict):
                jwts.append(
                    JwtClaims(
                        location=str(j.get("location", "")),
                        marker=str(j.get("marker", "")),
                        exp=_number(j.get("exp")),
                        iat=_number(j.get("iat")),
                        nbf=_number(j.get("nbf")),
                        aud=[str(a) for a in j.get("aud") or []][:3],
                    )
                )
        ids = data.get("correlation_ids")
        return cls(
            credentials=[str(c) for c in data.get("credentials") or []],
            jwts=jwts,
            correlation_ids={str(k): str(v) for k, v in ids.items()}
            if isinstance(ids, dict)
            else {},
            request_header_bytes=int(data.get("request_header_bytes") or 0),
            cookie_header_bytes=int(data.get("cookie_header_bytes") or 0),
            request_body_bytes=int(data.get("request_body_bytes") or 0),
        )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def decode_jwt_claims(token: str) -> dict[str, Any] | None:
    """Decode a JWT's payload without verifying it. Returns None if it isn't one."""
    parts = token.split(".")
    if len(parts) < 3:
        return None
    payload = parts[1]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
    except (binascii.Error, ValueError):
        return None
    return claims if isinstance(claims, dict) else None


def _headers(message: Any) -> list[tuple[str, str]]:
    if not isinstance(message, dict) or not isinstance(message.get("headers"), list):
        return []
    out = []
    for h in message["headers"]:
        if isinstance(h, dict):
            out.append((str(h.get("name", "")), str(h.get("value", ""))))
    return out


def extract(entry: dict[str, Any], redactor: Redactor) -> EntryMeta:
    """Read the facts from a raw (not yet redacted) entry."""
    meta = EntryMeta()
    raw_request, raw_response = entry.get("request"), entry.get("response")
    request: dict[str, Any] = raw_request if isinstance(raw_request, dict) else {}
    response: dict[str, Any] = raw_response if isinstance(raw_response, dict) else {}

    seen_tokens: set[str] = set()

    def jwt_in(text: str, location: str) -> None:
        for match in _JWT.finditer(text):
            token = match.group(0)
            if token in seen_tokens:
                continue
            claims = decode_jwt_claims(token)
            if claims is None:
                continue
            seen_tokens.add(token)
            aud = claims.get("aud")
            audiences = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
            meta.jwts.append(
                JwtClaims(
                    location=location,
                    marker=redactor.marker(token),
                    exp=_number(claims.get("exp")),
                    iat=_number(claims.get("iat")),
                    nbf=_number(claims.get("nbf")),
                    aud=[redactor.text(str(a))[:200] for a in audiences[:3]],
                )
            )

    credentials: list[str] = []
    for name, value in _headers(request):
        lowered = name.lower().lstrip(":")
        meta.request_header_bytes += len(name) + len(value) + 4
        if lowered == "authorization":
            scheme = value.split(None, 1)[0].lower() if value.strip() else ""
            kind = scheme if scheme in ("bearer", "basic", "digest", "negotiate") else "other"
            credentials.append(f"authorization:{kind}")
        elif lowered == "proxy-authorization":
            credentials.append("proxy-authorization")
        elif lowered == "cookie":
            meta.cookie_header_bytes += len(value)
            if value.strip():
                credentials.append("cookie")
        elif is_sensitive_header(lowered) and value.strip():
            credentials.append(f"header:{lowered}")
        if value:
            jwt_in(value, f"header:{lowered}")

    cookies = request.get("cookies")
    if isinstance(cookies, list) and cookies and "cookie" not in credentials:
        credentials.append("cookie")
    if isinstance(cookies, list):
        for c in cookies:
            if isinstance(c, dict) and isinstance(c.get("value"), str):
                jwt_in(c["value"], f"cookie:{c.get('name', '')}")

    url = request.get("url")
    if isinstance(url, str):
        jwt_in(url, "url")
    query = request.get("queryString")
    if isinstance(query, list):
        for q in query:
            if (
                isinstance(q, dict)
                and q.get("value")
                and is_sensitive_name(str(q.get("name", "")), query=True)
            ):
                credentials.append(f"query:{str(q.get('name', '')).lower()}")

    post = request.get("postData")
    if isinstance(post, dict) and isinstance(post.get("text"), str):
        text = post["text"]
        meta.request_body_bytes = len(text.encode("utf-8", "surrogatepass"))
        if len(text) <= 256 * 1024:
            jwt_in(text, "body")
    body_size = request.get("bodySize")
    if isinstance(body_size, int) and body_size > meta.request_body_bytes:
        meta.request_body_bytes = body_size

    headers_size = request.get("headersSize")
    if isinstance(headers_size, int) and headers_size > meta.request_header_bytes:
        meta.request_header_bytes = headers_size

    meta.credentials = list(dict.fromkeys(credentials))

    for message in (response, request):
        for name, value in _headers(message):
            lowered = name.lower()
            if lowered in CORRELATION_HEADERS and lowered not in meta.correlation_ids and value:
                meta.correlation_ids[lowered] = redactor.text(value.strip())[:200]
    return meta
