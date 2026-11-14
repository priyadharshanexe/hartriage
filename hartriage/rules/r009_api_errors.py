"""R009: JSON error bodies, grouped by error code and message.

Only small JSON bodies of failed responses are kept after redaction (see the
redaction policy), plus the `errors` array of GraphQL answers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import numbers, plural

_CODE_KEYS = ("code", "error_code", "errorCode", "type", "error", "status_code", "reason")
_MESSAGE_KEYS = (
    "message",
    "error_description",
    "detail",
    "title",
    "description",
    "error_message",
    "errorMessage",
    "msg",
)


def _first(obj: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = obj.get(key)
        if (
            isinstance(value, str | int | float)
            and not isinstance(value, bool)
            and str(value).strip()
        ):
            return str(value).strip()
    return ""


def extract_error(body: Any) -> tuple[str, str] | None:
    """Pull (code, message) out of the common error shapes."""
    if isinstance(body, list) and body and isinstance(body[0], dict):
        body = {"errors": body}
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if isinstance(error, dict):  # {"error": {"code": ..., "message": ...}}
        code, message = _first(error, _CODE_KEYS), _first(error, _MESSAGE_KEYS)
        if code or message:
            return code, message
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):  # JSON:API, GraphQL
        first = errors[0]
        extensions = first.get("extensions") if isinstance(first.get("extensions"), dict) else {}
        code = _first(first, _CODE_KEYS) or _first(extensions or {}, _CODE_KEYS)
        message = _first(first, _MESSAGE_KEYS)
        if code or message:
            return code, message
    if isinstance(errors, dict):  # {"errors": {"field": ["is required"]}}
        parts = [
            f"{k}: {v[0] if isinstance(v, list) and v else v}" for k, v in list(errors.items())[:3]
        ]
        return "validation", "; ".join(str(p) for p in parts)
    if isinstance(body.get("detail"), list) and body["detail"]:  # FastAPI validation errors
        first = body["detail"][0]
        if isinstance(first, dict):
            loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
            return str(first.get("type", "validation")), f"{loc}: {first.get('msg', '')}".strip(
                ": "
            )
    code = _first(body, _CODE_KEYS)
    message = _first(body, _MESSAGE_KEYS)
    if isinstance(error, str) and not message:
        message = _first(body, ("error_description",)) or ""
    if code or message:
        return code, message
    return None


@dataclass
class _Group:
    code: str
    message: str
    statuses: set[int] = field(default_factory=set)
    hosts: set[str] = field(default_factory=set)
    entries: list[int] = field(default_factory=list)


class ApiErrors(Rule):
    id = "R009"
    slug = "api-errors"
    title = "API error messages"
    summary = "JSON error bodies grouped by code and message."

    def __init__(self) -> None:
        self._groups: dict[tuple[str, str], _Group] = {}

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        if entry.error_body is None:
            return ()
        found = extract_error(entry.error_body)
        if found is None:
            return ()
        code, message = found[0][:120], found[1][:300]
        group = self._groups.setdefault((code, message), _Group(code, message))
        group.statuses.add(entry.status)
        group.hosts.add(entry.host)
        group.entries.append(entry.number)
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        out = []
        groups = sorted(self._groups.values(), key=lambda g: (-len(g.entries), g.entries[0]))
        for g in groups[: ctx.config.max_listed]:
            hosts = ", ".join(sorted(g.hosts))
            label = g.code or "error"
            statuses = "/".join(str(s) for s in sorted(g.statuses))
            quoted = f": “{g.message}”" if g.message else ""
            out.append(
                self.finding(
                    severity=Severity.MEDIUM,
                    title=(
                        f"API error {g.code} ({statuses}){quoted} × {len(g.entries)}"
                        if g.code
                        else f"API error ({statuses}){quoted} × {len(g.entries)}"
                    ),
                    cause=f"{hosts} answered {plural(len(g.entries), 'request')} with error {label}{quoted}.",
                    next_step=(
                        "Look the error code up in the API's documentation or the KB, and include"
                        " the message and request numbers in any escalation."
                    ),
                    entries=list(g.entries),
                    evidence={
                        "code": g.code,
                        "message": g.message,
                        "statuses": sorted(g.statuses),
                        "hosts": sorted(g.hosts),
                        "count": len(g.entries),
                        "listed": numbers(g.entries),
                    },
                )
            )
        return out
