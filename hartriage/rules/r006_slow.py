"""R006: slow requests, and which phase the time went into."""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import numbers, plural, seconds, size

PHASE_NAMES = {
    "blocked": "queued in the browser",
    "dns": "DNS lookup",
    "connect": "connecting",
    "ssl": "TLS handshake",
    "send": "uploading",
    "wait": "waiting for the server",
    "receive": "downloading",
}


@dataclass(frozen=True, order=True, slots=True)
class _Slow:
    time_ms: float
    number: int
    url: str
    phase: str
    phase_ms: float
    response_bytes: int


class Slow(Rule):
    id = "R006"
    slug = "slow"
    title = "Slow requests"
    summary = "Requests over the threshold (3 s by default), with the phase that took the time."
    keep = 200

    def __init__(self) -> None:
        self._slow: list[_Slow] = []  # a min-heap of the slowest requests
        self.count = 0

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        if entry.long_lived or entry.time_ms < ctx.config.slow_ms:
            return ()
        phases = entry.timings.phases()
        if not phases:
            return ()
        phase, phase_ms = max(phases.items(), key=lambda kv: kv[1])
        self.count += 1
        item = _Slow(
            entry.time_ms, entry.number, entry.short_url, phase, phase_ms, entry.response_body_size
        )
        if len(self._slow) < self.keep:
            heapq.heappush(self._slow, item)
        else:
            heapq.heappushpop(self._slow, item)
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        by_phase: dict[str, list[_Slow]] = {}
        for item in sorted(self._slow, reverse=True):
            by_phase.setdefault(item.phase, []).append(item)
        out = []
        for phase, items in by_phase.items():
            worst = items[0]
            t = seconds(worst.phase_ms)
            causes = {
                "wait": f"The server took up to {t} to start answering: the time is spent in the backend, not the network.",
                "blocked": (
                    f"Requests sat in the browser's queue for up to {t} before being sent: too"
                    " many parallel requests to one host, a busy service worker, or a slow proxy."
                ),
                "dns": f"DNS lookups took up to {t}: a slow or unreachable DNS resolver (VPN or corporate DNS).",
                "connect": f"Opening connections took up to {t}: network latency, packet loss or a busy firewall.",
                "ssl": f"TLS handshakes took up to {t}: a TLS-inspecting proxy, or a distant or overloaded server.",
                "send": f"Uploading took up to {t}: a large request on a slow uplink.",
                "receive": (
                    f"Downloading took up to {t}"
                    + (f" for {size(worst.response_bytes)}" if worst.response_bytes else "")
                    + ": a large response or a slow connection."
                ),
            }
            steps = {
                "wait": "Escalate to engineering with these requests: the endpoint is slow server-side.",
                "blocked": "Reduce parallel requests (or move to HTTP/2), and check service workers and proxy settings.",
                "dns": "Try another DNS resolver or network; check VPN DNS settings.",
                "connect": "Test from another network to separate the customer's network from the server.",
                "ssl": "Test without the VPN/proxy; check the server's TLS setup and location.",
                "send": "Compress or split the upload; test the customer's upload speed.",
                "receive": "Paginate or compress the response; test the customer's download speed.",
            }
            nums = [i.number for i in items]
            out.append(
                self.finding(
                    severity=Severity.HIGH
                    if worst.time_ms >= ctx.config.very_slow_ms
                    else Severity.MEDIUM,
                    title=(
                        f"Slow: {plural(len(items), 'request')} mostly {PHASE_NAMES[phase]}"
                        f" (slowest #{worst.number}, {seconds(worst.time_ms)})"
                    ),
                    cause=causes[phase],
                    next_step=steps[phase],
                    entries=nums,
                    evidence={
                        "phase": phase,
                        "threshold_ms": ctx.config.slow_ms,
                        "requests": [
                            {
                                "entry": i.number,
                                "url": i.url,
                                "total_ms": round(i.time_ms),
                                "phase_ms": round(i.phase_ms),
                            }
                            for i in items[: ctx.config.max_listed]
                        ],
                        "count": len(items),
                        "listed": numbers(nums),
                    },
                )
            )
        return out
