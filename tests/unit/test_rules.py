"""Each rule finds what it should and nothing else, on small hand-built files."""

from __future__ import annotations

import json
from typing import Any

from hartriage.pipeline import process
from hartriage.rules import Finding
from tests.support.har import as_stream, entry, har, headers, make_jwt

T0 = "2026-11-14T10:00:00.000Z"


def at(seconds: float) -> str:
    whole = int(seconds)
    ms = round((seconds - whole) * 1000)
    return f"2026-11-14T10:{whole // 60:02d}:{whole % 60:02d}.{ms:03d}Z"


def run(*entries: dict[str, Any], rules: list[str] | None = None) -> list[Finding]:
    return process(as_stream(har(*entries)), rules=rules).findings


def by_rule(findings: list[Finding], rule: str) -> list[Finding]:
    return [f for f in findings if f.rule_id == rule]


# ------------------------------------------------------------------ R001


def test_r001_first_failure_by_time_with_followers() -> None:
    findings = run(
        entry("https://api.example.com/a", status=200, started=at(0)),
        entry("https://api.example.com/b", status=500, started=at(3)),
        entry("https://api.example.com/c", status=401, started=at(2)),  # earlier, listed later
        entry("https://cdn.example.com/favicon.ico", status=404, started=at(1)),
        entry(
            "https://ads.example.com/x", status=0, error="net::ERR_BLOCKED_BY_CLIENT", started=at(1)
        ),
        rules=["R001"],
    )
    [f] = findings
    assert f.entry == 3 and f.evidence["followers"] == [2]
    assert "authentication" in f.cause


def test_r001_nothing_failed() -> None:
    assert run(entry(status=200), entry(status=304), rules=["R001"]) == []


# ------------------------------------------------------------------ R002


def test_r002_expired_token() -> None:
    token = make_jwt(exp=1_763_114_000 - 600)  # 10 minutes before the request
    [f] = run(
        entry(
            status=401,
            started="2025-11-14T09:53:20.000Z",
            request_headers=headers(Authorization=f"Bearer {token}"),
        ),
        rules=["R002"],
    )
    assert f.evidence["kind"] == "expired_token"
    assert "expired 10 minutes before" in f.cause


def test_r002_no_credentials_and_grouping() -> None:
    [f] = run(entry(status=401), entry(status=401), rules=["R002"])
    assert f.evidence["kind"] == "no_credentials" and f.entries == [1, 2]


def test_r002_www_authenticate_insufficient_scope() -> None:
    www = 'Bearer error="insufficient_scope", error_description="needs orders:write"'
    [f] = run(
        entry(
            status=403,
            request_headers=headers(Authorization="Bearer abcdefgh12345678"),
            response_headers=headers(WWW_Authenticate=www),
        ),
        rules=["R002"],
    )
    assert f.evidence["kind"] == "insufficient_scope" and "orders:write" in f.cause


def test_r002_clock_skew() -> None:
    token = make_jwt(nbf=1_763_114_000 + 3600, exp=1_763_114_000 + 7200)
    [f] = run(
        entry(
            status=401,
            started="2025-11-14T09:53:20.000Z",
            request_headers=headers(Authorization=f"Bearer {token}"),
        ),
        rules=["R002"],
    )
    assert f.evidence["kind"] == "not_yet_valid" and f.confidence == "likely"


# ------------------------------------------------------------------ R003


def test_r003_failed_preflight() -> None:
    [f] = run(
        entry(
            "https://api.other.com/data",
            method="OPTIONS",
            status=405,
            request_headers=headers(
                Origin="https://app.example.com", Access_Control_Request_Method="PUT"
            ),
        ),
        rules=["R003"],
    )
    assert f.confidence == "likely" and "405" in f.cause


