"""R008: 413 (body too large), 414 (URL too long), 431 (headers too large) and big uploads."""

from __future__ import annotations

from collections.abc import Iterable

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import size


class Payload(Rule):
    id = "R008"
    slug = "payload"
    title = "Payload too large"
    summary = "413, 414 and 431 responses, and request bodies over 5 MB."

    def __init__(self) -> None:
        self._out: list[Finding] = []

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        meta = entry.meta
        if entry.status == 413:
            sent = entry.request_body_size or meta.request_body_bytes
            content_length = entry.request_header("content-length")
            if not sent and content_length and content_length.isdigit():
                sent = int(content_length)
            return [
                self.finding(
                    severity=Severity.HIGH,
                    title=f"413 Payload Too Large: #{entry.number} {entry.method} {entry.short_url}",
                    cause=(
                        f"{entry.host} refused the request body as too large"
                        + (f" ({size(sent)} sent)" if sent else "")
                        + "."
                    ),
                    next_step=(
                        "Reduce the payload (fewer items per request, compress, or upload files"
                        " separately), or ask whether the limit can be raised for this account."
                    ),
                    entries=[entry.number],
                    evidence={
                        "status": 413,
                        "request_bytes": sent,
                        "url": entry.short_url,
                        "method": entry.method,
                    },
                )
            ]
        if entry.status == 414:
            return [
                self.finding(
                    severity=Severity.HIGH,
                    title=f"414 URI Too Long: #{entry.number} {entry.short_url}",
                    cause=f"The URL was too long for {entry.host} ({len(entry.url):,} characters).",
                    next_step="Send the data in a POST body instead of the query string.",
                    entries=[entry.number],
                    evidence={"status": 414, "url_length": len(entry.url)},
                )
            ]
        if entry.status == 431:
            cookie = meta.cookie_header_bytes
            return [
                self.finding(
                    severity=Severity.HIGH,
                    title=f"431 Request Header Fields Too Large: #{entry.number} {entry.short_url}",
                    cause=(
                        f"The request headers were too large for {entry.host}"
                        f" ({size(meta.request_header_bytes)}"
                        + (f"; the Cookie header alone was {size(cookie)}" if cookie else "")
                        + ")."
                    ),
                    next_step=(
                        "Ask the customer to clear cookies for this site; if it recurs, the app is"
                        " setting too many or too large cookies."
                    ),
                    entries=[entry.number],
                    evidence={
                        "status": 431,
                        "request_header_bytes": meta.request_header_bytes,
                        "cookie_header_bytes": cookie,
                    },
                )
            ]
        body = max(entry.request_body_size, meta.request_body_bytes)
        if body >= ctx.config.large_request_bytes and entry.status < 400:
            self._out.append(
                self.finding(
                    severity=Severity.INFO,
                    title=f"Large upload: #{entry.number} sent {size(body)}",
                    cause=f"Request #{entry.number} uploaded {size(body)}, close to common server limits.",
                    next_step="If uploads fail intermittently, check the server's body size limit.",
                    entries=[entry.number],
                    evidence={"request_bytes": body, "url": entry.short_url},
                )
            )
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        return self._out
