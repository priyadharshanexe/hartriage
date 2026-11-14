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
