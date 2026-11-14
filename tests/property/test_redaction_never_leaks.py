"""The headline test: no planted secret survives redaction, wherever it is planted.

Hypothesis builds HAR files with random secrets in every place the redaction
policy covers: headers, cookies, query strings, the Referer, form and JSON bodies
(nested), multipart fields, error bodies, GraphQL errors, WebSocket messages,
custom fields, page titles, URL user-info, and JWTs, bearer tokens, AWS key ids and
private keys in free text. Then it checks the redacted file, the findings and the
summary for the secret in raw, URL-encoded and JSON-escaped form.

Run more cases with: HYPOTHESIS_PROFILE=ci uv run pytest tests/property
"""

from __future__ import annotations

import io
import json
import string
from typing import Any
from urllib.parse import quote, quote_plus

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hartriage.pipeline import process
from hartriage.summary import summarise, to_html, to_json, to_markdown
from tests.support.har import b64url, entry, har, headers

TOKEN_ALPHABET = string.ascii_letters + string.digits + "-_.~+/"
B64URL = string.ascii_letters + string.digits + "-_"


@st.composite
def secrets(draw: st.DrawFn, alphabet: str = TOKEN_ALPHABET) -> str:
    body = draw(st.text(alphabet=alphabet, min_size=15, max_size=47))
    digit = draw(st.sampled_from(string.digits))
    at = draw(st.integers(0, len(body)))
    return body[:at] + digit + body[at:]


SENSITIVE_HEADERS = [
    "Authorization",
    "authorization",
    "X-API-Key",
    "x-api-key",
    "X-Auth-Token",
    "Proxy-Authorization",
    "X-CSRF-Token",
    "X-Shopify-Access-Token",
    "X-Session-Id",
    "Api-Key",
    "Private-Token",
    "X-Goog-Api-Key",
    "Ocp-Apim-Subscription-Key",
    "X-Hub-Signature-256",
    "X-Amz-Security-Token",
]
QUERY_NAMES = [
    "access_token",
    "id_token",
    "refresh_token",
    "token",
    "code",
    "api_key",
    "key",
    "password",
    "signature",
    "sig",
    "X-Amz-Signature",
    "X-Amz-Credential",
    "apiKey",
    "client_secret",
    "sessionId",
    "auth_token",
]
JSON_KEYS = [
    "password",
    "apiKey",
    "client_secret",
    "refresh_token",
    "accessToken",
    "secret",
    "api_key",
    "sessionToken",
    "authorization",
    "privateKey",
    "pin",
    "cvv",
]
FORM_NAMES = ["password", "passwd", "token", "client_secret", "code", "api_key", "otp"]


def jwt_with(secret: str) -> str:
    sig = "".join(c for c in secret if c in B64URL) or "x1"
    return f"{b64url({'alg': 'HS256'})}.{b64url({'sub': '1', 'n': sig[:6]})}.{sig}"


PLACEMENTS = [
    "header",
    "bearer_header",
    "cookie_header",
    "set_cookie",
    "cookie_array",
    "query",
    "referer",
    "form",
    "form_params",
    "json_nested",
    "multipart",
    "jwt_free_text",
    "jwt_in_path",
    "bearer_text",
    "aws_key",
    "private_key",
    "userinfo",
    "error_body",
    "graphql_errors",
    "ok_body",
    "websocket",
    "custom_field",
    "page_title",
    "location",
    "jsonish_broken",
]


