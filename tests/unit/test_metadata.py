from __future__ import annotations

from hartriage.har.metadata import EntryMeta, decode_jwt_claims, extract
from hartriage.har.redactor import Redactor
from tests.support.har import entry, headers, make_jwt


def test_jwt_claims_are_decoded_without_verifying() -> None:
    token = make_jwt(exp=2_000_000_000, iat=1_900_000_000, aud="https://api.example.com")
    claims = decode_jwt_claims(token)
    assert claims is not None and claims["exp"] == 2_000_000_000
    assert decode_jwt_claims("not.a.jwt") is None


def test_extract_reads_credentials_jwts_and_ids() -> None:
    r = Redactor(salt=b"s")
    token = make_jwt(exp=1_700_000_000, aud="api")
    e = entry(
        "https://api.example.com/v1?api_key=abc",
        request_headers=headers(Authorization=f"Bearer {token}", Cookie="sid=1", X_Api_Key="k"),
        query=[{"name": "api_key", "value": "abc"}],
        response_headers=headers(X_Request_Id="req-9", CF_Ray="8f1a-AMS"),
    )
    meta = extract(e, r)
    assert meta.credentials == [
        "authorization:bearer",
        "cookie",
        "header:x-api-key",
        "query:api_key",
    ]
    assert meta.jwts[0].exp == 1_700_000_000 and meta.jwts[0].aud == ["api"]
    assert meta.jwts[0].marker == r.marker(token)
    assert meta.correlation_ids == {"x-request-id": "req-9", "cf-ray": "8f1a-AMS"}
    assert meta.cookie_header_bytes == len("sid=1")


def test_no_credentials() -> None:
    meta = extract(entry(request_headers=headers(Accept="*/*")), Redactor())
    assert meta.credentials == [] and not meta.credentials_present


def test_round_trip() -> None:
    r = Redactor()
    meta = extract(entry(request_headers=headers(Authorization="Bearer " + make_jwt(exp=5))), r)
    again = EntryMeta.from_dict(meta.to_dict())
    assert again == meta
    assert EntryMeta.from_dict("garbage") == EntryMeta()
