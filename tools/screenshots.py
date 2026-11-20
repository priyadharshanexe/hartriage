"""Capture the README screenshots from a running stack (docker compose up --build).

    uv run --with pillow python -m tools.screenshots

Registers a throwaway account, uploads the sample HAR, connects the fake helpdesk
(the made-up "acme" account, never a real one), tags a ticket, and saves PNGs and
the demo GIF to docs/screenshots/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

WEB = "http://127.0.0.1:8280"
API = "http://127.0.0.1:8200"
FAKE = "http://127.0.0.1:8290"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
SAMPLE = ROOT / "tools" / "fixtures" / "samples" / "checkout-broken.har"


FRAMES: list[tuple[Path, int]] = []


def shot(page: Page, name: str, full: bool = False) -> None:
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print(f"saved {name}.png")


def frame(page: Page, ms: int = 1400) -> None:
    """One frame of the demo GIF, shown for `ms` milliseconds."""
    path = OUT / f".frame-{len(FRAMES):02d}.png"
    page.screenshot(path=str(path))
    FRAMES.append((path, ms))


def write_gif() -> None:
    from PIL import Image  # uv run --with pillow

    images = [Image.open(p).convert("RGB").resize((1120, 720), Image.LANCZOS) for p, _ in FRAMES]
    palette = images[0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    frames[0].save(
        OUT / "demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[ms for _, ms in FRAMES],
        loop=0,
        optimize=True,
    )
    for p, _ in FRAMES:
        p.unlink()
    print("saved demo.gif")


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
    body{{font:14px "IBM Plex Mono",ui-monospace,Consolas,monospace;margin:0;padding:24px;background:#f2eee5;color:#1b1a17;display:grid;grid-template-columns:1fr 1fr;gap:16px}}
    section{{background:#fbf9f4;padding:16px;border:1px solid #d9d2c3;border-top:4px solid}} .raw{{border-top-color:#c8352a}} .clean{{border-top-color:#1b1a17}}
    h2{{font:600 13px system-ui;letter-spacing:.12em;text-transform:uppercase;margin:0 0 10px;color:#6e695d}} .k{{color:#6e695d}} div{{overflow-wrap:anywhere;margin:4px 0}} .url{{font-weight:600}}
    mark{{background:#1b1a17;color:#b8b19f;padding:1px 6px}}
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
        page.goto(f"{WEB}/login")
        page.get_by_role("heading", name="Sign in").wait_for()
        page.wait_for_timeout(2500)
        frame(page, 2200)
        page.goto(f"{WEB}/register")
        page.get_by_label("Your name").fill("Ada Agent")
        page.get_by_label("Work email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_label("Team or company name").fill("Acme Support")
        page.get_by_role("button", name="Create organisation").click()
        page.get_by_role("heading", name="Analyse a HAR file").wait_for()
        shot(page, "upload")
        frame(page)

        page.get_by_test_id("file-input").set_input_files(str(SAMPLE))
        for ms in (500, 900, 900, 1200):
            page.wait_for_timeout(ms)
            frame(page, 700)
        page.wait_for_url("**/analyses/*")
        page.get_by_test_id("likely-cause").wait_for()
        page.wait_for_timeout(1500)
        shot(page, "analysis-summary")
        frame(page, 2600)
        page.get_by_test_id("finding").filter(has_text="R002").get_by_role(
            "button", name="Show"
        ).click()
        page.get_by_role("complementary", name="Request 3").wait_for()
        page.wait_for_timeout(600)
        shot(page, "waterfall-and-request")
        frame(page, 2200)
        page.keyboard.press("Escape")
        page.evaluate("document.getElementById('requests').scrollIntoView()")
        shot(page, "waterfall")
        page.evaluate("document.getElementById('findings-heading').scrollIntoView()")
        shot(page, "findings")
        frame(page, 1800)

        page.goto(f"{WEB}/kb/R002-auth")
        page.get_by_role(
            "heading", name="R002 — Authentication and permission errors (401 / 403)"
        ).wait_for()
        shot(page, "kb-article")

        # Helpdesk: connect the fake Zendesk, tag a ticket, read the note.
        page.goto(f"{WEB}/connections")
        page.get_by_role("button", name="Add a connection").click()
        page.get_by_label("Subdomain").fill("acme")
        page.get_by_label("Sign in with").select_option("api_token")
        page.get_by_label("Agent email").fill("agent@acme.test")
        page.get_by_label("API token").fill("demo-token")
        page.get_by_label("Webhook signing secret (optional now)").fill("demo-signing-secret")
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
        frame(page, 2600)

        page.goto(f"{WEB}/analyses")
        page.get_by_role("heading", name="Files").wait_for()
        page.wait_for_timeout(800)
        shot(page, "files")
        frame(page, 2000)
        page.goto(f"{WEB}/settings")
        page.get_by_role("button", name="Save settings").wait_for()
        page.wait_for_timeout(1200)
        shot(page, "settings")
        frame(page, 2000)
        write_gif()
        before_after(page)
        browser.close()


if __name__ == "__main__":
    main()
