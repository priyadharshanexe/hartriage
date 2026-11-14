"""The customer's receiver after their outage: it accepts 2 requests a second and
answers the rest with 429 and Retry-After, like most API gateways.

    RATE=2 RETRY_AFTER=30 python receiver.py 9913
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RATE = float(os.environ.get("RATE", "2"))
RETRY_AFTER = int(os.environ.get("RETRY_AFTER", "30"))
lock = threading.Lock()
tokens, last = RATE, time.monotonic()


def take() -> bool:
    global tokens, last
    with lock:
        now = time.monotonic()
        tokens = min(RATE, tokens + (now - last) * RATE)
        last = now
        if tokens >= 1:
            tokens -= 1
            return True
        return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        ok = take()
        body = json.dumps({"ok": True} if ok else {"error": "rate limit exceeded", "limit": f"{RATE:g}/s"}).encode()
        self.send_response(200 if ok else 429)
        if not ok:
            self.send_header("Retry-After", str(RETRY_AFTER))
        self.send_header("X-RateLimit-Limit", f"{RATE:g}")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(f"{time.strftime('%H:%M:%S')} {200 if ok else 429} {self.headers.get('webhook-id')}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 9913), Handler).serve_forever()
