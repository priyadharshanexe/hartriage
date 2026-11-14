"""R011: 5xx errors grouped by endpoint, with the correlation ids engineering needs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import endpoint, numbers, plural, retry_after_seconds

_NAMES = {
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


@dataclass
class _Group:
    endpoint: str
    statuses: dict[int, int] = field(default_factory=dict)
    entries: list[int] = field(default_factory=list)
    correlation_ids: list[dict[str, str]] = field(default_factory=list)
    servers: set[str] = field(default_factory=set)
    retry_after: float | None = None


class ServerErrors(Rule):
    id = "R011"
    slug = "server-errors"
    title = "Server errors (5xx)"
    summary = "5xx responses grouped by endpoint, with the correlation ids to hand to engineering."

    def __init__(self) -> None:
        self._groups: dict[str, _Group] = {}

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        if not 500 <= entry.status <= 599:
            return ()
        key = endpoint(entry)
        group = self._groups.setdefault(key, _Group(key))
        group.statuses[entry.status] = group.statuses.get(entry.status, 0) + 1
        group.entries.append(entry.number)
        if entry.meta.correlation_ids and len(group.correlation_ids) < 20:
            group.correlation_ids.append({"entry": str(entry.number), **entry.meta.correlation_ids})
        server = entry.response_header("server")
        if server:
            group.servers.add(server[:60])
        after = retry_after_seconds(entry.response_header("retry-after"), entry.started)
        if after is not None:
            group.retry_after = after
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        out = []
        for g in sorted(self._groups.values(), key=lambda g: g.entries[0]):
            statuses = ", ".join(
                f"{s} {_NAMES.get(s, '')}".strip() + (f" ×{c}" if c > 1 else "")
                for s, c in sorted(g.statuses.items())
            )
            n = len(g.entries)
            gateway = any(s in (502, 504) for s in g.statuses)
            cause = f"{g.endpoint} failed on the server side ({statuses})"
            if gateway:
                cause += "; 502/504 mean a proxy or load balancer got no good answer from the app behind it"
            if g.retry_after is not None:
                cause += f"; the server asked clients to retry after {g.retry_after:.0f} s"
            cause += "."
            ids = [i for i in g.correlation_ids if len(i) > 1]
            step = "Escalate to engineering with " + (
                "the correlation ids below: they locate the exact server log lines."
                if ids
                else "the request numbers and timestamps (the response carried no request id)."
            )
            out.append(
                self.finding(
                    severity=Severity.HIGH,
                    title=f"Server error: {g.endpoint} → {plural(n, 'failure')} ({numbers(g.entries, 5)})",
                    cause=cause,
                    next_step=step,
                    entries=list(g.entries),
                    evidence={
                        "endpoint": g.endpoint,
                        "statuses": {str(k): v for k, v in g.statuses.items()},
                        "count": n,
                        "correlation_ids": ids,
                        "servers": sorted(g.servers),
                    },
                )
            )
        return out
