"""A normalised, read-only view of one *redacted* HAR entry, for the rules.

HAR files from Chrome, Firefox, Safari and Playwright disagree in small ways: how a
network error is recorded (``_error``, ``_failureText``, status 0 or -1), whether
missing timings are -1 or absent, where the resource type lives. `Entry` hides
those differences so each rule is a few lines of plain logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import SplitResult, urlsplit

from hartriage.har.metadata import EntryMeta


def split(url: str) -> SplitResult:
    """urlsplit that never raises: a malformed URL in a HAR file must not stop the analysis."""
    try:
        return urlsplit(url)
    except ValueError:
        return SplitResult("", "", url, "", "")


PHASES = ("blocked", "dns", "connect", "ssl", "send", "wait", "receive")


@dataclass(frozen=True, slots=True)
class Timings:
    blocked: float | None = None
    dns: float | None = None
    connect: float | None = None  # includes ssl, per the HAR spec
    ssl: float | None = None
    send: float | None = None
    wait: float | None = None
    receive: float | None = None

    @classmethod
    def from_har(cls, data: Any) -> Timings:
        if not isinstance(data, dict):
            return cls()
        values: dict[str, float | None] = {}
        for phase in PHASES:
            raw = data.get(phase)
            values[phase] = (
                float(raw)
                if isinstance(raw, int | float) and not isinstance(raw, bool) and raw >= 0
                else None
            )
        return cls(**values)

    def as_dict(self) -> dict[str, float | None]:
        return {p: getattr(self, p) for p in PHASES}

    def phases(self) -> dict[str, float]:
        """Exclusive phase durations: connect excludes the TLS handshake."""
        out: dict[str, float] = {}
        for phase in PHASES:
            value = getattr(self, phase)
            if value is None:
                continue
            if phase == "connect" and self.ssl is not None:
                value = max(0.0, value - self.ssl)
            out[phase] = value
        return out

    def total(self) -> float:
        return sum(self.phases().values())


def _headers(message: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    raw = message.get("headers")
    if not isinstance(raw, list):
        return ()
    return tuple(
        (str(h.get("name", "")), str(h.get("value", ""))) for h in raw if isinstance(h, dict)
    )


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


@dataclass(frozen=True, slots=True)
class Entry:
    number: int  # 1-based, as people say "request #12"
    method: str
    url: str
    status: int  # 0 when no response arrived
    status_text: str
    http_version: str
    started: datetime | None
    time_ms: float
    timings: Timings
    request_headers: tuple[tuple[str, str], ...]
    response_headers: tuple[tuple[str, str], ...]
    mime: str
    resource_type: str
    request_body_size: int
    response_body_size: int
    transfer_size: int
    error: str
    redirect_url: str
    server_ip: str
    page_ref: str
    error_body: Any = None
    meta: EntryMeta = field(default_factory=EntryMeta)

    # -- URL parts -----------------------------------------------------------

    @property
    def scheme(self) -> str:
        return split(self.url).scheme.lower()

    @property
    def host(self) -> str:
        try:
            return (split(self.url).hostname or "").lower()
        except ValueError:
            return ""

    @property
    def origin(self) -> str:
        parts = split(self.url)
        return f"{parts.scheme}://{parts.netloc}".lower() if parts.netloc else ""

    @property
    def path(self) -> str:
        return split(self.url).path or "/"

    @property
    def short_url(self) -> str:
        """Scheme, host and path, without the query string."""
        parts = split(self.url)
        return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}" if parts.netloc else self.url

    # -- headers -------------------------------------------------------------

    def request_header(self, name: str) -> str | None:
        lowered = name.lower()
        for k, v in self.request_headers:
            if k.lower() == lowered:
                return v
        return None

    def response_header(self, name: str) -> str | None:
        lowered = name.lower()
        for k, v in self.response_headers:
            if k.lower() == lowered:
                return v
        return None

    # -- classification --------------------------------------------------------

    @property
    def is_http(self) -> bool:
        return self.scheme in ("http", "https", "ws", "wss")

    @property
    def failed(self) -> bool:
        return self.status >= 400 or self.status == 0 or bool(self.error)

    @property
    def is_network_error(self) -> bool:
        return self.status == 0 or bool(self.error)

    @property
    def is_preflight(self) -> bool:
        return (
            self.method == "OPTIONS"
            and self.request_header("access-control-request-method") is not None
        )

    @property
    def long_lived(self) -> bool:
        """Server-sent events, websockets and similar connections are slow by design."""
        return (
            "text/event-stream" in self.mime
            or self.status == 101
            or self.resource_type in ("websocket", "eventsource")
            or self.scheme in ("ws", "wss")
        )

    @property
    def label(self) -> str:
        status = str(self.status) if self.status else (self.error or "no response")
        return f"#{self.number} {self.method} {self.short_url} → {status}"

    # -- construction ------------------------------------------------------------

    @classmethod
    def from_har(cls, number: int, raw: dict[str, Any], meta: EntryMeta | None = None) -> Entry:
        request = raw.get("request") if isinstance(raw.get("request"), dict) else {}
        response = raw.get("response") if isinstance(raw.get("response"), dict) else {}
        request = request if isinstance(request, dict) else {}
        response = response if isinstance(response, dict) else {}
        content = response.get("content") if isinstance(response.get("content"), dict) else {}
        content = content if isinstance(content, dict) else {}

        status = response.get("status")
        status = (
            int(status) if isinstance(status, int | float) and not isinstance(status, bool) else 0
        )
        if status < 0:  # Playwright writes -1 for "no response"
            status = 0

        error = ""
        for source in (raw, response):
            for key in ("_error", "_failureText", "_errorText"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    error = value.strip()
                    break
            if error:
                break
        if not error and status == 0:
            text = str(response.get("statusText") or "")
            if text.startswith(("net::", "NS_", "SSL_", "SEC_", "MOZILLA_PKIX")):
                error = text

        resource_type = str(raw.get("_resourceType") or raw.get("_type") or "").lower()

        error_body = None
        body = content.get("text")
        if isinstance(body, str) and body and (status >= 400 or content.get("_partial")):
            try:
                error_body = json.loads(body)
            except ValueError:
                error_body = None

        def _int(value: Any) -> int:
            if isinstance(value, bool):
                return 0
            return int(value) if isinstance(value, int | float) and value > 0 else 0

        time_ms = raw.get("time")
        timings = Timings.from_har(raw.get("timings"))
        return cls(
            number=number,
            method=str(request.get("method") or "GET").upper(),
            url=str(request.get("url") or ""),
            status=status,
            status_text=str(response.get("statusText") or ""),
            http_version=str(response.get("httpVersion") or request.get("httpVersion") or ""),
            started=parse_time(raw.get("startedDateTime")),
            time_ms=float(time_ms)
            if isinstance(time_ms, int | float) and not isinstance(time_ms, bool) and time_ms >= 0
            else timings.total(),
            timings=timings,
            request_headers=_headers(request),
            response_headers=_headers(response),
            mime=str(content.get("mimeType") or "").lower(),
            resource_type=resource_type,
            request_body_size=max(
                _int(request.get("bodySize")), meta.request_body_bytes if meta else 0
            ),
            response_body_size=_int(content.get("size")) or _int(response.get("bodySize")),
            transfer_size=_int(response.get("_transferSize")) or _int(response.get("bodySize")),
            error=error,
            redirect_url=str(response.get("redirectURL") or ""),
            server_ip=str(raw.get("serverIPAddress") or ""),
            page_ref=str(raw.get("pageref") or ""),
            error_body=error_body,
            meta=meta or EntryMeta(),
        )
