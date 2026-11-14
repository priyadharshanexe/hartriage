"""A small local server that fails on purpose, for recording golden HAR files.

Two origins run side by side so CORS can be tested:

* the app,   http://app.test:8471  (and https://shop.test:8473 for mixed content)
* the API,   http://api.test:8472

`record.py` maps *.test to 127.0.0.1 inside the browser. Each scenario is a page
under /scenario/<name> that makes the requests and then sets `window.done = true`.

Tokens minted here are signed with a throwaway key generated at start-up; they
are fake, expired on purpose and worthless.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

APP_PORT, API_PORT, TLS_PORT = 8471, 8472, 8473
APP = f"http://app.test:{APP_PORT}"
API = f"http://api.test:{API_PORT}"
SHOP = f"https://shop.test:{TLS_PORT}"
KEY = os.urandom(32)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def mint(exp_offset: int, scope: str = "orders:read") -> str:
    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = b64(
        json.dumps(
            {
                "sub": "user-1001",
                "iat": now - 7200,
                "exp": now + exp_offset,
                "aud": API,
                "scope": scope,
            }
        ).encode()
    )
    sig = b64(hmac.new(KEY, f"{header}.{claims}".encode(), hashlib.sha256).digest())
    return f"{header}.{claims}.{sig}"


def page(title: str, script: str) -> bytes:
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<link rel="icon" href="data:,"></head><body><h1>{title}</h1><pre id="log"></pre><script>
const log = (m) => document.getElementById('log').textContent += m + "\\n";
const API = "{API}";
async function main() {{
{script}
}}
main().catch(e => log('error: ' + e)).finally(() => {{ window.done = true; }});
</script></body></html>""".encode()


