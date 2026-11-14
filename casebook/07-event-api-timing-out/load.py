"""The customer's integration: N concurrent POST /v1/events, 40 s client timeout.
Prints one line per request: start offset, status, seconds taken, request id.

    API_KEY=... python load.py http://localhost:8101 40
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE, N = sys.argv[1], int(sys.argv[2])
KEY = os.environ["API_KEY"]
T0 = time.monotonic()


def send(i: int) -> tuple[float, str, float, str]:
    body = json.dumps({"type": "order.paid", "payload": {"order_id": 9000 + i}}).encode()
    req = urllib.request.Request(f"{BASE}/v1/events", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310 - local test URL
            status, rid = str(r.status), r.headers.get("X-Request-ID", "")
    except urllib.error.HTTPError as e:
        status, rid = str(e.code), e.headers.get("X-Request-ID", "")
    except OSError:
        status, rid = "client timeout", ""
    return start - T0, status, time.monotonic() - start, rid


with ThreadPoolExecutor(N) as pool:
    results = list(pool.map(send, range(N)))
for offset, status, took, rid in sorted(results):
    print(f"+{offset:4.1f}s  {status:>14}  {took:5.1f}s  {rid}")
summary: dict[str, int] = {}
for _, status, _, _ in results:
    summary[status] = summary.get(status, 0) + 1
print("summary:", summary)
