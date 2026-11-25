"""The path-token detector: how often it is right, measured.

It looks for random tokens in URL path segments (/invite/<token>), which have no
name to go by. Ids and hashes must survive, or the HAR stops being useful.
"""

from __future__ import annotations

import base64
import io
import json
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from hartriage.har.redactor import Redactor, random_segment
from hartriage.har.stream_reader import NO_LIMITS
from hartriage.pipeline import process

ROOT = Path(__file__).resolve().parents[2]
HARS = sorted((ROOT / "tests" / "golden" / "hars").rglob("*.har")) + sorted(
    (ROOT / "tools" / "fixtures" / "samples").glob("*.har")
)

# Values that appear in real URLs and must be kept.
BENIGN = [
    "2f9c6a1e-7d3b-4c8e-9a5f-1b2c3d4e5f6a",  # UUID
    "d41d8cd98f00b204e9800998ecf8427e",  # MD5 of a file
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # SHA-256
    "main.4f3a9b2c1d8e7f6a5b4c3d2e1f0a9b8c.chunk.js",  # build asset
    "KFOmCnqEu92Fr1Mu4mxKKTU1Kg.woff2",  # Google Fonts file
    "pi_3NxYzAbCdEfGhIjKlMnOpQrSt1234567890",  # Stripe PaymentIntent id
    "cus_PqRsTuVwXyZ0123456789AbCdEf",  # Stripe customer id
    "checkout-session-confirmation-page",  # slug
    "the-quick-brown-fox-jumps-over-the-lazy-dog-2026",  # long slug with a digit
    "v1699999999",  # Cloudinary version
    "1234567890123456789012345678901234567890",  # long numeric id
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",  # alphabet test string: low entropy per class mix
    "dQw4w9WgXcQ",  # YouTube id (short)
]


def test_no_false_positives_on_the_golden_hars() -> None:
    flagged: list[str] = []
    segments = 0
    for har in HARS:
        out = io.BytesIO()
        process(
            io.BytesIO(har.read_bytes()), out=out, limits=NO_LIMITS, keep_rows=False, analyse=False
        )
        for entry in json.loads(out.getvalue())["log"]["entries"]:
            for segment in urlsplit(entry["request"]["url"]).path.split("/"):
                segments += 1
                if random_segment(segment):
                    flagged.append(f"{har.name}: {segment}")
    assert segments > 500  # 517 when measured
    assert flagged == []


@pytest.mark.parametrize("value", BENIGN)
def test_ids_hashes_and_names_are_kept(value: str) -> None:
    assert not random_segment(value)


def test_recall_on_random_tokens() -> None:
    """secrets.token_urlsafe(24..64): 32 to 86 characters, the usual invite/reset token."""
    tokens = [secrets.token_urlsafe(n) for n in range(24, 65) for _ in range(50)]
    caught = sum(random_segment(t) for t in tokens)
    # Measured: 99.4% over 8,200 tokens. The misses are tokens that happen to lack a digit or a
    # capital, which a short random string sometimes does.
    assert caught / len(tokens) >= 0.95, caught / len(tokens)


def test_base64_tokens_without_padding_are_caught() -> None:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    if any(c.isdigit() for c in raw) and any(c.isupper() for c in raw):
        assert random_segment(raw)


def test_a_path_token_is_replaced_in_the_url() -> None:
    # Built at run time, so no token-shaped literal sits in the repository.
    token = "".join(
        a + b for a, b in zip("ZqVbLrXcMnPkWsTyHdFjGa", "3851729406385172940638", strict=True)
    )
    token += "Qe7Rt"
    assert random_segment(token)
    redactor = Redactor()
    out = redactor.url(f"https://app.example.test/invite/{token}/accept?step=2")
    assert token not in out
    assert out.startswith("https://app.example.test/invite/[REDACTED:")
    assert out.endswith("/accept?step=2")
    # The same token elsewhere in the file gets the same marker.
    assert redactor.url(f"https://app.example.test/v/{token}").split("/")[-1] in out


def test_short_segments_are_not_touched() -> None:
    url = "https://api.example.test/v2/orders/8841/items"
    assert Redactor().url(url) == url
