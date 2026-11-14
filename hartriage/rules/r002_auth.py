"""R002: 401 and 403 responses. Were credentials sent, had the token expired, what did
the server say in WWW-Authenticate?"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import SignInTracker, duration_words, is_noise, iso, numbers, plural

_PARAM = re.compile(r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))')
_CDN_SERVERS = ("cloudflare", "akamai", "cloudfront", "fastly", "imperva", "sucuri")


def parse_www_authenticate(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    params = {
        m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3)
        for m in _PARAM.finditer(value)
    }
    scheme = value.strip().split(None, 1)[0] if value.strip() else ""
    if scheme and "=" not in scheme:
        params.setdefault("scheme", scheme)
    return params


@dataclass
class _Group:
    status: int
    host: str
    kind: str
    entries: list[int] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    starts: list[datetime | None] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


class Auth(Rule):
    id = "R002"
    slug = "auth"
    title = "Authentication and permission errors"
    summary = "401/403: were credentials sent, had the JWT expired, what WWW-Authenticate said."

    def __init__(self) -> None:
        self._groups: dict[tuple[int, str, str], _Group] = {}
        self._sign_in = SignInTracker()

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        self._sign_in.observe(entry)
        if entry.status not in (401, 403) or is_noise(entry):
            return ()
        kind, detail = self._classify(entry)
        key = (entry.status, entry.host, kind)
        group = self._groups.get(key)
        if group is None:
            group = self._groups[key] = _Group(entry.status, entry.host, kind, detail=detail)
        group.entries.append(entry.number)
        group.starts.append(entry.started)
        group.paths.append(entry.path)
        return ()

    def _classify(self, entry: Entry) -> tuple[str, dict[str, Any]]:
        meta = entry.meta
        www = parse_www_authenticate(entry.response_header("www-authenticate"))
        detail: dict[str, Any] = {
            "credentials": meta.credentials,
            "www_authenticate": entry.response_header("www-authenticate") or "",
            "server": entry.response_header("server") or "",
        }
        started = entry.started.timestamp() if entry.started else None
        for jwt in meta.jwts:
            info: dict[str, Any] = {
                "token": jwt.marker,
                "location": jwt.location,
                "exp": iso(jwt.exp),
                "iat": iso(jwt.iat),
                "aud": jwt.aud,
            }
            if started is not None and jwt.exp is not None and jwt.exp < started:
                info["expired_seconds_before_request"] = int(started - jwt.exp)
                detail["jwt"] = info
                return "expired_token", detail
            if started is not None and jwt.nbf is not None and jwt.nbf > started + 60:
                info["not_valid_for_seconds"] = int(jwt.nbf - started)
                detail["jwt"] = info
                return "not_yet_valid", detail
            detail.setdefault("jwt", info)
        error = www.get("error", "").lower()
        if error:
            detail["error"] = error
            detail["error_description"] = www.get("error_description", "")
        if error == "invalid_token":
            return "invalid_token", detail
        if error == "insufficient_scope":
            return "insufficient_scope", detail
        server = (entry.response_header("server") or "").lower()
        if entry.status == 403 and "html" in entry.mime and any(c in server for c in _CDN_SERVERS):
            return "cdn_block", detail
        if not meta.credentials_present:
            return "no_credentials", detail
        return ("rejected" if entry.status == 401 else "forbidden"), detail

    def finish(self, ctx: Context) -> Iterable[Finding]:
        findings = []
        for group in self._groups.values():
            if group.kind == "no_credentials" and group.status == 401:
                probes = [
                    n
                    for n, s, p in zip(group.entries, group.starts, group.paths, strict=True)
                    if self._sign_in.is_probe(group.host, 401, False, s, p)
                ]
                if probes:
                    findings.append(self._probe_finding(group, probes))
                    group.entries = [n for n in group.entries if n not in probes]
                    if not group.entries:
                        continue
            findings.append(self._finding(group))
        return findings

    def _probe_finding(self, g: _Group, probes: list[int]) -> Finding:
        return self.finding(
            severity=Severity.INFO,
            title=f"Sign-in check before signing in: {plural(len(probes), 'request')} to {g.host} ({numbers(probes)})",
            cause=(
                f"These 401s came before any credentials were sent, and later requests to {g.host}"
                " with credentials succeeded: the app checking for a session before sign-in. Usually"
                " expected."
            ),
            next_step="Ignore unless the customer reports being signed out; look at the later failures first.",
            entries=probes,
            evidence={"status": 401, "host": g.host, "kind": "sign_in_probe", "count": len(probes)},
            confidence="likely",
        )

    def _finding(self, g: _Group) -> Finding:
        n = len(g.entries)
        where = f"{plural(n, 'request')} to {g.host} ({numbers(g.entries)})"
        d = g.detail
        description = d.get("error_description") or ""
        jwt = d.get("jwt") or {}
        confidence = "certain"
        if g.kind == "expired_token":
            ago = duration_words(jwt.get("expired_seconds_before_request", 0))
            cause = (
                f"The token {jwt.get('token', '')} had expired {ago} before the request"
                f" (exp {jwt.get('exp')}), so {g.host} rejected it with {g.status}."
            )
            step = (
                "Ask the customer to sign out and in again. If it keeps happening, the app is"
                " not refreshing tokens before they expire: escalate with these request numbers."
            )
        elif g.kind == "not_yet_valid":
            ahead = duration_words(jwt.get("not_valid_for_seconds", 0))
            cause = (
                f"The token is not valid for another {ahead} by the browser's clock, so the"
                " customer's device clock is probably wrong."
            )
            step = "Ask the customer to set their device clock to update automatically, then retry."
            confidence = "likely"
        elif g.kind == "invalid_token":
            cause = (
                f"{g.host} rejected the token as invalid"
                f"{': ' + description if description else ''}."
            )
            step = (
                "Sign out and in again. If that fails, check the token is for this environment"
                " (production vs sandbox) and has not been revoked."
            )
        elif g.kind == "insufficient_scope":
            cause = (
                f"The user is signed in, but the token lacks the scope this needs"
                f"{': ' + description if description else ''}."
            )
            step = "Grant the missing scope or role, then have the user sign in again."
        elif g.kind == "cdn_block":
            cause = (
                f"A CDN or firewall ({d.get('server')}) blocked the request with an HTML 403"
                " before it reached the application."
            )
            step = "Ask the site owner to check their WAF/CDN logs for the blocked requests."
            confidence = "likely"
        elif g.kind == "no_credentials":
            cause = (
                f"The request reached {g.host} without any credentials (no Authorization"
                " header, cookie or API key)."
            )
            step = (
                "Check the user is signed in. If they are, the app is not attaching the token,"
                " or the browser is not sending the session cookie (SameSite, third-party"
                " cookie blocking, wrong cookie domain)."
            )
        elif g.kind == "forbidden":
            cause = (
                f"The user is authenticated but not allowed to do this on {g.host}: a missing"
                " permission, role or plan feature."
            )
            step = "Check the user's role and permissions for this action."
        else:
            cause = (
                f"Credentials were sent but {g.host} rejected them: wrong, revoked, or for a"
                " different environment."
            )
            step = (
                "Sign out and in again; for API keys, check the key is active and belongs to"
                " this environment."
            )
        label = {401: "401 Unauthorized", 403: "403 Forbidden"}[g.status]
        return self.finding(
            severity=Severity.HIGH,
            title=f"{label}: {where}",
            cause=cause,
            next_step=step,
            entries=list(g.entries),
            evidence={"status": g.status, "host": g.host, "kind": g.kind, "count": n, **d},
            confidence=confidence,
        )
