"""Create the Zendesk webhook and trigger for HAR Triage, and store the webhook's
signing secret in the HAR Triage connection. Secrets are never printed.

    uv run python -m tools.live.zd_setup https://<tunnel>.trycloudflare.com
"""

from __future__ import annotations

import json
import sys

import httpx

from tools.live.env import load
from tools.live.setup_freshdesk import API

NAME = "HAR Triage (live tests)"


def zendesk() -> httpx.Client:
    e = load()
    base = f"https://{e['ZENDESK_SUBDOMAIN']}.zendesk.com"
    token = httpx.post(
        f"{base}/oauth/tokens",
        json={
            "grant_type": "client_credentials",
            "client_id": e["ZENDESK_OAUTH_CLIENT_ID"],
            "client_secret": e["ZENDESK_OAUTH_CLIENT_SECRET"],
            "scope": "read write",
        },
        timeout=30,
    )
    token.raise_for_status()
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=60,
    )


def main() -> None:
    e = load()
    url = f"{sys.argv[1].rstrip('/')}/v1/webhooks/zendesk/{e['ZENDESK_CONNECTION_ID']}"
    with zendesk() as z:
        for hook in z.get(
            "/api/v2/webhooks", params={"filter[name_contains]": "HAR Triage"}
        ).json()["webhooks"]:
            print(
                "deleting old webhook",
                hook["id"],
                z.delete(f"/api/v2/webhooks/{hook['id']}").status_code,
            )
        for trig in (
            z.get("/api/v2/triggers/search.json", params={"query": "HAR Triage"})
            .json()
            .get("triggers", [])
        ):
            print(
                "deleting old trigger",
                trig["id"],
                z.delete(f"/api/v2/triggers/{trig['id']}.json").status_code,
            )
        r = z.post(
            "/api/v2/webhooks",
            json={
                "webhook": {
                    "name": NAME,
                    "endpoint": url,
                    "http_method": "POST",
                    "request_format": "json",
                    "status": "active",
                    "subscriptions": ["conditional_ticket_events"],
                }
            },
        )
        print("webhook:", r.status_code, r.text[:300] if r.status_code >= 300 else "")
        r.raise_for_status()
        hook_id = r.json()["webhook"]["id"]
        secret = z.get(f"/api/v2/webhooks/{hook_id}/signing_secret").json()["signing_secret"][
            "secret"
        ]
        r = z.post(
            "/api/v2/triggers.json",
            json={
                "trigger": {
                    "title": NAME,
                    "conditions": {
                        "all": [
                            {
                                "field": "current_tags",
                                "operator": "includes",
                                "value": "har_analyze",
                            }
                        ]
                    },
                    "actions": [
                        {
                            "field": "notification_webhook",
                            "value": [hook_id, json.dumps({"ticket_id": "{{ticket.id}}"})],
                        }
                    ],
                }
            },
        )
        print(
            "trigger:",
            r.status_code,
            r.text[:300] if r.status_code >= 300 else r.json()["trigger"]["id"],
        )
        r.raise_for_status()
    with httpx.Client(base_url=API, timeout=60) as c:
        token = c.post(
            "/v1/auth/login",
            json={"email": e["HARTRIAGE_LIVE_EMAIL"], "password": e["HARTRIAGE_LIVE_PASSWORD"]},
        ).json()["access_token"]
        r = c.patch(
            f"/v1/connections/{e['ZENDESK_CONNECTION_ID']}",
            headers={"Authorization": f"Bearer {token}"},
            json={"signing_secret": secret},
        )
        print(
            "signing secret stored:",
            r.status_code,
            "needs_signing_secret =",
            r.json()["needs_signing_secret"],
        )


if __name__ == "__main__":
    main()
