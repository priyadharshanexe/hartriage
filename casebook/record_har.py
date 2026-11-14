"""Record a HAR the way a customer would: open a URL in Chromium with recording on.

    uv run python casebook/record_har.py https://expired.badssl.com/ casebook/01-.../endpoint-check.har
"""

from __future__ import annotations

import sys

from playwright.sync_api import Error, sync_playwright


def main(url: str, out: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(record_har_path=out, record_har_content="embed")
        page = context.new_page()
        try:
            page.goto(url, timeout=20_000)
        except Error as exc:  # the navigation failing is the point
            print(f"navigation failed: {str(exc).splitlines()[0]}")
        context.close()
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
