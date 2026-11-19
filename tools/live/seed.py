"""Seed the live trial helpdesks with tickets that carry HAR files.

    uv run python -m tools.live.seed freshdesk|zendesk

Requesters are fake example.com addresses, so no real person gets mail. Ticket ids
are kept in tools/live/state.json (gitignored).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from tools.live.env import ROOT, load

STATE = ROOT / "tools" / "live" / "state.json"
GEN = ROOT / "tools" / "live" / "generated"
HARS = ROOT / "tests" / "golden" / "hars"
# A 1x1 PNG, for "a non-HAR attachment".
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def state() -> dict[str, Any]:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save(data: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def big_har(target_bytes: int) -> Path:
    """A real Chromium recording padded with extra entries until it is near the limit."""
    GEN.mkdir(parents=True, exist_ok=True)
    path = GEN / f"big-{target_bytes // (1024 * 1024)}mb.har"
    if path.exists():
        return path
    har = json.loads((HARS / "chromium" / "checkout-story.har").read_text(encoding="utf-8"))
    entries = har["log"]["entries"]
    template = json.loads(json.dumps(entries[0]))
    template["response"]["content"]["text"] = "x" * 200_000
    size = len(json.dumps(har))
    i = 0
    while size < target_bytes:
        e = json.loads(json.dumps(template))
        e["request"]["url"] = f"{e['request']['url']}?page={i}"
        entries.insert(1, e)
        size += 200_400
        i += 1
    path.write_text(json.dumps(har), encoding="utf-8")
    return path


def har(browser: str, name: str) -> tuple[str, bytes]:
    return f"{browser}-{name}.har", (HARS / browser / f"{name}.har").read_bytes()


# ------------------------------------------------------------------ Freshdesk


def freshdesk() -> None:
    e = load()
    dom = e["FRESHDESK_DOMAIN"].replace("https://", "").split(".freshdesk.com")[0]
    c = httpx.Client(
        base_url=f"https://{dom}.freshdesk.com", auth=(e["FRESHDESK_API_KEY"], "X"), timeout=120
    )
    s = state()
    tickets = s.setdefault("freshdesk", {})

    def create(key: str, subject: str, files: list[tuple[str, bytes]], email: str) -> str:
        if key in tickets:
            return str(tickets[key])
        data = {
            "subject": subject,
            "description": f"<p>{subject}. Test ticket for HAR Triage live testing.</p>",
            "email": email,
            "status": "2",
            "priority": "1",
        }
        if files:
            r = c.post(
                "/api/v2/tickets",
                data=data,
                files=[
                    (
                        "attachments[]",
                        (n, b, "application/json" if n.endswith(".har") else "image/png"),
                    )
                    for n, b in files
                ],
            )
        else:
            r = c.post("/api/v2/tickets", json={**data, "status": 2, "priority": 1})
        print(key, r.status_code, r.text[:200] if r.status_code >= 300 else "")
        r.raise_for_status()
        tickets[key] = str(r.json()["id"])
        save(s)
        return str(tickets[key])

    create(
        "single",
        "Checkout says I am signed out (Chromium HAR)",
        [har("chromium", "checkout-story")],
        "har.tester+fd1@example.com",
    )
    multi = create(
        "multi",
        "Several problems, two HAR files and a screenshot",
        [har("chromium", "auth"), har("firefox", "cors"), ("screenshot.png", PNG)],
        "har.tester+fd2@example.com",
    )
    if "multi_note" not in tickets:
        name, body = har("firefox", "network")
        r = c.post(
            f"/api/v2/tickets/{multi}/notes",
            data={"body": "<p>Customer sent another recording.</p>", "private": "true"},
            files=[("attachments[]", (name, body, "application/json"))],
        )
        print("multi note", r.status_code)
        r.raise_for_status()
        tickets["multi_note"] = str(r.json()["id"])
        save(s)
    big = big_har(18 * 1024 * 1024)
    create(
        "big",
        "Large HAR near the 20 MB attachment limit",
        [(big.name, big.read_bytes())],
        "har.tester+fd3@example.com",
    )
    create("empty", "No attachment at all", [], "har.tester+fd4@example.com")
    print(json.dumps(tickets, indent=1))


if __name__ == "__main__":
    {"freshdesk": freshdesk}[sys.argv[1]]()
