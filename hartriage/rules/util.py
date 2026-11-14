"""Helpers shared by the rules."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from hartriage.har.model import Entry
from hartriage.har.model import split as urlsplit

ABORTED = ("net::ERR_ABORTED", "NS_BINDING_ABORTED", "NS_ERROR_ABORT")
BLOCKED_BY_CLIENT = ("net::ERR_BLOCKED_BY_CLIENT",)

_ID_SEGMENT = re.compile(
    r"^(?:\d+|[0-9a-fA-F]{8,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}|(?=.*\d)[A-Za-z0-9_-]{16,})$"
)
_MARKER = re.compile(r"\[REDACTED:[0-9a-f]{8}\]")


def is_noise(entry: Entry) -> bool:
    """Requests that fail all the time without meaning anything."""
    if not entry.is_http:
        return True
    if entry.path.endswith("/favicon.ico"):
        return True
    return any(entry.error.startswith(e) for e in ABORTED + BLOCKED_BY_CLIENT)


def endpoint(entry: Entry) -> str:
    """`GET api.example.com/orders/{id}`: the URL with ids and secrets folded together."""
    segments = []
    for segment in entry.path.split("/"):
        if _MARKER.search(segment):
            segments.append("{redacted}")
        elif _ID_SEGMENT.match(segment):
            segments.append("{id}")
        else:
            segments.append(segment)
    return f"{entry.method} {entry.host}{'/'.join(segments) or '/'}"


def seconds(ms: float) -> str:
    if ms >= 60_000:
        return f"{ms / 60_000:.1f} min"
    if ms >= 1000:
        return f"{ms / 1000:.1f} s"
    return f"{ms:.0f} ms"


def size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} bytes"


def duration_words(total_seconds: float) -> str:
    s = abs(total_seconds)
    if s < 90:
        return f"{s:.0f} seconds"
    if s < 90 * 60:
        return f"{s / 60:.0f} minutes"
    if s < 36 * 3600:
        return f"{s / 3600:.1f} hours"
    return f"{s / 86400:.1f} days"


def iso(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def plural(n: int, word: str, plural_word: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural_word or word + 's')}"


def numbers(nums: list[int], limit: int = 10) -> str:
    shown = ", ".join(f"#{n}" for n in nums[:limit])
    return shown + (f" and {len(nums) - limit} more" if len(nums) > limit else "")


def retry_after_seconds(value: str | None, now: datetime | None) -> float | None:
    """Parse Retry-After: either delta-seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if now is None or when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.netloc else ""


SESSION_PATH = re.compile(
    r"/(me|whoami|session|sessions|current[-_]?user|auth|oauth|token|refresh|login|signin)(/|$)",
    re.IGNORECASE,
)


class SignInTracker:
    """Spot "sign-in probes": requests refused with 401 because no credentials were
    sent yet, followed by requests to the same host that succeed *with* credentials.

    Apps check for a session on page load ("GET /me") before the user signs in. Those
    401s are expected, and must not be reported as the first failure.
    """

    def __init__(self) -> None:
        self._first_authed_success: dict[str, float] = {}

    def observe(self, entry: Entry) -> None:
        if entry.meta.credentials_present and 200 <= entry.status < 400 and entry.started:
            when = entry.started.timestamp()
            current = self._first_authed_success.get(entry.host)
            if current is None or when < current:
                self._first_authed_success[entry.host] = when

    def is_probe(
        self,
        host: str,
        status: int,
        credentials_present: bool,
        started: datetime | None,
        path: str = "",
    ) -> bool:
        if status != 401 or credentials_present or started is None:
            return False
        success = self._first_authed_success.get(host)
        if success is None:
            return False
        # Session checks ("/me", "/auth/refresh") are probes whenever they ran; any other
        # call is only a probe if it ran before the app had credentials.
        return bool(SESSION_PATH.search(path)) or started.timestamp() <= success