def test_r003_missing_allow_origin_but_same_origin_is_fine() -> None:
    findings = run(
        entry("https://api.other.com/a", request_headers=headers(Origin="https://app.example.com")),
        entry(
            "https://app.example.com/b", request_headers=headers(Origin="https://app.example.com")
        ),
        entry(
            "https://api.other.com/ok",
            request_headers=headers(Origin="https://app.example.com"),
            response_headers=headers(Access_Control_Allow_Origin="https://app.example.com"),
        ),
        rules=["R003"],
    )
    [f] = findings
    assert f.entries == [1] and f.evidence["kind"] == "missing"


def test_r003_wildcard_with_cookies() -> None:
    [f] = run(
        entry(
            "https://api.other.com/a",
            request_headers=headers(Origin="https://app.example.com", Cookie="a=1"),
            response_headers=headers(Access_Control_Allow_Origin="*"),
        ),
        rules=["R003"],
    )
    assert f.evidence["kind"] == "credentials"


# ------------------------------------------------------------------ R004


def test_r004_login_loop() -> None:
    findings = run(
        entry(
            "https://app.example.com/home",
            status=302,
            redirect="https://sso.example.com/login",
            started=at(0),
        ),
        entry(
            "https://sso.example.com/login",
            status=302,
            redirect="https://app.example.com/home",
            response_headers=headers(Set_Cookie="sid=1; Path=/; SameSite=Strict"),
            started=at(1),
        ),
        entry(
            "https://app.example.com/home",
            status=302,
            redirect="https://sso.example.com/login",
            started=at(2),
        ),
        entry("https://sso.example.com/login", status=200, started=at(3)),
        rules=["R004"],
    )
    [f] = findings
    assert f.evidence["auth_flow"] and "cookie" in f.cause


def test_r004_long_chain_and_too_many_redirects() -> None:
    chain = [
        entry(f"https://a.com/{i}", status=301, redirect=f"https://a.com/{i + 1}", started=at(i))
        for i in range(6)
    ]
    findings = run(
        *chain,
        entry("https://a.com/6", started=at(7)),
        entry("https://b.com/x", status=0, error="net::ERR_TOO_MANY_REDIRECTS", started=at(8)),
        rules=["R004"],
    )
    kinds = sorted(f.severity.value for f in findings)
    assert kinds == ["high", "medium"]


# ------------------------------------------------------------------ R005


def test_r005_categories() -> None:
    findings = run(
        entry("https://nope.invalid/x", status=0, error="net::ERR_NAME_NOT_RESOLVED"),
        entry("https://expired.example.com/", status=0, error="net::ERR_CERT_DATE_INVALID"),
        entry("https://ff.example.com/", status=0, _error="SEC_ERROR_EXPIRED_CERTIFICATE"),
        entry("https://ads.example.com/", status=0, error="net::ERR_BLOCKED_BY_CLIENT"),
        entry("https://a.example.com/", status=0, error="net::ERR_ABORTED"),
        rules=["R005"],
    )
    cats = {f.evidence["category"]: f for f in findings}
    assert set(cats) == {"dns", "tls", "blocked_by_client"}
    assert "expired" in cats["tls"].cause
    assert cats["blocked_by_client"].severity.value == "info"


def test_r005_playwright_failure_text() -> None:
    e = entry("https://x.invalid/", status=-1)
    e["response"]["_failureText"] = "net::ERR_CONNECTION_REFUSED"
    [f] = run(e, rules=["R005"])
    assert f.evidence["category"] == "refused"


# ------------------------------------------------------------------ R006


def test_r006_dominant_phase() -> None:
    findings = run(
        entry(
            "https://a.com/slow",
            time=8000,
            timings={
                "blocked": 5,
                "dns": 1,
                "connect": 10,
                "ssl": 5,
                "send": 1,
                "wait": 7900,
                "receive": 83,
            },
        ),
        entry(
            "https://a.com/dns",
            time=4000,
            timings={
                "blocked": 1,
                "dns": 3900,
                "connect": 50,
                "ssl": -1,
                "send": 1,
                "wait": 40,
                "receive": 9,
            },
        ),
        entry(
            "https://a.com/stream", time=60000, content={"size": 0, "mimeType": "text/event-stream"}
        ),
        entry("https://a.com/fast", time=200),
        rules=["R006"],
    )
    phases = {f.evidence["phase"]: f for f in findings}
    assert set(phases) == {"wait", "dns"}
    assert phases["wait"].entries == [1]


