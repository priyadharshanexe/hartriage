"""R003: likely CORS failures.

Marked "likely": the browser enforces CORS after the network layer, and HAR files
often record the response as if nothing went wrong. The console has the final word.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import is_noise, numbers


@dataclass
class _Group:
    origin: str
    target: str
    kind: str
    entries: list[int] = field(default_factory=list)
    reason: str = ""
    status: int = 0


def _list(value: str | None) -> set[str]:
    return {v.strip().lower() for v in (value or "").split(",") if v.strip()}


class Cors(Rule):
    id = "R003"
    slug = "cors"
    title = "CORS failures (likely)"
    summary = "Failed preflights and cross-origin responses missing Access-Control-Allow-Origin."

    def __init__(self) -> None:
        self._groups: dict[tuple[str, str, str], _Group] = {}

    def _add(self, entry: Entry, origin: str, kind: str, reason: str) -> None:
        key = (origin, entry.origin, kind)
        group = self._groups.get(key)
        if group is None:
            group = self._groups[key] = _Group(
                origin, entry.origin, kind, reason=reason, status=entry.status
            )
        group.entries.append(entry.number)

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        if is_noise(entry):
            return ()
        origin = (entry.request_header("origin") or "").lower()
        if not origin or origin == "null" or origin == entry.origin:
            return ()
        mode = (entry.request_header("sec-fetch-mode") or "cors").lower()
        if mode not in ("cors",) and not entry.is_preflight:
            return ()
        allow_origin = entry.response_header("access-control-allow-origin")
        if entry.is_preflight:
            method = (entry.request_header("access-control-request-method") or "").upper()
            wanted_headers = _list(entry.request_header("access-control-request-headers"))
            if entry.status == 0:
                self._add(
                    entry,
                    origin,
                    "preflight",
                    f"the preflight got no response ({entry.error or 'no status'})",
                )
            elif not 200 <= entry.status < 300:
                self._add(
                    entry, origin, "preflight", f"the preflight was answered with {entry.status}"
                )
            elif allow_origin is None:
                self._add(
                    entry,
                    origin,
                    "preflight",
                    "the preflight response has no Access-Control-Allow-Origin",
                )
            elif (
                allow_origin.strip() not in ("*", origin) and allow_origin.strip().lower() != origin
            ):
                self._add(
                    entry,
                    origin,
                    "preflight",
                    f"the preflight allows origin {allow_origin.strip()}, not {origin}",
                )
            else:
                allowed_methods = _list(entry.response_header("access-control-allow-methods"))
                allowed_headers = _list(entry.response_header("access-control-allow-headers"))
                simple = {"GET", "HEAD", "POST"}
                if (
                    method
                    and method not in simple
                    and allowed_methods
                    and "*" not in allowed_methods
                    and method.lower() not in allowed_methods
                ):
                    self._add(
                        entry, origin, "preflight", f"the preflight does not allow method {method}"
                    )
                missing = wanted_headers - allowed_headers
                if wanted_headers and "*" not in allowed_headers and missing:
                    self._add(
                        entry,
                        origin,
                        "preflight",
                        "the preflight does not allow header(s) " + ", ".join(sorted(missing)),
                    )
            return ()
        if entry.status == 0:
            if (
                entry.error in ("net::ERR_FAILED", "NS_ERROR_DOM_BAD_URI", "")
                and not entry.response_headers
            ):
                self._add(
                    entry,
                    origin,
                    "blocked",
                    "the browser recorded no response for a cross-origin request",
                )
            return ()
        if allow_origin is None:
            self._add(
                entry, origin, "missing", "the response has no Access-Control-Allow-Origin header"
            )
        elif allow_origin.strip() == "*" and entry.request_header("cookie"):
            credentials = (entry.response_header("access-control-allow-credentials") or "").lower()
            if credentials != "true":
                self._add(
                    entry,
                    origin,
                    "credentials",
                    "cookies were sent but the response allows any origin (*) without credentials",
                )
        elif allow_origin.strip().lower() not in ("*", origin):
            self._add(
                entry,
                origin,
                "mismatch",
                f"the response allows origin {allow_origin.strip()}, not {origin}",
            )
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        out = []
        for g in self._groups.values():
            if g.kind == "preflight":
                cause = (
                    f"The browser's preflight check for {g.target} failed ({g.reason}), so the"
                    " real request was never sent."
                )
            elif g.kind == "blocked":
                cause = (
                    f"Requests from {g.origin} to {g.target} ended with no response, which is"
                    " how a CORS block often looks in a HAR file."
                )
            else:
                cause = (
                    f"The browser blocks {g.origin} from reading responses from {g.target}:"
                    f" {g.reason}."
                )
            out.append(
                self.finding(
                    severity=Severity.HIGH,
                    title=f"Likely CORS failure: {g.origin} → {g.target} ({numbers(g.entries, 5)})",
                    cause=cause,
                    next_step=(
                        f"Ask the owner of {g.target} to allow the origin {g.origin}"
                        " (Access-Control-Allow-Origin, and -Methods/-Headers for preflights)."
                        " Confirm in the browser console: it shows CORS errors a HAR file"
                        " often leaves out."
                    ),
                    entries=list(g.entries),
                    evidence={
                        "origin": g.origin,
                        "target": g.target,
                        "kind": g.kind,
                        "reason": g.reason,
                        "status": g.status,
                        "count": len(g.entries),
                    },
                    confidence="likely",
                )
            )
        return out
