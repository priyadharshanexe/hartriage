"""R010: http:// resources on an https:// page."""

from __future__ import annotations

from collections.abc import Iterable

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import numbers, plural

_LOCAL = ("localhost", "127.0.0.1", "[::1]", "::1")
_ACTIVE_TYPES = ("script", "xhr", "fetch", "stylesheet", "document", "iframe", "websocket")


def is_active(entry: Entry) -> bool:
    if entry.resource_type:
        return entry.resource_type in _ACTIVE_TYPES
    return not entry.mime.startswith(("image/", "audio/", "video/"))


class MixedContent(Rule):
    id = "R010"
    slug = "mixed-content"
    title = "Mixed content"
    summary = "Plain http:// resources loaded by an https:// page."

    def __init__(self) -> None:
        self._active: list[int] = []
        self._passive: list[int] = []
        self._examples: list[str] = []
        self._page = ""

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        if not self._page and (entry.resource_type == "document" or "text/html" in entry.mime):
            self._page = entry.url
        page = self._page or ctx.page_url
        if not page.startswith("https://") or entry.scheme not in ("http", "ws"):
            return ()
        if entry.host in _LOCAL or entry.host.endswith(".localhost"):
            return ()
        (self._active if is_active(entry) else self._passive).append(entry.number)
        if len(self._examples) < 5:
            self._examples.append(entry.short_url)
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        if not (self._active or self._passive):
            return []
        nums = self._active + self._passive
        severity = Severity.HIGH if self._active else Severity.MEDIUM
        kinds = []
        if self._active:
            kinds.append(
                f"{plural(len(self._active), 'script, style or API call')} (browsers block these)"
            )
        if self._passive:
            kinds.append(
                f"{plural(len(self._passive), 'image or media file')} (browsers upgrade or block these)"
            )
        return [
            self.finding(
                severity=severity,
                title=f"Mixed content: {plural(len(nums), 'http:// request')} on an https:// page",
                cause="The secure page loads " + " and ".join(kinds) + " over plain http.",
                next_step="Change these URLs to https:// (or protocol-relative); check the CDN/asset settings.",
                entries=sorted(nums),
                evidence={
                    "page": (self._page or ctx.page_url)[:300],
                    "active": self._active[:50],
                    "passive": self._passive[:50],
                    "examples": self._examples,
                    "listed": numbers(sorted(nums)),
                },
            )
        ]
