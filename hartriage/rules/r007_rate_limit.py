"""R007: 429 Too Many Requests, Retry-After and whether the client honoured it."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import endpoint, numbers, plural, retry_after_seconds, seconds

_LIMIT_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "ratelimit",
    "ratelimit-policy",
    "x-rate-limit-limit",
    "x-rate-limit-remaining",
    "x-rate-limit-reset",
)


@dataclass
class _Host:
    host: str
    entries: list[int] = field(default_factory=list)
    retry_after: list[float] = field(default_factory=list)
    limits: dict[str, str] = field(default_factory=dict)
    early_retries: list[int] = field(default_factory=list)
    shortest_wait_ms: float | None = None


class RateLimit(Rule):
    id = "R007"
    slug = "rate-limit"
    title = "Rate limiting (429)"
    summary = "429 responses: Retry-After, X-RateLimit-* and retries sent before the wait was over."

    def __init__(self) -> None:
        self._hosts: dict[str, _Host] = {}
        # endpoint -> (when the 429 arrived, how long the server asked the client to wait)
        self._backoff: dict[str, tuple[datetime, float]] = {}

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        key = endpoint(entry)
        if entry.started is not None and key in self._backoff:
            when, wait_s = self._backoff[key]
            gap_ms = (entry.started - when).total_seconds() * 1000
            if 0 <= gap_ms < wait_s * 1000:
                host = self._hosts[entry.host]
                host.early_retries.append(entry.number)
                if host.shortest_wait_ms is None or gap_ms < host.shortest_wait_ms:
                    host.shortest_wait_ms = gap_ms
        if entry.status != 429:
            return ()
        host = self._hosts.setdefault(entry.host, _Host(entry.host))
        host.entries.append(entry.number)
        for name in _LIMIT_HEADERS:
            value = entry.response_header(name)
            if value and name not in host.limits:
                host.limits[name] = value[:100]
        after = retry_after_seconds(entry.response_header("retry-after"), entry.started)
        if after is not None:
            host.retry_after.append(after)
            if entry.started is not None:
                done = entry.started.timestamp() + entry.time_ms / 1000
                self._backoff[key] = (datetime.fromtimestamp(done, entry.started.tzinfo), after)
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        out = []
        for h in self._hosts.values():
            n = len(h.entries)
            wait = max(h.retry_after) if h.retry_after else None
            cause = f"{h.host} rate-limited the client: {plural(n, 'request')} got 429 Too Many Requests"
            if h.early_retries and wait is not None:
                cause += (
                    f", and the client tried again {plural(len(h.early_retries), 'time')}"
                    f" after only {seconds(h.shortest_wait_ms or 0)} although the server"
                    f" asked it to wait {wait:.0f} s"
                )
            elif wait is not None:
                cause += f"; the server asked the client to wait {wait:.0f} s (Retry-After)"
            limit = h.limits.get("x-ratelimit-limit") or h.limits.get("ratelimit-limit")
            if limit:
                cause += f"; the limit is {limit} per window"
            cause += "."
            out.append(
                self.finding(
                    severity=Severity.HIGH,
                    title=f"Rate limited by {h.host}: {plural(n, '429 response')} ({numbers(h.entries, 5)})",
                    cause=cause,
                    next_step=(
                        "Make the client honour Retry-After and back off exponentially with"
                        " jitter. Check whether several tabs, scripts or integrations share one"
                        " API key and its limit."
                    ),
                    entries=list(h.entries) + [e for e in h.early_retries if e not in h.entries],
                    evidence={
                        "host": h.host,
                        "count": n,
                        "retry_after_seconds": wait,
                        "limits": h.limits,
                        "early_retries": h.early_retries[:20],
                        "shortest_wait_ms": round(h.shortest_wait_ms)
                        if h.shortest_wait_ms is not None
                        else None,
                    },
                )
            )
        return out
