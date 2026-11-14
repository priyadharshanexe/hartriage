"""R005: DNS, connection and TLS failures, from the error the browser recorded."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, Severity
from hartriage.rules.util import ABORTED, numbers, plural

# (category, prefixes). Chrome writes net::ERR_*, Firefox NS_*/SEC_*/SSL_* codes.
_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("blocked_by_client", ("net::ERR_BLOCKED_BY_CLIENT",)),
    (
        "dns",
        (
            "net::ERR_NAME_NOT_RESOLVED",
            "net::ERR_NAME_RESOLUTION_FAILED",
            "net::ERR_DNS_",
            "NS_ERROR_UNKNOWN_HOST",
        ),
    ),
    (
        "tls",
        (
            "net::ERR_CERT_",
            "net::ERR_SSL_",
            "net::ERR_BAD_SSL_CLIENT_AUTH_CERT",
            "SEC_ERROR_",
            "SSL_ERROR_",
            "MOZILLA_PKIX_ERROR_",
            "NS_ERROR_NET_INADEQUATE_SECURITY",
        ),
    ),
    ("refused", ("net::ERR_CONNECTION_REFUSED", "NS_ERROR_CONNECTION_REFUSED")),
    ("timeout", ("net::ERR_CONNECTION_TIMED_OUT", "net::ERR_TIMED_OUT", "NS_ERROR_NET_TIMEOUT")),
    (
        "reset",
        (
            "net::ERR_CONNECTION_RESET",
            "net::ERR_CONNECTION_CLOSED",
            "net::ERR_CONNECTION_ABORTED",
            "NS_ERROR_NET_RESET",
            "NS_ERROR_NET_INTERRUPT",
        ),
    ),
    (
        "unreachable",
        (
            "net::ERR_ADDRESS_UNREACHABLE",
            "net::ERR_NETWORK_ACCESS_DENIED",
            "net::ERR_ADDRESS_INVALID",
        ),
    ),
    ("offline", ("net::ERR_INTERNET_DISCONNECTED", "net::ERR_NETWORK_CHANGED", "NS_ERROR_OFFLINE")),
    (
        "proxy",
        (
            "net::ERR_PROXY_",
            "net::ERR_TUNNEL_CONNECTION_FAILED",
            "NS_ERROR_PROXY_",
            "NS_ERROR_UNKNOWN_PROXY_HOST",
        ),
    ),
    (
        "policy",
        (
            "net::ERR_BLOCKED_BY_RESPONSE",
            "net::ERR_BLOCKED_BY_ORB",
            "net::ERR_BLOCKED_BY_CSP",
            "net::ERR_BLOCKED_BY_ADMINISTRATOR",
            "NS_ERROR_CONTENT_BLOCKED",
        ),
    ),
    (
        "protocol",
        (
            "net::ERR_HTTP2_",
            "net::ERR_QUIC_PROTOCOL_ERROR",
            "net::ERR_SPDY_",
            "net::ERR_INCOMPLETE_CHUNKED_ENCODING",
            "net::ERR_CONTENT_LENGTH_MISMATCH",
            "net::ERR_EMPTY_RESPONSE",
            "net::ERR_INVALID_RESPONSE",
            "net::ERR_CONTENT_DECODING_FAILED",
            "net::ERR_RESPONSE_HEADERS_",
            "NS_ERROR_NET_PARTIAL_TRANSFER",
            "NS_ERROR_CORRUPTED_CONTENT",
        ),
    ),
)

_TLS_DETAIL = (
    (
        ("ERR_CERT_DATE_INVALID", "SEC_ERROR_EXPIRED_CERTIFICATE", "EXPIRED"),
        "the certificate has expired (or the device clock is wrong)",
    ),
    (
        ("ERR_CERT_COMMON_NAME_INVALID", "SSL_ERROR_BAD_CERT_DOMAIN"),
        "the certificate is for a different hostname",
    ),
    (
        ("ERR_CERT_AUTHORITY_INVALID", "SEC_ERROR_UNKNOWN_ISSUER", "SELF_SIGNED"),
        "the certificate is not from a trusted authority (self-signed, or a proxy re-signing traffic)",
    ),
    (("ERR_CERT_REVOKED", "SEC_ERROR_REVOKED_CERTIFICATE"), "the certificate has been revoked"),
    (
        ("ERR_SSL_VERSION_OR_CIPHER_MISMATCH", "SSL_ERROR_NO_CYPHER_OVERLAP"),
        "the browser and server share no TLS version or cipher",
    ),
)

_SEVERITY = {
    "blocked_by_client": Severity.INFO,
    "policy": Severity.MEDIUM,
    "protocol": Severity.MEDIUM,
    "other": Severity.MEDIUM,
}


def categorise(error: str) -> str | None:
    if not error or any(error.startswith(a) for a in ABORTED):
        return None
    for category, prefixes in _CATEGORIES:
        if any(error.startswith(p) or p in error for p in prefixes):
            return category
    if error == "net::ERR_FAILED":
        return None  # generic; usually CORS (R003) or a cancelled request
    return "other"


def tls_detail(error: str) -> str:
    upper = error.upper()
    for needles, text in _TLS_DETAIL:
        if any(n in upper for n in needles):
            return text
    return "the certificate or TLS settings were rejected"


@dataclass
class _Group:
    category: str
    host: str
    errors: list[str] = field(default_factory=list)
    entries: list[int] = field(default_factory=list)
    server_ip: str = ""


class Network(Rule):
    id = "R005"
    slug = "network"
    title = "DNS, connection and TLS failures"
    summary = (
        "Network errors recorded by the browser: DNS, refused, timeouts, TLS, proxies, blockers."
    )

    def __init__(self) -> None:
        self._groups: dict[tuple[str, str], _Group] = {}

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        category = categorise(entry.error)
        if category is None:
            return ()
        group = self._groups.setdefault((category, entry.host), _Group(category, entry.host))
        group.entries.append(entry.number)
        if entry.error not in group.errors:
            group.errors.append(entry.error)
        group.server_ip = group.server_ip or entry.server_ip
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        out = []
        for g in self._groups.values():
            error = g.errors[0]
            host = g.host
            confidence = "certain"
            steps = {
                "dns": (
                    "Check the hostname is spelled right and resolves (nslookup "
                    + host
                    + "). On a VPN or corporate network, ask whether DNS filtering blocks it."
                ),
                "tls": (
                    "Open https://" + host + " in the browser and look at the certificate."
                    " If it is valid there, ask whether a proxy or antivirus inspects TLS."
                ),
                "refused": "Check the service is running and listening on that port.",
                "timeout": (
                    "Check the server is up and reachable from the customer's network;"
                    " firewalls that drop packets cause timeouts."
                ),
                "reset": "Ask whether a proxy, firewall or VPN sits between the customer and "
                + host
                + ".",
                "unreachable": "Check the customer's network route and firewall rules to "
                + host
                + ".",
                "offline": "The device lost its network connection; ask the customer to retry on a stable network.",
                "proxy": "Check the browser's proxy settings (or the PAC file) on the customer's device.",
                "policy": "Check the site's CSP, CORP and COEP headers for the blocked resource.",
                "protocol": (
                    "Retry on another network; if it persists, check proxies and the server or"
                    " CDN logs for responses cut off midway."
                ),
                "blocked_by_client": (
                    "Usually harmless. If the app needs this host, ask the"
                    " customer to allow it in their ad blocker or try a private window."
                ),
                "other": "Search the error code; retry on another network to rule out the local setup.",
            }
            causes = {
                "dns": f"The browser could not find {host} (DNS lookup failed: {error}).",
                "tls": f"The secure connection to {host} failed because {tls_detail(error)} ({error}).",
                "refused": f"Nothing accepted the connection to {host} ({error}): the service is down or the port is wrong.",
                "timeout": f"The connection to {host} timed out ({error}).",
                "reset": f"The connection to {host} was cut off ({error}), often by a proxy, firewall or load balancer.",
                "unreachable": f"{host} could not be reached from the customer's network ({error}).",
                "offline": f"The device was offline or changed networks ({error}).",
                "proxy": f"The browser could not connect through its proxy ({error}).",
                "policy": f"A browser security policy blocked the response from {host} ({error}).",
                "protocol": f"The response from {host} was cut off or malformed ({error}).",
                "blocked_by_client": (
                    f"The browser itself blocked {plural(len(g.entries), 'request')} to"
                    f" {host} ({error}), usually an ad blocker or privacy extension."
                ),
                "other": f"Requests to {host} failed with {error}.",
            }
            if g.category in ("protocol", "reset"):
                confidence = "likely"
            out.append(
                self.finding(
                    severity=_SEVERITY.get(g.category, Severity.HIGH),
                    title=f"{_TITLES[g.category]}: {host} ({numbers(g.entries, 5)})",
                    cause=causes[g.category],
                    next_step=steps[g.category],
                    entries=list(g.entries),
                    evidence={
                        "category": g.category,
                        "host": host,
                        "errors": g.errors,
                        "count": len(g.entries),
                        "server_ip": g.server_ip,
                    },
                    confidence=confidence,
                )
            )
        return out


_TITLES = {
    "dns": "DNS lookup failed",
    "tls": "TLS/certificate error",
    "refused": "Connection refused",
    "timeout": "Connection timed out",
    "reset": "Connection reset",
    "unreachable": "Host unreachable",
    "offline": "Device offline",
    "proxy": "Proxy failure",
    "policy": "Blocked by a browser policy",
    "protocol": "Broken response",
    "blocked_by_client": "Blocked by an extension",
    "other": "Network error",
}
