"""Found live: httpx logged pre-signed attachment URLs (S3 X-Amz-Signature), which
would let anyone with log access download a customer's unredacted HAR."""

from __future__ import annotations

import logging

from hartriage.core.logging import configure


def test_http_client_request_urls_are_not_logged() -> None:
    logging.getLogger("httpx").setLevel(logging.INFO)
    configure("INFO", json_logs=True)
    for name in ("httpx", "httpcore"):
        assert not logging.getLogger(name).isEnabledFor(logging.INFO)
