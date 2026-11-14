"""Build HAR files in tests. Every secret-looking value is assembled at run time,
so the repository itself never contains anything a secret scanner would flag."""

from __future__ import annotations

import base64
import io
import json
from typing import Any


def b64url(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def make_jwt(
    exp: float | None = None,
    iat: float | None = None,
    aud: str | None = None,
    nbf: float | None = None,
    sub: str = "user-42",
) -> str:
    claims: dict[str, Any] = {"sub": sub}
    if exp is not None:
        claims["exp"] = int(exp)
    if iat is not None:
        claims["iat"] = int(iat)
    if nbf is not None:
        claims["nbf"] = int(nbf)
    if aud is not None:
        claims["aud"] = aud
    header = b64url({"alg": "HS256", "typ": "JWT"})
    return f"{header}.{b64url(claims)}.c2lnbmF0dXJlLW5vdC1jaGVja2Vk"


def headers(**pairs: str) -> list[dict[str, str]]:
    return [{"name": k.replace("_", "-"), "value": v} for k, v in pairs.items()]


def entry(
    url: str = "https://app.example.com/api/items",
    *,
    method: str = "GET",
    status: int = 200,
    started: str = "2026-11-14T10:00:00.000Z",
    time: float = 120.0,
    request_headers: list[dict[str, str]] | None = None,
    response_headers: list[dict[str, str]] | None = None,
    query: list[dict[str, str]] | None = None,
    cookies: list[dict[str, Any]] | None = None,
    post: dict[str, Any] | None = None,
    content: dict[str, Any] | None = None,
    timings: dict[str, float] | None = None,
    error: str | None = None,
    resource_type: str | None = None,
    redirect: str = "",
    status_text: str = "",
    **extra: Any,
) -> dict[str, Any]:
    e: dict[str, Any] = {
        "startedDateTime": started,
        "time": time,
        "request": {
            "method": method,
            "url": url,
            "httpVersion": "HTTP/1.1",
            "headers": request_headers or [],
            "queryString": query or [],
            "cookies": cookies or [],
            "headersSize": -1,
            "bodySize": len(post["text"]) if post and "text" in post else 0,
        },
        "response": {
            "status": status,
            "statusText": status_text,
            "httpVersion": "HTTP/1.1",
            "headers": response_headers or [],
            "cookies": [],
            "content": content or {"size": 0, "mimeType": "application/json"},
            "redirectURL": redirect,
            "headersSize": -1,
            "bodySize": -1,
        },
        "cache": {},
        "timings": timings
        or {
            "blocked": 1,
            "dns": -1,
            "connect": -1,
            "ssl": -1,
            "send": 1,
            "wait": time - 3,
            "receive": 1,
        },
    }
    if post is not None:
        e["request"]["postData"] = post
    if error:
        e["_error"] = error
    if resource_type:
        e["_resourceType"] = resource_type
    e.update(extra)
    return e


def har(
    *entries: dict[str, Any],
    pages: list[dict[str, Any]] | None = None,
    creator: str = "WebInspector",
) -> dict[str, Any]:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": creator, "version": "537.36"},
            "pages": pages or [],
            "entries": list(entries),
        }
    }


def as_stream(data: dict[str, Any] | str | bytes) -> io.BytesIO:
    if isinstance(data, dict):
        data = json.dumps(data)
    if isinstance(data, str):
        data = data.encode()
    return io.BytesIO(data)