# ------------------------------------------------------------------ R007


def test_r007_early_retry_detected() -> None:
    findings = run(
        entry(
            "https://api.a.com/search",
            status=429,
            started=at(0),
            time=50,
            response_headers=headers(Retry_After="30", X_RateLimit_Limit="100"),
        ),
        entry(
            "https://api.a.com/search",
            status=429,
            started=at(0.5),
            time=50,
            response_headers=headers(Retry_After="30"),
        ),
        rules=["R007"],
    )
    [f] = findings
    assert f.evidence["early_retries"] == [2] and f.evidence["retry_after_seconds"] == 30
    assert "100 per window" in f.cause


# ------------------------------------------------------------------ R008


def test_r008_413_and_431() -> None:
    findings = run(
        entry(method="POST", status=413, post={"mimeType": "application/json", "text": "x" * 2048}),
        entry(status=431, request_headers=headers(Cookie="c=" + "y" * 9000)),
        rules=["R008"],
    )
    statuses = sorted(f.evidence["status"] for f in findings)
    assert statuses == [413, 431]
    assert any("Cookie header alone" in f.cause for f in findings)


# ------------------------------------------------------------------ R009


def test_r009_groups_error_codes() -> None:
    body = {
        "size": 10,
        "mimeType": "application/json",
        "text": json.dumps(
            {"error": {"code": "card_declined", "message": "Your card was declined"}}
        ),
    }
    findings = run(
        entry(status=402, content=dict(body)),
        entry(status=402, content=dict(body)),
        entry(
            status=422,
            content={
                "size": 1,
                "mimeType": "application/json",
                "text": json.dumps(
                    {
                        "detail": [
                            {"loc": ["body", "email"], "msg": "field required", "type": "missing"}
                        ]
                    }
                ),
            },
        ),
        rules=["R009"],
    )
    top = findings[0]
    assert top.evidence["code"] == "card_declined" and top.entries == [1, 2]
    assert any(f.evidence["message"] == "email: field required" for f in findings)


# ------------------------------------------------------------------ R010


def test_r010_mixed_content() -> None:
    findings = run(
        entry(
            "https://shop.example.com/",
            resource_type="document",
            content={"size": 10, "mimeType": "text/html"},
        ),
        entry("http://cdn.example.com/app.js", resource_type="script"),
        entry("http://cdn.example.com/logo.png", resource_type="image"),
        entry("http://localhost:3000/dev.js", resource_type="script"),
        rules=["R010"],
    )
    [f] = findings
    assert f.severity.value == "high" and f.entries == [2, 3]


# ------------------------------------------------------------------ R011


def test_r011_groups_by_endpoint_with_ids() -> None:
    findings = run(
        entry(
            "https://api.a.com/orders/123", status=500, response_headers=headers(X_Request_Id="r1")
        ),
        entry(
            "https://api.a.com/orders/456", status=502, response_headers=headers(X_Request_Id="r2")
        ),
        entry("https://api.a.com/users/9", status=503),
        rules=["R011"],
    )
    assert len(findings) == 2
    orders = next(f for f in findings if "orders" in f.evidence["endpoint"])
    assert orders.evidence["endpoint"] == "GET api.a.com/orders/{id}"
    assert [i["x-request-id"] for i in orders.evidence["correlation_ids"]] == ["r1", "r2"]
    assert "502/504" in orders.cause


def test_findings_are_sorted_by_severity() -> None:
    findings = run(entry(status=500), entry("https://a.com/s", time=5000))
    ranks = [f.severity.rank for f in findings]
    assert ranks == sorted(ranks)
