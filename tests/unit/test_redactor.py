from __future__ import annotations

import json
from typing import Any

import pytest

from hartriage.har.redactor import (
    MARKER_RE,
    RedactionPolicy,
    Redactor,
    is_sensitive_header,
    is_sensitive_name,
    report_sentence,
)
from tests.support.har import entry, headers, make_jwt

SECRET = "s3cr3t" + "Value" + "9f8e7d6c"  # assembled so scanners don't flag the source


def red() -> Redactor:
    return Redactor(salt=b"fixed-salt-for-tests")


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "x-api-key",
        "X-Auth-Token",
        "Cookie",
        "X-Shopify-Access-Token",
        "X-Session-Id",
        "Private-Token",
        "x-xsrf-token",
        "X-Hub-Signature-256",
        "Sec-WebSocket-Key",
    ],
)
def test_sensitive_headers(name: str) -> None:
    assert is_sensitive_header(name)


@pytest.mark.parametrize(
    "name",
    [
        "WWW-Authenticate",
        "Content-Type",
        "X-Request-Id",
        "Keep-Alive",
        "Access-Control-Allow-Credentials",
        "Retry-After",
        "cf-ray",
        "X-RateLimit-Remaining",
        "traceparent",
        "Vary",
    ],
)
def test_harmless_headers(name: str) -> None:
    assert not is_sensitive_header(name)


def test_names_match_words_not_substrings() -> None:
    assert is_sensitive_name("apiKey") and is_sensitive_name("refresh_token")
    assert not is_sensitive_name("keyword") and not is_sensitive_name("author")
    assert not is_sensitive_name("monkey") and not is_sensitive_name("country_code")
    assert is_sensitive_name("code", query=True) and not is_sensitive_name("code")


def test_marker_is_stable_and_short() -> None:
    r = red()
    assert r.marker(SECRET) == r.marker(SECRET)
    assert MARKER_RE.fullmatch(r.marker(SECRET))
    assert r.marker(r.marker(SECRET)) == r.marker(SECRET)  # already redacted stays as is


def test_authorization_keeps_the_scheme() -> None:
    value = red().header_value("Authorization", f"Bearer {SECRET}")
    assert value.startswith("Bearer [REDACTED:") and SECRET not in value


def test_unknown_scheme_is_not_kept() -> None:
    value = red().header_value("Authorization", f"{SECRET} {SECRET}x")
    assert MARKER_RE.fullmatch(value)


def test_cookie_names_and_set_cookie_attributes_are_kept() -> None:
    r = red()
    cookie = r.header_value("Cookie", f"sid={SECRET}; theme=dark")
    assert cookie.startswith("sid=[REDACTED:") and "; theme=[REDACTED:" in cookie
    set_cookie = r.header_value(
        "Set-Cookie", f"sid={SECRET}; Path=/; Secure; HttpOnly; SameSite=None"
    )
    assert SECRET not in set_cookie and set_cookie.endswith(
        "; Path=/; Secure; HttpOnly; SameSite=None"
    )


def test_www_authenticate_challenge_is_kept() -> None:
    value = 'Bearer realm="api", error="invalid_token", error_description="The token expired"'
    assert red().header_value("WWW-Authenticate", value) == value


def test_prose_after_bearer_is_not_mistaken_for_a_token() -> None:
    text = "Bearer authentication required for this endpoint"
    assert red().text(text) == text


def test_free_text_patterns() -> None:
    r = red()
    jwt = make_jwt(exp=1)
    aws = "AKIA" + "IOSFODNN7" + "EXAMPL1"
    key = "-----BEGIN PRIVATE KEY-----\nMIIabc\n-----END PRIVATE KEY-----"
    text = f"jwt {jwt} aws {aws} key {key} url https://bob:{SECRET}@host/x?password={SECRET}&page=2"
    out = r.text(text)
    for value in (jwt, aws, "MIIabc", SECRET):
        assert value not in out
    assert "page=2" in out and "https://bob:" in out
    counts = r.report.counts()
    assert counts["aws_keys"] == 1 and counts["private_keys"] == 1


