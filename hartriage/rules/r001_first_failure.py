"""R001: the first request that failed, and the failures that followed on the same host.

The first failure is usually the cause; later errors on the same host are often
knock-on effects (a 401 on login, then every API call after it fails too).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import is_noise, numbers, plural


@dataclass(frozen=True, slots=True)
class _Failure:
    number: int
    started: datetime | None
    host: str
    status: int
    error: str
    method: str
    url: str
    status_text: str


class FirstFailure(Rule):
    id = "R001"
    slug = "first-failure"
    title = "First failure"
    summary = "The first request with status 400 or above, status 0 or a network error."

    def __init__(self) -> None:
        self._failures: list[_Failure] = []

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        if entry.failed and not is_noise(entry):
            self._failures.append(
                _Failure(
                    entry.number,
                    entry.started,
                    entry.host,
                    entry.status,
                    entry.error,
                    entry.method,
                    entry.short_url,
                    entry.status_text,
                )
            )
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        if not self._failures:
            return []

        def key(f: _Failure) -> tuple[float, int]:
            return (f.started.timestamp() if f.started else float(f.number), f.number)

        ordered = sorted(self._failures, key=key)
        first = ordered[0]
        followers = [f.number for f in ordered[1:] if f.host == first.host]
        other_hosts = sorted({f.host for f in ordered[1:] if f.host != first.host})
        outcome = str(first.status) if first.status else (first.error or "no response")
        if first.status and first.status_text:
            outcome = f"{first.status} {first.status_text}"

        if first.status in (401, 403):
            cause = (
                "The first failure is an authentication or permission error, so the"
                " failures that follow it are probably knock-on effects."
            )
        elif first.status >= 500:
            cause = "The first failure is a server-side error on " + first.host + "."
        elif first.status == 0 or first.error:
            cause = (
                f"The browser could not complete the first failing request"
                f" ({first.error or 'no response was recorded'})."
            )
        elif first.status == 404:
            cause = "The first failure is a 404: the app asked for something that is not there."
        else:
            cause = f"The server rejected the first failing request with {outcome}."

        after = (
            f" {plural(len(followers), 'later failure')} on {first.host}"
            f" ({numbers(followers)}) may be knock-on effects."
            if followers
            else ""
        )
        return [
            self.finding(
                severity=Severity.HIGH,
                title=f"First failure: #{first.number} {first.method} {first.url} → {outcome}",
                cause=cause,
                next_step=f"Start the investigation at request #{first.number}.{after}",
                entries=[first.number, *followers],
                evidence={
                    "method": first.method,
                    "url": first.url,
                    "status": first.status,
                    "status_text": first.status_text,
                    "error": first.error,
                    "host": first.host,
                    "started": first.started.isoformat() if first.started else None,
                    "followers": followers[:50],
                    "follower_count": len(followers),
                    "other_failing_hosts": other_hosts[:10],
                    "total_failures": len(ordered),
                },
            )
        ]