SCENARIOS: dict[str, tuple[str, str]] = {
    "healthy": (
        "Dashboard",
        """
  await fetch('/api/me').then(r => r.json());
  await fetch('/api/orders?page=1').then(r => r.json());
  await fetch('/static/app.css');
""",
    ),
    "auth": (
        "Orders",
        """
  const expired = "{EXPIRED}";
  await fetch('/api/me', {headers: {Authorization: 'Bearer ' + expired}});
  await fetch('/api/orders', {headers: {Authorization: 'Bearer ' + expired}});
  await fetch('/api/admin/users', {headers: {Authorization: 'Bearer {VALID}'}});
  await fetch('/api/settings');
""",
    ),
    "rate-limit": (
        "Search",
        """
  for (let i = 0; i < 5; i++) { await fetch('/api/search?q=shoes&page=' + i); }
""",
    ),
    "server-errors": (
        "Reports",
        """
  await fetch('/api/orders/123');
  await fetch('/api/orders/456');
  await fetch('/api/reports/weekly');
""",
    ),
    "payload": (
        "Import",
        """
  await fetch('/api/import', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({rows: 'x'.repeat(2 * 1024 * 1024)})});
  await fetch('/api/cookies/bloat');
  await fetch('/api/profile');
""",
    ),
    "slow": (
        "Analytics",
        """
  await fetch('/api/report?range=90d');
  await fetch('/api/me');
""",
    ),
    "cors": (
        "Integrations",
        """
  try { await fetch(API + '/v1/data'); } catch (e) { log('blocked: ' + e); }
  try { await fetch(API + '/v1/data', {method: 'PUT', headers: {'X-Client': 'web'}, body: '{}'}); }
  catch (e) { log('blocked: ' + e); }
  await fetch(API + '/v1/open').then(r => r.json());
""",
    ),
    "redirects": (
        "Account",
        """
  try { await fetch('/loop/a'); } catch (e) { log('loop: ' + e); }
  await fetch('/hop/1');
""",
    ),
    "network": (
        "Status",
        """
  const tries = ['http://does-not-exist.invalid/ping', 'http://127.0.0.1:59999/ping',
                 'https://expired.badssl.com/'];
  for (const u of tries) { try { await fetch(u, {mode: 'no-cors'}); } catch (e) { log(u + ': ' + e); } }
""",
    ),
    "api-errors": (
        "Checkout",
        """
  for (let i = 0; i < 2; i++) {
    await fetch('/api/payments', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({amount: 1999, card_token: 'tok_' + i})});
  }
  await fetch('/api/signup', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email: '', password: 'hunter2-not-real'})});
""",
    ),
    "mixed-content": (
        "Shop",
        """
  const s = document.createElement('script'); s.src = 'http://cdn.test:8471/static/widget.js';
  document.body.appendChild(s);
  await new Promise(r => setTimeout(r, 500));
  try { await fetch('http://cdn.test:8471/api/me'); } catch (e) { log('mixed: ' + e); }
""",
    ),
    "checkout-story": (
        "Checkout",
        """
  await fetch('/static/app.css');
  await fetch('/api/me', {headers: {Authorization: 'Bearer {EXPIRED}'}});
  await fetch('/api/cart', {headers: {Authorization: 'Bearer {EXPIRED}'}});
  await fetch('/api/orders', {headers: {Authorization: 'Bearer {EXPIRED}'}});
  await fetch('/api/report?range=90d');
  await fetch('/api/orders/123');
""",
    ),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "fault-server/1.0"
    protocol_version = "HTTP/1.1"
    counters: ClassVar[dict[str, int]] = {}
    lock = threading.Lock()

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def send(
        self,
        status: int,
        body: bytes = b"",
        ctype: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-Id", f"req-{os.urandom(4).hex()}")
        for k, v in (headers or {}).items():
            for value in v.split("\n"):
                self.send_header(k, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, status: int, data: object, headers: dict[str, str] | None = None) -> None:
        self.send(status, json.dumps(data).encode(), headers=headers)

    def body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def do_OPTIONS(self) -> None:
        port = self.server.server_address[1]
        if port == API_PORT and self.path.startswith("/v1/data"):
            self.send(405, b"", "text/plain")  # preflights are not handled: the bug under test
            return
        self.send(
            204,
            b"",
            "text/plain",
            {
                "Access-Control-Allow-Origin": APP,
                "Access-Control-Allow-Methods": "GET, PUT",
                "Access-Control-Allow-Headers": "X-Client",
            },
        )

    def do_PUT(self) -> None:
        self.body()
        self.json(200, {"ok": True})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self.body()
        if path == "/api/import":
            self.json(
                413,
                {"error": {"code": "payload_too_large", "message": "Request body exceeds 1 MB"}},
            )
        elif path == "/api/payments":
            self.json(
                402,
                {
                    "error": {
                        "code": "card_declined",
                        "message": "Your card was declined.",
                        "decline_code": "insufficient_funds",
                    }
                },
            )
        elif path == "/api/signup":
            _ = body
            self.json(
                422,
                {
                    "detail": [
                        {"loc": ["body", "email"], "msg": "field required", "type": "missing"}
                    ]
                },
            )
        else:
            self.json(404, {"detail": "Not Found"})

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        port = self.server.server_address[1]
        auth = self.headers.get("Authorization", "")
        if path.startswith("/scenario/"):
            name = path.split("/")[2]
            title, script = SCENARIOS[name]
            script = script.replace("{EXPIRED}", mint(-900)).replace("{VALID}", mint(3600))
            self.send(200, page(title, script), "text/html; charset=utf-8")
        elif path == "/static/app.css":
            self.send(200, b"body{font-family:sans-serif}", "text/css")
        elif path == "/static/widget.js":
            self.send(200, b"window.widget = true;", "text/javascript")
        elif path == "/static/logo.png":
            self.send(200, b"\x89PNG\r\n\x1a\n", "image/png")
        elif port == API_PORT and path == "/v1/data":
            self.json(200, {"items": []})  # no Access-Control-Allow-Origin: the bug under test
        elif port == API_PORT and path == "/v1/open":
            self.json(200, {"ok": True}, {"Access-Control-Allow-Origin": APP})
        elif path in ("/api/me", "/api/orders", "/api/cart"):
            if auth.startswith("Bearer "):
                self.json(
                    401,
                    {"error": "invalid_token", "error_description": "The access token expired"},
                    {
                        "WWW-Authenticate": 'Bearer realm="api", error="invalid_token", error_description="The access token expired"'
                    },
                )
            elif self.headers.get("Cookie", "") and len(self.headers.get("Cookie", "")) > 8000:
                self.json(431, {"error": "headers too large"})
            else:
                self.json(200, {"id": "user-1001", "name": "Test User"})
        elif path == "/api/admin/users":
            self.json(
                403,
                {"error": "insufficient_scope", "error_description": "requires admin:users"},
                {
                    "WWW-Authenticate": 'Bearer error="insufficient_scope", error_description="requires admin:users"'
                },
            )
        elif path == "/api/settings":
            self.json(401, {"message": "Authentication required"})
        elif path == "/api/search":
            with self.lock:
                n = self.counters["search"] = self.counters.get("search", 0) + 1
            if n == 1:
                self.json(
                    200, {"results": []}, {"X-RateLimit-Limit": "1", "X-RateLimit-Remaining": "0"}
                )
            else:
                self.json(
                    429,
                    {"error": {"code": "rate_limited", "message": "Too many requests"}},
                    {
                        "Retry-After": "30",
                        "X-RateLimit-Limit": "1",
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time.time()) + 30),
                    },
                )
        elif path.startswith("/api/orders/"):
            self.json(
                500,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Unexpected error. Reference this request id.",
                    }
                },
            )
        elif path == "/api/reports/weekly":
            self.send(502, b"<html><body>Bad Gateway</body></html>", "text/html")
        elif path == "/api/cookies/bloat":
            cookies = "\n".join(f"pref{i}={'v' * 3000}; Path=/" for i in range(4))
            self.json(200, {"ok": True}, {"Set-Cookie": cookies})
        elif path == "/api/profile":
            if len(self.headers.get("Cookie", "")) > 8000:
                self.json(
                    431,
                    {
                        "error": {
                            "code": "headers_too_large",
                            "message": "Request headers too large",
                        }
                    },
                )
            else:
                self.json(200, {"ok": True})
        elif path == "/api/report":
            time.sleep(3.5 if query.get("range") == ["90d"] else 0)
            self.json(200, {"rows": 3})
        elif path.startswith("/loop/"):
            nxt = "/loop/b" if path == "/loop/a" else "/loop/a"
            self.send(302, b"", "text/plain", {"Location": nxt})
        elif path.startswith("/hop/"):
            n = int(path.split("/")[2])
            if n < 6:
                self.send(301, b"", "text/plain", {"Location": f"/hop/{n + 1}"})
            else:
                self.json(200, {"arrived": True})
        else:
            self.json(404, {"detail": "Not Found"})


def tls_context(directory: Path) -> ssl.SSLContext:
    """A throwaway self-signed certificate for https://shop.test."""
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "shop.test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("shop.test")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    cert_path.unlink()
    key_path.unlink()
    return ctx


def serve(tmp: Path) -> list[ThreadingHTTPServer]:
    servers = [
        ThreadingHTTPServer(("127.0.0.1", p), Handler) for p in (APP_PORT, API_PORT, TLS_PORT)
    ]
    servers[2].socket = tls_context(tmp).wrap_socket(servers[2].socket, server_side=True)
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    return servers


def reset() -> None:
    Handler.counters.clear()