def test_url_query_and_fragment() -> None:
    out = red().url(f"https://app.example.com/cb?state=abc&code={SECRET}#access_token={SECRET}&x=1")
    assert SECRET not in out and "state=abc" in out and "x=1" in out


def test_json_body_walks_nested_keys() -> None:
    body = {
        "user": "bob",
        "auth": {"password": SECRET, "remember": True},
        "items": [{"apiKey": SECRET, "qty": 2}],
        "note": f"bearer {SECRET}",
    }
    out = red().body_text(json.dumps(body), "application/json")
    data = json.loads(out)
    assert SECRET not in out
    assert (
        data["user"] == "bob" and data["auth"]["remember"] is True and data["items"][0]["qty"] == 2
    )


def test_form_body() -> None:
    out = red().body_text(
        f"user=bob&password={SECRET}&next=%2Fhome", "application/x-www-form-urlencoded"
    )
    assert out.startswith("user=bob&password=[REDACTED:") and out.endswith("&next=%2Fhome")


def test_large_request_body_is_dropped() -> None:
    r = Redactor(RedactionPolicy(request_body_max_bytes=10))
    post: dict[str, Any] = {"mimeType": "text/plain", "text": "x" * 50}
    r.post_data(post)
    assert post["text"] == "" and post["_size"] == 50 and r.report.request_bodies_removed == 1


def test_response_bodies_dropped_but_small_json_errors_kept() -> None:
    r = red()
    ok: dict[str, Any] = {"size": 10, "mimeType": "text/html", "text": "<p>hello</p>"}
    r.response_content(ok, 200)
    assert "text" not in ok and "removed" in ok["comment"]
    err: dict[str, Any] = {
        "size": 40,
        "mimeType": "application/json",
        "text": json.dumps({"error": {"code": "card_declined", "message": "No", "token": SECRET}}),
    }
    r.response_content(err, 402)
    kept = json.loads(err["text"])
    assert kept["error"]["code"] == "card_declined" and SECRET not in err["text"]


def test_base64_error_body_is_decoded() -> None:
    import base64

    r = red()
    err: dict[str, Any] = {
        "size": 10,
        "mimeType": "application/json",
        "encoding": "base64",
        "text": base64.b64encode(b'{"message": "bad request"}').decode(),
    }
    r.response_content(err, 400)
    assert json.loads(err["text"]) == {"message": "bad request"} and "encoding" not in err


def test_graphql_keeps_errors_only() -> None:
    r = red()
    body: dict[str, Any] = {
        "size": 10,
        "mimeType": "application/json",
        "text": json.dumps({"data": {"email": "a@b.c"}, "errors": [{"message": "Not allowed"}]}),
    }
    r.response_content(body, 200)
    assert json.loads(body["text"]) == {"errors": [{"message": "Not allowed"}]}


def test_redact_entry_covers_every_part() -> None:
    r = red()
    e = entry(
        f"https://api.example.com/x?token={SECRET}",
        request_headers=headers(
            Authorization=f"Bearer {SECRET}", Referer=f"https://a.com/?sig={SECRET}"
        ),
        query=[{"name": "token", "value": SECRET}],
        cookies=[{"name": "sid", "value": SECRET}],
        response_headers=headers(X_Request_Id="req-123", Location=f"/next?code={SECRET}"),
        redirect=f"/next?code={SECRET}",
        _webSocketMessages=[{"type": "send", "data": SECRET}],
        _custom={"token": SECRET},
        _hartriage={"credentials": ["forged"]},
    )
    r.redact_entry(e)
    text = json.dumps(e)
    assert SECRET not in text
    assert "req-123" in text  # correlation ids survive
    assert "_hartriage" not in e  # metadata in the input is never trusted
    assert r.report.entries_touched == 1


def test_report_sentence() -> None:
    assert report_sentence({"tokens": 14, "cookies": 6, "api_keys": 2}, 37, 52, 210) == (
        "Removed 14 tokens, 6 cookies and 2 API keys (37 places in 52 requests)."
        " Dropped 210 response bodies."
    )
    assert report_sentence({}, 0, 0, 0) == "No secrets found."
