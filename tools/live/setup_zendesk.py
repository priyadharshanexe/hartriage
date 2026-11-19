"""Connect HAR Triage to the live Zendesk trial with the confidential OAuth client.

Prints only ids and URLs; the connection id goes to .env.live (gitignored).
"""

from __future__ import annotations

import httpx

from tools.live.env import load
from tools.live.setup_freshdesk import API, append


def main() -> None:
    env = load()
    with httpx.Client(base_url=API, timeout=60) as c:
        token = c.post(
            "/v1/auth/login",
            json={"email": env["HARTRIAGE_LIVE_EMAIL"], "password": env["HARTRIAGE_LIVE_PASSWORD"]},
        ).json()["access_token"]
        r = c.post(
            "/v1/connections",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "platform": "zendesk",
                "subdomain": env["ZENDESK_SUBDOMAIN"],
                "oauth_client_id": env["ZENDESK_OAUTH_CLIENT_ID"],
                "oauth_client_secret": env["ZENDESK_OAUTH_CLIENT_SECRET"],
                "replace_attachments": True,
            },
        )
        print("create connection:", r.status_code, r.text[:300] if r.status_code >= 300 else "")
        r.raise_for_status()
        conn = r.json()
        append({"ZENDESK_CONNECTION_ID": conn["id"]})
        print("connection", conn["id"], "auth", conn["auth_type"], "account", conn.get("account"))
        print("needs signing secret:", conn["needs_signing_secret"])
        print("webhook", conn["webhook_url"])


if __name__ == "__main__":
    main()