@st.composite
def planted(draw: st.DrawFn) -> tuple[dict[str, Any], list[str]]:
    count = draw(st.integers(1, 6))
    entries = []
    leaked: list[str] = []
    pages = []
    for i in range(count):
        kind = draw(st.sampled_from(PLACEMENTS))
        secret = draw(secrets())
        depth = draw(st.integers(0, 4))
        req_headers = headers(Accept="application/json", User_Agent="Mozilla/5.0 test")
        resp_headers = headers(Content_Type="application/json")
        url = f"https://app{i}.example.com/api/v1/items"
        kw: dict[str, Any] = {}
        status = 200
        expect = secret
        if kind == "header":
            req_headers.append({"name": draw(st.sampled_from(SENSITIVE_HEADERS)), "value": secret})
        elif kind == "bearer_header":
            req_headers.append({"name": "Authorization", "value": f"Bearer {secret}"})
        elif kind == "cookie_header":
            req_headers.append(
                {
                    "name": "Cookie",
                    "value": f"lang=en; {draw(st.sampled_from(['sid', 'x', 'session']))}={secret}; a=b",
                }
            )
        elif kind == "set_cookie":
            resp_headers.append(
                {
                    "name": "Set-Cookie",
                    "value": f"sid={secret}; Path=/; HttpOnly; Secure; SameSite=Lax",
                }
            )
        elif kind == "cookie_array":
            kw["cookies"] = [
                {"name": "theme", "value": "dark"},
                {"name": "sid", "value": secret, "httpOnly": True},
            ]
        elif kind == "query":
            name = draw(st.sampled_from(QUERY_NAMES))
            url += f"?page=2&{name}={quote(secret, safe='')}"
            kw["query"] = [{"name": "page", "value": "2"}, {"name": name, "value": secret}]
        elif kind == "referer":
            req_headers.append(
                {
                    "name": "Referer",
                    "value": f"https://login.example.com/cb?state=xyz&access_token={quote(secret, safe='')}",
                }
            )
        elif kind == "form":
            name = draw(st.sampled_from(FORM_NAMES))
            kw["post"] = {
                "mimeType": "application/x-www-form-urlencoded",
                "text": f"user=bob&{name}={quote_plus(secret)}&remember=1",
            }
        elif kind == "form_params":
            name = draw(st.sampled_from(FORM_NAMES))
            kw["post"] = {
                "mimeType": "application/x-www-form-urlencoded",
                "text": "",
                "params": [{"name": "user", "value": "bob"}, {"name": name, "value": secret}],
            }
        elif kind == "json_nested":
            value: Any = {draw(st.sampled_from(JSON_KEYS)): secret}
            for _ in range(depth):
                value = draw(st.sampled_from([{"data": value}, [value], {"items": [1, value]}]))
            kw["post"] = {
                "mimeType": "application/json",
                "text": json.dumps({"op": "save", "payload": value}),
            }
        elif kind == "multipart":
            boundary = "----WebKitFormBoundaryabc"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="user"\r\n\r\nbob\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="password"\r\n\r\n{secret}\r\n'
                f"--{boundary}--\r\n"
            )
            kw["post"] = {"mimeType": f"multipart/form-data; boundary={boundary}", "text": body}
        elif kind == "jwt_free_text":
            expect = jwt_with(secret)
            where = draw(st.sampled_from(["header", "body"]))
            if where == "header":
                req_headers.append({"name": "X-Debug", "value": f"forwarded {expect} upstream"})
            else:
                kw["post"] = {
                    "mimeType": "application/json",
                    "text": json.dumps({"note": f"t={expect}", "n": 1}),
                }
        elif kind == "jwt_in_path":
            expect = jwt_with(secret)
            url = f"https://app{i}.example.com/reset/{expect}/confirm"
        elif kind == "bearer_text":
            kw["post"] = {
                "mimeType": "text/plain",
                "text": f"curl -H 'Authorization: Bearer {secret}' https://x",
            }
        elif kind == "aws_key":
            expect = "AKIA" + "".join(
                draw(
                    st.lists(
                        st.sampled_from(string.ascii_uppercase + string.digits),
                        min_size=16,
                        max_size=16,
                    )
                )
            )
            kw["post"] = {"mimeType": "text/plain", "text": f"aws configure set id {expect} done"}
        elif kind == "private_key":
            expect = f"-----BEGIN RSA PRIVATE KEY-----\nMIIE{secret}\n-----END RSA PRIVATE KEY-----"
            kw["post"] = {"mimeType": "text/plain", "text": f"key:\n{expect}\n"}
            leaked.append(f"MIIE{secret}")
        elif kind == "userinfo":
            url = f"https://bob:{quote(secret, safe='')}@app{i}.example.com/files"
        elif kind == "error_body":
            status = draw(st.sampled_from([400, 401, 422, 500]))
            kw["content"] = {
                "size": 80,
                "mimeType": "application/json",
                "text": json.dumps({"error": {"message": "bad", "api_key": secret}}),
            }
        elif kind == "graphql_errors":
            kw["content"] = {
                "size": 80,
                "mimeType": "application/json",
                "text": json.dumps(
                    {
                        "data": {"me": {"email": secret}},
                        "errors": [{"message": "denied", "extensions": {"token": secret}}],
                    }
                ),
            }
        elif kind == "ok_body":
            kw["content"] = {
                "size": 80,
                "mimeType": "application/json",
                "text": json.dumps({"anything": secret}),
            }
        elif kind == "websocket":
            kw["_webSocketMessages"] = [
                {"type": "send", "time": 1.0, "opcode": 1, "data": json.dumps({"auth": secret})}
            ]
        elif kind == "custom_field":
            kw["_auth"] = {"token": secret, "kind": "user"}
        elif kind == "page_title":
            pages.append(
                {
                    "id": f"page_{i}",
                    "title": f"https://app.example.com/?token={quote(secret, safe='')}",
                    "startedDateTime": "2026-11-14T10:00:00.000Z",
                    "pageTimings": {},
                }
            )
        elif kind == "location":
            status = 302
            resp_headers.append(
                {
                    "name": "Location",
                    "value": f"https://app.example.com/cb?code={quote(secret, safe='')}",
                }
            )
            kw["redirect"] = f"https://app.example.com/cb?code={quote(secret, safe='')}"
        elif kind == "jsonish_broken":
            kw["post"] = {
                "mimeType": "application/json",
                "text": '{"user": "bob", "password": "' + secret + '", "trunc',
            }
        entries.append(
            entry(
                url, status=status, request_headers=req_headers, response_headers=resp_headers, **kw
            )
        )
        leaked.append(expect)
    return har(*entries, pages=pages), leaked


