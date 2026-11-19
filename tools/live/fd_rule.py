"""Create (or replace) the optional Freshdesk "ticket updates" automation for HAR Triage.

    uv run python -m tools.live.fd_rule https://<tunnel>.trycloudflare.com

Tagging alone is handled by polling (Freshdesk does not fire this rule when only a tag
changes). The rule speeds things up when an agent tags a ticket and also changes a
field. The JSON below is what the Freshdesk UI saves, read back through the API; note
that "ticket_action: update" is only accepted for agent-performed rules (type 1).
"""

from __future__ import annotations

import sys

import httpx

from tools.live.env import load

NAME = "HAR Triage: analyse tagged tickets"


def client() -> httpx.Client:
    e = load()
    dom = e["FRESHDESK_DOMAIN"].replace("https://", "").split(".freshdesk.com")[0]
    return httpx.Client(
        base_url=f"https://{dom}.freshdesk.com", auth=(e["FRESHDESK_API_KEY"], "X"), timeout=30
    )


def rule(url: str, secret: str) -> dict[str, object]:
    return {
        "name": NAME,
        "position": 1,
        "active": True,
        "performer": {"type": 1},
        "events": [{"field_name": "ticket_action", "value": "update"}],
        "conditions": [
            {
                "name": "condition_set_1",
                "match_type": "any",
                "properties": [
                    {
                        "resource_type": "ticket",
                        "field_name": "tag_names",
                        "operator": "and",
                        "value": ["har_analyze"],
                    }
                ],
            }
        ],
        "actions": [
            {
                "field_name": "trigger_webhook",
                "request_type": "POST",
                "url": url,
                "content_type": "JSON",
                "content_layout": "advanced",
                "custom_headers": {"x-hartriage-secret": secret},
                "content": '{"ticket_id": {{ticket.id}}}',
            }
        ],
    }


def main() -> None:
    e = load()
    url = f"{sys.argv[1].rstrip('/')}/v1/webhooks/freshdesk/{e['FRESHDESK_CONNECTION_ID']}"
    secret = e["FRESHDESK_WEBHOOK_SECRET"]
    with client() as c:
        for existing in c.get("/api/v2/automations/4/rules").json():
            if existing.get("name") == NAME:
                c.delete(f"/api/v2/automations/4/rules/{existing['id']}").raise_for_status()
        r = c.post("/api/v2/automations/4/rules", json=rule(url, secret))
        print("create rule:", r.status_code, r.text[:300].replace(secret, "<secret>"))
        r.raise_for_status()


if __name__ == "__main__":
    main()
