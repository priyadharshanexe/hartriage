"""Create a HAR Triage account and a Freshdesk connection for live testing.

Writes the HAR Triage test login and the Freshdesk webhook secret to .env.live
(gitignored). Prints only ids and URLs, never secrets.
"""

from __future__ import annotations

import secrets
import time

import httpx

from tools.live.env import ROOT, load

API = "http://127.0.0.1:8200"


def append(values: dict[str, str]) -> None:
    with (ROOT / ".env.live").open("a", encoding="utf-8") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")


def main() -> None:
    env = load()
    with httpx.Client(base_url=API, timeout=60) as c:
        if "HARTRIAGE_LIVE_EMAIL" not in env:
            email = f"live-{int(time.time())}@example.com"
            password = secrets.token_urlsafe(18)
            r = c.post(
                "/v1/auth/register",
                json={
                    "name": "Live Tester",
                    "email": email,
                    "password": password,
                    "organization": "Live helpdesk tests",
                },
            )
            r.raise_for_status()
            append({"HARTRIAGE_LIVE_EMAIL": email, "HARTRIAGE_LIVE_PASSWORD": password})
            env = load()
        token = c.post(
            "/v1/auth/login",
            json={"email": env["HARTRIAGE_LIVE_EMAIL"], "password": env["HARTRIAGE_LIVE_PASSWORD"]},
        ).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        domain = env["FRESHDESK_DOMAIN"].replace("https://", "").split(".freshdesk.com")[0]
        r = c.post(
            "/v1/connections",
            headers=auth,
            json={
                "platform": "freshdesk",
                "subdomain": domain,
                "api_key": env["FRESHDESK_API_KEY"],
            },
        )
        print("create connection:", r.status_code)
        r.raise_for_status()
        conn = r.json()
        append(
            {
                "FRESHDESK_CONNECTION_ID": conn["id"],
                "FRESHDESK_WEBHOOK_SECRET": conn["webhook_secret"],
            }
        )
        print("connection", conn["id"], "account", conn.get("account"))
        print("webhook", conn["webhook_url"])


if __name__ == "__main__":
    main()
