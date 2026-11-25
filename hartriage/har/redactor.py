"""Remove secrets from HAR entries before anything is stored.

Every secret is replaced with ``[REDACTED:<8 hex>]``. The hex is an HMAC of the
secret keyed with a random salt that exists only while one file is processed, so:

* inside one file the same token always gets the same marker ("the token sent in
  request 3 is the one that failed in request 7"), and
* markers cannot be compared across files, and cannot be reversed.

What counts as a secret is in `RedactionPolicy`; the whole policy is documented
in docs/redaction-policy.md. Names (header names, cookie names, query parameter
names, JSON keys) are kept; values are what get removed.

This module is pure: no I/O, no clock, no globals that change. The property
tests in tests/property drive it with thousands of generated files.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import secrets
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote_plus

MARKER_RE = re.compile(r"\[REDACTED:[0-9a-f]{8}\]")
_MARKER_FULL = re.compile(r"^\[REDACTED:[0-9a-f]{8}\]$")

# --------------------------------------------------------------------------- names

SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-xsrf-token",
        "x-amz-security-token",
    }
)
# Names that match a sensitive word but carry no secret. WWW-Authenticate says *why*
# a request was rejected, which the auth rule needs.
SAFE_HEADERS = frozenset(
    {
        "www-authenticate",
        "proxy-authenticate",
        "access-control-allow-headers",
        "access-control-request-headers",
        "access-control-expose-headers",
        "access-control-allow-credentials",
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-max-age",
    }
)

SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "access_token",
        "id_token",
        "refresh_token",
        "token",
        "code",
        "api_key",
        "apikey",
        "key",
        "password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "signature",
        "sig",
        "x-amz-signature",
        "x-amz-credential",
        "x-amz-security-token",
        "x-goog-signature",
        "x-goog-credential",
        "auth",
        "authorization",
        "session",
        "sessionid",
        "session_id",
        "sid",
        "jwt",
        "assertion",
        "samlresponse",
        "samlrequest",
        "otp",
        "ticket",
    }
)

# A name is sensitive when one of its words is in this set ("api_key", "accessToken",
# "X-Auth-Token") or it contains one of the substrings below ("xauthtoken").
SENSITIVE_WORDS = frozenset(
    {
        "token",
        "tokens",
        "secret",
        "secrets",
        "key",
        "keys",
        "apikey",
        "session",
        "sessionid",
        "sid",
        "auth",
        "authorization",
        "authentication",
        "password",
        "passwords",
        "passwd",
        "pwd",
        "pass",
        "passphrase",
        "signature",
        "sig",
        "credential",
        "credentials",
        "cookie",
        "csrf",
        "xsrf",
        "jwt",
        "bearer",
        "otp",
        "pin",
        "cvv",
        "cvc",
        "privatekey",
        "assertion",
    }
)
SENSITIVE_SUBSTRINGS = (
    "token",
    "secret",
    "passw",
    "signature",
    "credential",
    "session",
    "apikey",
    "privatekey",
    "accesskey",
    "authoriz",
)

_WORD_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")

_AUTH_SCHEMES = frozenset(
    {
        "bearer",
        "basic",
        "digest",
        "token",
        "negotiate",
        "ntlm",
        "hoba",
        "mutual",
        "aws4-hmac-sha256",
        "dpop",
        "sso-key",
        "apikey",
        "key",
    }
)

_CORRELATION_SAFE = frozenset(
    {
        "x-request-id",
        "x-correlation-id",
        "request-id",
        "x-amzn-requestid",
        "x-amz-request-id",
        "x-amz-cf-id",
        "cf-ray",
        "traceparent",
        "x-b3-traceid",
        "x-cloud-trace-context",
        "x-ms-request-id",
        "x-github-request-id",
        "x-trace-id",
    }
)


def words_of(name: str) -> list[str]:
    return [w.lower() for w in _WORD_SPLIT.split(name) if w]


def is_sensitive_name(name: str, *, query: bool = False) -> bool:
    """True when a key, field or parameter name says its value is a secret.

    `query` adds the exact parameter names that are secrets only in URLs and forms:
    ``code`` is an OAuth authorization code in a callback URL, but an error code in
    a JSON body.
    """
    lowered = name.lower()
    if query and lowered in SENSITIVE_QUERY_PARAMS:
        return True
    if any(w in SENSITIVE_WORDS for w in words_of(name)):
        return True
    compact = re.sub(r"[^a-z0-9]", "", lowered)
    return any(s in compact for s in SENSITIVE_SUBSTRINGS)


def is_sensitive_header(name: str) -> bool:
    lowered = name.lower().lstrip(":")
    if lowered in SAFE_HEADERS or lowered in _CORRELATION_SAFE:
        return False
    if lowered in SENSITIVE_HEADERS:
        return True
    return is_sensitive_name(lowered)


def category_for_name(name: str) -> str:
    """Which line of the redaction report a secret found under `name` counts towards."""
    words = set(words_of(name))
    lowered = name.lower()
    if "cookie" in lowered:
        return "cookies"
    if words & {"key", "keys", "apikey"} or "apikey" in lowered.replace("_", "").replace("-", ""):
        return "api_keys"
    if words & {"password", "passwords", "passwd", "pwd", "pass", "passphrase", "pin"}:
        return "passwords"
    if words & {"signature", "sig"} or "signature" in lowered:
        return "signatures"
    return "tokens"


# ------------------------------------------------------------------ text patterns

_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
# JWS (3 parts) and JWE (5 parts). The header always starts with eyJ ({").
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{2,}(?:\.[A-Za-z0-9_-]*){2,4}")
_SCHEME_CREDENTIAL = re.compile(r"(?i)\b(bearer|basic)(\s+)([A-Za-z0-9\-._~+/]+=*)")
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@?#]*):([^/\s@?#]+)@")
_AWS_KEY_ID = re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA|ACCA)[A-Z0-9]{16}\b")
_KNOWN_TOKENS = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{22,255}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|AIza[0-9A-Za-z_\-]{35}|sk-[A-Za-z0-9_\-]{32,})"
)
# name=value pairs in URLs, cookies-like strings and log lines.
_PAIR = re.compile(r"(^|[?&#;,\s])([A-Za-z0-9_.\-\[\]%]{1,128})=([^&#\s\"'<>;,]*)")
# "name": "value" pairs in JSON that failed to parse (for example a truncated body).
_JSONISH_PAIR = re.compile(r'"([^"\\]{1,128})"(\s*:\s*)"((?:[^"\\]|\\.)*)"')


# ------------------------------------------------------------------------ report


@dataclass
class RedactionReport:
    """What was removed from one file. Counts only, never values."""

    distinct: dict[str, set[str]] = field(default_factory=dict)
    occurrences: Counter[str] = field(default_factory=Counter)
    entries_touched: int = 0
    response_bodies_removed: int = 0
    request_bodies_removed: int = 0
    websocket_messages_removed: int = 0
    error_bodies_kept: int = 0

    def add(self, category: str, marker: str) -> None:
        self.distinct.setdefault(category, set()).add(marker)
        self.occurrences[category] += 1

    def counts(self) -> dict[str, int]:
        return {c: len(m) for c, m in sorted(self.distinct.items())}

    @property
    def total_secrets(self) -> int:
        return len({m for markers in self.distinct.values() for m in markers})

    def to_dict(self) -> dict[str, Any]:
        return {
            "secrets": self.counts(),
            "occurrences": dict(sorted(self.occurrences.items())),
            "total_secrets": self.total_secrets,
            "entries_touched": self.entries_touched,
            "response_bodies_removed": self.response_bodies_removed,
            "request_bodies_removed": self.request_bodies_removed,
            "websocket_messages_removed": self.websocket_messages_removed,
            "error_bodies_kept": self.error_bodies_kept,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        return report_sentence(
            self.counts(),
            sum(self.occurrences.values()),
            self.entries_touched,
            self.response_bodies_removed,
        )


_LABELS = {
    "tokens": ("token", "tokens"),
    "cookies": ("cookie", "cookies"),
    "api_keys": ("API key", "API keys"),
    "passwords": ("password", "passwords"),
    "signatures": ("signature", "signatures"),
    "aws_keys": ("AWS access key", "AWS access keys"),
    "private_keys": ("private key", "private keys"),
}


def report_sentence(
    counts: dict[str, int], occurrences: int, entries: int, bodies_removed: int
) -> str:
    parts = []
    for category in (
        "tokens",
        "cookies",
        "api_keys",
        "passwords",
        "signatures",
        "aws_keys",
        "private_keys",
    ):
        n = counts.get(category, 0)
        if n:
            singular, plural = _LABELS[category]
            parts.append(f"{n} {singular if n == 1 else plural}")
    bodies = (
        f" Dropped {bodies_removed} response bod{'y' if bodies_removed == 1 else 'ies'}."
        if bodies_removed
        else ""
    )
    if not parts:
        return "No secrets found." + bodies
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    places = f"{occurrences} place{'s' if occurrences != 1 else ''}"
    reqs = f"{entries} request{'s' if entries != 1 else ''}"
    return f"Removed {listed} ({places} in {reqs}).{bodies}"


# ------------------------------------------------------------------------ policy


@dataclass(frozen=True)
class RedactionPolicy:
    keep_error_bodies: bool = True
    error_body_max_bytes: int = 16 * 1024
    keep_graphql_errors: bool = True
    request_body_max_bytes: int = 64 * 1024


DEFAULT_POLICY = RedactionPolicy()


# ---------------------------------------------------------------------- redactor


class Redactor:
    """Redacts one HAR file. Create one per file: the salt must not be reused."""

    def __init__(self, policy: RedactionPolicy = DEFAULT_POLICY, salt: bytes | None = None):
        self.policy = policy
        self._salt = salt if salt is not None else secrets.token_bytes(32)
        self.report = RedactionReport()
        self._touched = False

    # -- markers ---------------------------------------------------------------

    def marker(self, value: str) -> str:
        if _MARKER_FULL.match(value):
            return value
        digest = hmac.new(self._salt, value.encode("utf-8", "surrogatepass"), hashlib.sha256)
        return f"[REDACTED:{digest.hexdigest()[:8]}]"

    def _secret(self, value: str, category: str) -> str:
        if _MARKER_FULL.match(value):
            return value
        mark = self.marker(value)
        self.report.add(category, mark)
        self._touched = True
        return mark

    # -- free text -------------------------------------------------------------

    def text(self, s: str) -> str:
        """Redact secrets in free text: JWTs, bearer tokens, keys, name=value pairs."""
        if not s or len(s) < 4:
            return s
        s = _PRIVATE_KEY.sub(lambda m: self._secret(m.group(0), "private_keys"), s)
        if "eyJ" in s:
            s = _JWT.sub(lambda m: self._secret(m.group(0), "tokens"), s)
        s = _SCHEME_CREDENTIAL.sub(self._scheme_sub, s)
        if "@" in s:
            s = _URL_USERINFO.sub(
                # Brackets are not allowed in a URL's user-info, so the marker is %-encoded there.
                lambda m: (
                    f"{m.group(1)}{m.group(2)}:"
                    f"{quote(self._secret(unquote_plus(m.group(3)), 'passwords'), safe=':')}@"
                ),
                s,
            )
        s = _AWS_KEY_ID.sub(lambda m: self._secret(m.group(0), "aws_keys"), s)
        s = _KNOWN_TOKENS.sub(lambda m: self._secret(m.group(0), "api_keys"), s)
        if "=" in s:
            s = _PAIR.sub(self._pair_sub, s)
        if '"' in s and ":" in s:
            s = _JSONISH_PAIR.sub(self._jsonish_sub, s)
        return s

    def _scheme_sub(self, m: re.Match[str]) -> str:
        scheme, space, credential = m.group(1), m.group(2), m.group(3)
        rest = m.string[m.end() :]
        # `Bearer realm="api"` is a challenge parameter, not a credential.
        if rest.startswith("=") or not _looks_like_token(credential):
            return m.group(0)
        return f"{scheme}{space}{self._secret(credential, 'tokens')}"

    def _pair_sub(self, m: re.Match[str]) -> str:
        lead, name, value = m.group(1), m.group(2), m.group(3)
        if (
            not value
            or not is_sensitive_name(unquote_plus(name), query=True)
            or MARKER_RE.fullmatch(value)
        ):
            return m.group(0)
        if MARKER_RE.search(value) and not MARKER_RE.sub("", value):
            return m.group(0)
        return f"{lead}{name}={self._secret(unquote_plus(value), category_for_name(name))}"

    def _jsonish_sub(self, m: re.Match[str]) -> str:
        name, colon, value = m.group(1), m.group(2), m.group(3)
        if not value or not is_sensitive_name(name) or _MARKER_FULL.match(value):
            return m.group(0)
        return f'"{name}"{colon}"{self._secret(_json_unescape(value), category_for_name(name))}"'

    # -- structured values -------------------------------------------------------

    def url(self, url: str) -> str:
        if not isinstance(url, str):
            return url
        url = self.text(url)
        # A token in the path (/invite/<token>, /reset/<token>) has no name to go by.
        # Only whole segments that look random are taken; see random_segment().
        scheme, sep, rest = url.partition("://")
        if not sep:
            return url
        host, slash, tail = rest.partition("/")
        if not slash:
            return url
        path, q, query = tail.partition("?")
        segments = path.split("/")
        if not any(random_segment(seg) for seg in segments):
            return url
        path = "/".join(
            self._secret(seg, "tokens") if random_segment(seg) else seg for seg in segments
        )
        return f"{scheme}://{host}/{path}{q}{query}"

    def json_value(self, value: Any, sensitive: bool = False, name: str = "") -> Any:
        """Walk decoded JSON. Values under a sensitive key are replaced; the rest is scanned."""
        if isinstance(value, dict):
            return {
                k: self.json_value(v, sensitive or is_sensitive_name(str(k)), str(k))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.json_value(v, sensitive, name) for v in value]
        if isinstance(value, bool) or value is None:
            return value
        if sensitive:
            raw = value if isinstance(value, str) else json.dumps(value)
            if raw == "":
                return value
            return self._secret(raw, category_for_name(name) if name else "tokens")
        if isinstance(value, str):
            return self.text(value)
        return value

    def header_value(self, name: str, value: str) -> str:
        lowered = name.lower().lstrip(":")
        if lowered == "cookie":
            return self.cookie_header(value)
        if lowered == "set-cookie":
            return "\n".join(self.set_cookie(line) for line in value.split("\n"))
        if is_sensitive_header(lowered):
            return self.credential(value, category_for_name(lowered))
        return self.text(value)

    def credential(self, value: str, category: str) -> str:
        """Redact a whole credential value, keeping a known scheme word ("Bearer")."""
        if not value or _MARKER_FULL.match(value):
            return value
        parts = value.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() in _AUTH_SCHEMES:
            return f"{parts[0]} {self._secret(parts[1], category)}"
        return self._secret(value, category)

    def cookie_header(self, value: str) -> str:
        out = []
        for part in value.split(";"):
            if not part.strip():
                continue
            name, eq, val = part.strip().partition("=")
            if eq:
                out.append(f"{name}={self._secret(val, 'cookies') if val else ''}")
            else:
                out.append(self._secret(name, "cookies"))
        return "; ".join(out)

    def set_cookie(self, line: str) -> str:
        if not line.strip():
            return line
        first, sep, attributes = line.partition(";")
        name, eq, val = first.strip().partition("=")
        if not eq:
            return self._secret(line, "cookies")
        redacted = f"{name}={self._secret(val, 'cookies') if val else ''}"
        if sep:
            redacted += ";" + self.text(attributes)
        return redacted

    # -- bodies ----------------------------------------------------------------

    def post_data(self, post: dict[str, Any]) -> None:
        mime = str(post.get("mimeType", "")).lower()
        params = post.get("params")
        if isinstance(params, list):
            for p in params:
                if not isinstance(p, dict):
                    continue
                pname = str(p.get("name", ""))
                if "fileName" in p and "value" in p:
                    p["value"] = ""  # uploaded file contents are never kept
                elif isinstance(p.get("value"), str):
                    p["value"] = (
                        self._secret(p["value"], category_for_name(pname))
                        if is_sensitive_name(pname, query=True) and p["value"]
                        else self.text(p["value"])
                    )
        text = post.get("text")
        if not isinstance(text, str) or not text:
            return
        if len(text.encode("utf-8", "surrogatepass")) > self.policy.request_body_max_bytes:
            post["text"] = ""
            post["comment"] = "Request body removed by HAR Triage: larger than the size limit"
            post["_size"] = len(text.encode("utf-8", "surrogatepass"))
            self.report.request_bodies_removed += 1
            self._touched = True
            return
        post["text"] = self.body_text(text, mime)

    def body_text(self, text: str, mime: str) -> str:
        stripped = text.lstrip()
        if "json" in mime or stripped[:1] in ("{", "["):
            try:
                decoded = json.loads(text)
            except ValueError:
                return self.text(text)
            return json.dumps(self.json_value(decoded), ensure_ascii=False)
        if "x-www-form-urlencoded" in mime:
            return self.form_urlencoded(text)
        if "multipart/form-data" in mime:
            return self.multipart(text)
        return self.text(text)

    def form_urlencoded(self, text: str) -> str:
        out = []
        for pair in text.split("&"):
            name, eq, value = pair.partition("=")
            dname = unquote_plus(name)
            if eq and value and is_sensitive_name(dname, query=True):
                out.append(f"{name}={self._secret(unquote_plus(value), category_for_name(dname))}")
            elif eq:
                decoded = unquote_plus(value)
                scanned = self.text(decoded)
                out.append(pair if scanned == decoded else f"{name}={quote(scanned, safe='[]:')}")
            else:
                out.append(self.text(pair))
        return "&".join(out)

    _PART = re.compile(
        r'(Content-Disposition:\s*form-data;\s*name="([^"]*)"(?:;\s*filename="[^"]*")?[^\r\n]*\r?\n'
        r"(?:[^\r\n]+\r?\n)*\r?\n)(.*?)(?=\r?\n--)",
        re.DOTALL | re.IGNORECASE,
    )

    def multipart(self, text: str) -> str:
        def part(m: re.Match[str]) -> str:
            head, name, value = m.group(1), m.group(2), m.group(3)
            if "filename=" in head.lower():
                return head + "[file content removed]"
            if value and is_sensitive_name(name, query=True):
                return head + self._secret(value, category_for_name(name))
            return head + self.text(value)

        return self.text(self._PART.sub(part, text))

    def response_content(self, content: dict[str, Any], status: int) -> None:
        text = content.get("text")
        if not isinstance(text, str) or text == "":
            content.pop("text", None)
            return
        kept = self._keep_body(content, text, status)
        content.pop("encoding", None)
        if kept is None:
            content.pop("text", None)
            content["comment"] = "Response body removed by HAR Triage before storage"
            self.report.response_bodies_removed += 1
            self._touched = True
        else:
            content["text"] = kept
            self.report.error_bodies_kept += 1

    def _keep_body(self, content: dict[str, Any], text: str, status: int) -> str | None:
        policy = self.policy
        if not (policy.keep_error_bodies or policy.keep_graphql_errors):
            return None
        if content.get("encoding") == "base64":
            try:
                text = base64.b64decode(text, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return None
        if len(text.encode("utf-8", "surrogatepass")) > policy.error_body_max_bytes:
            return None
        if text.lstrip()[:1] not in ("{", "["):
            return None
        try:
            decoded = json.loads(text)
        except ValueError:
            return None
        if status >= 400 and policy.keep_error_bodies:
            return json.dumps(self.json_value(decoded), ensure_ascii=False)
        # GraphQL answers errors with 200: keep only the errors, never the data.
        if (
            policy.keep_graphql_errors
            and isinstance(decoded, dict)
            and isinstance(decoded.get("errors"), list)
            and decoded["errors"]
        ):
            content["_partial"] = "errors only"
            return json.dumps({"errors": self.json_value(decoded["errors"])}, ensure_ascii=False)
        return None

    # -- whole entries -----------------------------------------------------------

    def redact_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Redact one HAR entry in place and return it."""
        self._touched = False
        entry.pop("_hartriage", None)  # never trust metadata that arrives in the input
        request = entry.get("request")
        if isinstance(request, dict):
            self._redact_message(request)
            if isinstance(request.get("url"), str):
                request["url"] = self.url(request["url"])
            query = request.get("queryString")
            if isinstance(query, list):
                for q in query:
                    if isinstance(q, dict) and isinstance(q.get("value"), str):
                        qname = str(q.get("name", ""))
                        q["value"] = (
                            self._secret(q["value"], category_for_name(qname))
                            if q["value"] and is_sensitive_name(qname, query=True)
                            else self.text(q["value"])
                        )
            post = request.get("postData")
            if isinstance(post, dict):
                self.post_data(post)
        response = entry.get("response")
        if isinstance(response, dict):
            self._redact_message(response)
            if isinstance(response.get("redirectURL"), str):
                response["redirectURL"] = self.url(response["redirectURL"])
            content = response.get("content")
            if isinstance(content, dict):
                status = response.get("status")
                self.response_content(content, status if isinstance(status, int) else 0)
        messages = entry.get("_webSocketMessages")
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict) and message.get("data"):
                    size = len(str(message["data"]).encode("utf-8", "surrogatepass"))
                    message["data"] = f"[message removed: {size} bytes]"
                    self.report.websocket_messages_removed += 1
        # Last pass: everything else (initiators, custom fields, comments) is scanned too.
        for key in list(entry):
            if key not in ("request", "response"):
                entry[key] = self._sweep(entry[key], key)
        if isinstance(request, dict):
            self._sweep_known(request, ("headers", "cookies", "queryString", "postData", "url"))
        if isinstance(response, dict):
            self._sweep_known(response, ("headers", "cookies", "content", "redirectURL"))
        if self._touched:
            self.report.entries_touched += 1
        return entry

    def _redact_message(self, message: dict[str, Any]) -> None:
        headers = message.get("headers")
        if isinstance(headers, list):
            for h in headers:
                if isinstance(h, dict) and isinstance(h.get("value"), str):
                    h["value"] = self.header_value(str(h.get("name", "")), h["value"])
        cookies = message.get("cookies")
        if isinstance(cookies, list):
            for c in cookies:
                if isinstance(c, dict):
                    if isinstance(c.get("value"), str) and c["value"]:
                        c["value"] = self._secret(c["value"], "cookies")
                    for k, v in list(c.items()):
                        if k not in ("name", "value") and isinstance(v, str):
                            c[k] = self.text(v)

    def _sweep_known(self, message: dict[str, Any], handled: tuple[str, ...]) -> None:
        for key in list(message):
            if key not in handled:
                message[key] = self._sweep(message[key], key)
        if isinstance(message.get("content"), dict):
            content = message["content"]
            for key in list(content):
                if key != "text":
                    content[key] = self._sweep(content[key], key)

    def _sweep(self, value: Any, name: str, custom: bool = False) -> Any:
        # Inside a custom ("_"-prefixed) field, names are trusted to mean what they say,
        # as in a JSON body. Standard HAR fields are handled field by field above.
        custom = custom or name.startswith("_")
        if isinstance(value, str):
            if custom and value and is_sensitive_name(name.lstrip("_")):
                return self._secret(value, category_for_name(name))
            return self.text(value)
        if isinstance(value, dict):
            return {k: self._sweep(v, str(k), custom) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sweep(v, name, custom) for v in value]
        return value

    def redact_log_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Redact `log.pages`, `log.creator` and the other non-entry fields."""
        return {k: self._sweep(v, k) for k, v in fields.items()}


_SEGMENT = re.compile(r"^[A-Za-z0-9_~-]{32,512}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_HEX = re.compile(r"^[0-9a-fA-F]+$")
_PREFIXED_ID = re.compile(r"^[a-z]{2,8}_[A-Za-z0-9]")  # pi_3Nx…, cus_…: ids, kept


def random_segment(segment: str) -> bool:
    """A URL path segment that looks like a random token rather than a name or an id.

    Conservative on purpose (redacting ids and hashes makes a HAR useless): at least
    32 URL-safe characters with no dot (so no file names), lower case, upper case and
    digits all present, at least 4.3 bits of entropy per character, and not a UUID,
    a hex hash or a prefixed id. Measured on the golden HARs: no false positives; on
    tokens from secrets.token_urlsafe(24..64): see tests/unit/test_entropy_detector.py.
    """
    if not _SEGMENT.match(segment) or _UUID.match(segment) or _HEX.match(segment):
        return False
    if _PREFIXED_ID.match(segment):
        return False
    if not (
        any(c.islower() for c in segment)
        and any(c.isupper() for c in segment)
        and any(c.isdigit() for c in segment)
    ):
        return False
    counts: dict[str, int] = {}
    for c in segment:
        counts[c] = counts.get(c, 0) + 1
    n = len(segment)
    entropy = -sum(k / n * math.log2(k / n) for k in counts.values())
    return entropy >= 4.3


def _looks_like_token(value: str) -> bool:
    """Tell "Bearer 9f8a7cQ2..." from prose such as "Bearer authentication required"."""
    if len(value) < 8:
        return False
    if len(value) >= 20 or any(c.isdigit() for c in value) or any(c in "-._~+/=" for c in value):
        return True
    return any(c.isupper() for c in value[1:]) and any(c.islower() for c in value)


def _json_unescape(value: str) -> str:
    try:
        result = json.loads(f'"{value}"')
    except ValueError:
        return value
    return result if isinstance(result, str) else value


MarkerFn = Callable[[str], str]
