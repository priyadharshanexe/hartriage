"""The customer's webhook receiver: two nodes behind a round-robin load balancer.

It verifies Standard Webhooks signatures the way the official libraries do,
including the 5-minute timestamp tolerance. Node web-2's clock is wrong by
CLOCK_SKEW_SECONDS (its NTP client stopped), which is the whole case.

    SECRET=whsec_... CLOCK_SKEW_SECONDS=-420 python receiver.py 9912
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import itertools
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = os.environ["SECRET"]
SKEW = int(os.environ.get("CLOCK_SKEW_SECONDS", "-420"))
TOLERANCE = 300
NODES = itertools.cycle([("web-1", 0), ("web-2", SKEW)])


def verify(headers: dict[str, str], body: bytes, now: float) -> str | None:
    msg_id, ts, signatures = headers.get("webhook-id", ""), headers.get("webhook-timestamp", ""), headers.get("webhook-signature", "")
    if not (msg_id and ts.isdigit() and signatures):
        return "missing webhook headers"
    drift = now - int(ts)
    if drift > TOLERANCE:
        return f"timestamp too old ({drift:.0f} s; tolerance {TOLERANCE} s)"
    if drift < -TOLERANCE:
        return f"timestamp too new ({-drift:.0f} s in the future; tolerance {TOLERANCE} s)"
    key = base64.b64decode(SECRET.removeprefix("whsec_"))
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    for candidate in signatures.split():
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return None
    return "no matching signature"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        node, skew = next(NODES)
        now = time.time() + skew
        error = verify({k.lower(): v for k, v in self.headers.items()}, body, now)
        status = 401 if error else 200
        reply = json.dumps({"node": node, "error": error} if error else {"node": node, "ok": True}).encode()
        self.send_response_only(status)  # no automatic Date: each node stamps its own clock
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Served-By", node)
        self.send_header("Date", self.date_time_string(now))
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)
        print(f"{node} {status} {self.headers.get('webhook-id')} {error or 'ok'}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 9912), Handler).serve_forever()
