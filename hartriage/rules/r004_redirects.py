"""R004: redirect loops and long redirect chains."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlunsplit

from hartriage.har.model import Entry
from hartriage.har.model import split as urlsplit
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import numbers

LOOP_ERRORS = ("net::ERR_TOO_MANY_REDIRECTS", "NS_ERROR_REDIRECT_LOOP")
_AUTH_WORDS = ("login", "signin", "sign-in", "auth", "sso", "oauth", "saml", "callback", "session")


def _norm(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


@dataclass
class _Chain:
    hops: list[tuple[int, str, int]] = field(default_factory=list)  # (number, url, status)
    set_cookie_seen: bool = False
    cookie_sent_after: bool = False


class Redirects(Rule):
    id = "R004"
    slug = "redirects"
    title = "Redirect loops and long chains"
    summary = "Redirect loops (ERR_TOO_MANY_REDIRECTS or a URL seen twice) and chains of 5+ hops."

    def __init__(self) -> None:
        self._pending: dict[str, _Chain] = {}
        self._chains: list[_Chain] = []
        self._loop_errors: list[Entry] = []

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        if any(entry.error.startswith(e) for e in LOOP_ERRORS):
            self._loop_errors.append(entry)
        url = _norm(entry.url)
        chain = self._pending.pop(url, None)
        is_redirect = 300 <= entry.status < 400 and entry.status != 304
        if chain is None and not is_redirect:
            return ()
        if chain is None:
            chain = _Chain()
            self._chains.append(chain)
        elif entry.request_header("cookie") and chain.set_cookie_seen:
            chain.cookie_sent_after = True
        chain.hops.append((entry.number, entry.short_url, entry.status))
        if entry.response_header("set-cookie"):
            chain.set_cookie_seen = True
        if is_redirect:
            target = entry.redirect_url or entry.response_header("location") or ""
            if target and len(chain.hops) < 60:
                self._pending[_norm(urljoin(entry.url, target))] = chain
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        out = []
        for chain in self._chains:
            urls = [u for _, u, _ in chain.hops]
            redirects = sum(1 for _, _, s in chain.hops if 300 <= s < 400)
            repeated = len(set(urls)) < len(urls)
            if not repeated and redirects < ctx.config.long_redirect_chain:
                continue
            nums = [n for n, _, _ in chain.hops]
            hosts = list(dict.fromkeys(urlsplit(u).netloc for u in urls))
            auth_like = any(w in u.lower() for u in urls for w in _AUTH_WORDS)
            if repeated:
                loop = " → ".join(dict.fromkeys(urls))
                if auth_like:
                    cause = (
                        "The browser is bouncing between the app and its sign-in page: the"
                        " session cookie set during sign-in is not being stored or sent back"
                        + (
                            " (a Set-Cookie was returned, but no later request sent a cookie)"
                            if chain.set_cookie_seen and not chain.cookie_sent_after
                            else ""
                        )
                        + "."
                    )
                    step = (
                        "Check the session cookie's SameSite/Secure/Domain attributes and"
                        " whether the browser blocks third-party cookies; try a private window"
                        " with extensions off."
                    )
                else:
                    cause = f"The redirects go round in a circle: {loop}."
                    step = (
                        "Check the server's redirect rules (http↔https, www↔apex, trailing"
                        " slash) for two rules that undo each other."
                    )
                out.append(
                    self.finding(
                        severity=Severity.HIGH,
                        title=f"Redirect loop across {len(hosts)} host(s) ({numbers(nums, 5)})",
                        cause=cause,
                        next_step=step,
                        entries=nums,
                        evidence={
                            "chain": [
                                {"entry": n, "url": u, "status": s} for n, u, s in chain.hops[:20]
                            ],
                            "hops": redirects,
                            "hosts": hosts,
                            "auth_flow": auth_like,
                            "set_cookie_seen": chain.set_cookie_seen,
                        },
                    )
                )
            else:
                out.append(
                    self.finding(
                        severity=Severity.MEDIUM,
                        title=f"Long redirect chain: {redirects} redirects before {urls[-1]}",
                        cause=f"The browser followed {redirects} redirects in a row, which adds a round trip each.",
                        next_step="Link straight to the final URL, or collapse the redirect rules.",
                        entries=nums,
                        evidence={
                            "chain": [
                                {"entry": n, "url": u, "status": s} for n, u, s in chain.hops[:20]
                            ],
                            "hops": redirects,
                            "hosts": hosts,
                        },
                    )
                )
        for entry in self._loop_errors:
            if any(entry.number in f.entries for f in out):
                continue
            out.append(
                self.finding(
                    severity=Severity.HIGH,
                    title=f"Redirect loop: #{entry.number} {entry.short_url} ({entry.error})",
                    cause=(
                        "The browser gave up after too many redirects; the HAR file may not record"
                        " every hop, but the loop starts at this URL."
                    ),
                    next_step=(
                        "Check the server's redirect rules for this URL; for sign-in flows, check"
                        " the session cookie is being stored."
                    ),
                    entries=[entry.number],
                    evidence={"error": entry.error, "url": entry.short_url},
                )
            )
        return out
