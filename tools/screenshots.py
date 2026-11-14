"""Capture the README screenshots from a running stack (docker compose up --build).

    uv run python -m tools.screenshots

Registers a throwaway account, uploads the sample HAR, connects the fake helpdesk,
tags a ticket, and saves PNGs to docs/screenshots/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

WEB = "http://localhost:8280"
API = "http://localhost:8200"
FAKE = "http://localhost:8290"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
SAMPLE = ROOT / "tools" / "fixtures" / "samples" / "checkout-broken.har"


def shot(page: Page, name: str, full: bool = False) -> None:
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print(f"saved {name}.png")


def before_after(page: Page) -> None:
    """A side-by-side of one request before and after redaction."""
    raw = json.loads(SAMPLE.read_text(encoding="utf-8"))["log"]["entries"][2]["request"]
    with httpx.Client(base_url=API, timeout=30) as c:
        token = c.post("/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()[
            "access_token"
        ]
        items = c.get("/v1/analyses", headers={"Authorization": f"Bearer {token}"}).json()["items"]
        detail = c.get(
            f"/v1/analyses/{items[-1]['id']}/entries/3",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
    clean = detail["entry"]["request"]

    def block(title: str, request: dict[str, object], tone: str) -> str:
        headers = "".join(
            f"<div><span class=k>{h['name']}:</span> {h['value']}</div>"  # type: ignore[index]
            for h in request["headers"]  # type: ignore[attr-defined]
            if str(h["name"]).lower()
            in ("authorization", "cookie", "referer", "user-agent", "accept")  # type: ignore[index]
        )
        return f"<section class={tone}><h2>{title}</h2><div class=url>{request['method']} {request['url']}</div>{headers}</section>"

    html = f"""<!doctype html><meta charset=utf-8><style>
    body{{font:14px ui-monospace,Consolas,monospace;margin:0;padding:24px;background:#f8fafc;display:grid;grid-template-columns:1fr 1fr;gap:16px}}
    section{{background:white;border-radius:8px;padding:16px;border:2px solid}} .raw{{border-color:#f87171}} .clean{{border-color:#14b8a6}}
    h2{{font:600 16px system-ui;margin:0 0 8px}} .k{{color:#64748b}} div{{word-break:break-all;margin:4px 0}} .url{{font-weight:600}}
    </style>{block("Before: what the customer's browser recorded", raw, "raw")}{block("After: what HAR Triage stores", clean, "clean")}"""
    page.set_content(
        html.replace("[REDACTED:", "<mark>[REDACTED:").replace("]</div>", "]</mark></div>")
    )
    page.set_viewport_size({"width": 1400, "height": 420})
    shot(page, "before-after-redaction")


EMAIL = f"screens-{int(time.time())}@example.com"
PASSWORD = "screenshot password 1"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(f"{WEB}/register")
        page.get_by_label("Your name").fill("Ada Agent")
        page.get_by_label("Work email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_label("Team or company name").fill("Acme Support")
        page.get_by_role("button", name="Create organisation").click()
        page.get_by_role("heading", name="Analyse a HAR file").wait_for()
        shot(page, "upload")

        page.get_by_test_id("file-input").set_input_files(str(SAMPLE))
        page.wait_for_url("**/analyses/*")
        page.get_by_test_id("likely-cause").wait_for()
        shot(page, "analysis-summary")
        page.get_by_test_id("finding").filter(has_text="R002").get_by_role(
            "button", name="Show"
        ).click()
        page.locator("#requests").scroll_into_view_if_needed()
        page.get_by_role("complementary", name="Request 3").wait_for()
        page.wait_for_timeout(600)
        page.evaluate("document.getElementById('requests').scrollIntoView()")
        shot(page, "waterfall-and-request")
        page.evaluate("window.scrollTo(0, 0)")
        page.get_by_text("Findings (").scroll_into_view_if_needed()
        shot(page, "findings")

        page.goto(f"{WEB}/kb/R002-auth")
        page.get_by_role(
            "heading", name="R002 — Authentication and permission errors (401 / 403)"
        ).wait_for()
        shot(page, "kb-article")

        # Helpdesk: connect the fake Zendesk, tag a ticket, read the note.
        page.goto(f"{WEB}/connections")
        page.get_by_role("button", name="Add a connection").click()
        page.get_by_label("Subdomain").fill("acme")
        page.get_by_label("Agent email").fill("agent@acme.test")
        page.get_by_label("API token").fill("demo-token")
        page.get_by_label("Webhook signing secret").fill("demo-signing-secret")
        page.get_by_role("button", name="Connect").click()
        page.get_by_text("Webhook URL").first.wait_for()
        webhook = page.locator("code").first.inner_text()
        with httpx.Client(base_url=FAKE, timeout=60) as fake:
            tid = fake.post(
                "/_admin/tickets",
                json={
                    "platform": "zendesk",
                    "account": "acme",
                    "subject": "Checkout page says I'm signed out",
                    "attachments": [{"filename": "checkout.har", "sample": SAMPLE.name}],
                },
            ).json()["id"]
            fake.post(
                f"/_admin/tickets/zendesk/acme/{tid}/tag",
                json={"webhook_url": webhook, "secret": "demo-signing-secret", "repeat": 2},
            )
            for _ in range(60):
                if "har_analyzed" in fake.get(f"/_admin/tickets/zendesk/acme/{tid}").json()["tags"]:
                    break
                time.sleep(0.5)
        page.reload()
        page.get_by_text("Setup steps").click()
        shot(page, "connections")
        page.goto(FAKE)
        page.locator("details").last.click()
        shot(page, "helpdesk-private-note", full=True)

        page.goto(f"{WEB}/analyses")
        page.get_by_role("heading", name="History").wait_for()
        shot(page, "history")
        before_after(page)
        browser.close()


if __name__ == "__main__":
    main()
