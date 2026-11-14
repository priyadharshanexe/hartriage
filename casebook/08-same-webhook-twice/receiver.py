"""The customer's receiver: it ships the order as soon as the webhook arrives, then
does slow bookkeeping before answering. With DEDUPE=1 it remembers webhook-ids and
acknowledges a repeat without shipping again.

    DELAY=8 DEDUPE=0 python receiver.py 9918
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DELAY = float(os.environ.get("DELAY", "8"))
DEDUPE = os.environ.get("DEDUPE") == "1"
seen: set[str] = set()
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        msg_id = self.headers.get("webhook-id", "")
        order = body.get("data", body).get("order_id") if isinstance(body, dict) else None
        with lock:
            repeat = msg_id in seen
            seen.add(msg_id)
        stamp = time.strftime("%H:%M:%S")
        if DEDUPE and repeat:
            print(f"{stamp} {msg_id} order={order} DUPLICATE, acknowledged without shipping", flush=True)
        else:
            print(f"{stamp} {msg_id} order={order} SHIPPED{' (again!)' if repeat else ''}", flush=True)
            time.sleep(DELAY)  # slow bookkeeping before the response
        reply = b'{"ok": true}'
        try:
            self.send_response(200)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)
        except OSError:
            pass  # the sender went away mid-request


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 9918), Handler).serve_forever()