def forms(secret: str) -> list[str]:
    return list({secret, quote(secret, safe=""), quote_plus(secret), json.dumps(secret)[1:-1]})


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(planted())
def test_no_planted_secret_survives(case: tuple[dict[str, Any], list[str]]) -> None:
    data, planted_secrets = case
    out = io.BytesIO()
    result = process(io.BytesIO(json.dumps(data).encode()), out=out)
    summary = summarise(result)
    texts = [
        out.getvalue().decode("utf-8"),
        to_json(summary, result.findings, {"report": result.report.to_dict()}),
        to_markdown(summary),
        to_html(summary),
        json.dumps([r.to_dict() for r in result.rows]),
    ]
    for secret in planted_secrets:
        for form in forms(secret):
            for text in texts:
                assert form not in text, f"secret leaked in form {form!r}"


@settings(max_examples=200, deadline=None)
@given(secrets())
def test_same_secret_same_marker_within_a_file(secret: str) -> None:
    data = har(
        entry(request_headers=[{"name": "Authorization", "value": f"Bearer {secret}"}]),
        entry(
            url=f"https://app.example.com/x?access_token={quote(secret, safe='')}",
            query=[{"name": "access_token", "value": secret}],
        ),
    )
    out = io.BytesIO()
    process(io.BytesIO(json.dumps(data).encode()), out=out)
    redacted = json.loads(out.getvalue())
    header = redacted["log"]["entries"][0]["request"]["headers"][0]["value"]
    query = redacted["log"]["entries"][1]["request"]["queryString"][0]["value"]
    assert header == f"Bearer {query}"
    assert query.startswith("[REDACTED:")


@settings(max_examples=100, deadline=None)
@given(secrets())
def test_markers_differ_across_files(secret: str) -> None:
    data = har(entry(request_headers=[{"name": "X-API-Key", "value": secret}]))
    markers = set()
    for _ in range(2):
        out = io.BytesIO()
        process(io.BytesIO(json.dumps(data).encode()), out=out)
        markers.add(
            json.loads(out.getvalue())["log"]["entries"][0]["request"]["headers"][0]["value"]
        )
    assert len(markers) == 2  # a fresh salt per file: markers can't be matched across files
