"""The customer's receiver: verifies Standard Webhooks signatures with ONE secret,
the one it was deployed with.

    SECRET=whsec_... python receiver.py 9916
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = os.environ["SECRET"]


def verify(headers: dict[str, str], body: bytes) -> tuple[str | None, int]:
    msg_id, ts, header = headers.get("webhook-id", ""), headers.get("webhook-timestamp", ""), headers.get("webhook-signature", "")
    signatures = header.split()
    if abs(time.time() - int(ts or 0)) > 300:
        return "timestamp outside tolerance", len(signatures)
    key = base64.b64decode(SECRET.removeprefix("whsec_"))
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    if any(hmac.compare_digest(s.partition(",")[2], expected) for s in signatures):
        return None, len(signatures)
    return "no matching signature", len(signatures)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        error, count = verify({k.lower(): v for k, v in self.headers.items()}, body)
        reply = json.dumps({"error": error, "signatures_received": count} if error else {"ok": True, "signatures_received": count}).encode()
        self.send_response(401 if error else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)
        print(f"{time.strftime('%H:%M:%S')} {401 if error else 200} signatures={count} {error or 'ok'}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 9916), Handler).serve_forever()
