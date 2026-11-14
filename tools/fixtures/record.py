"""Record the golden HAR files in Chromium and Firefox.

    uv run python -m tools.fixtures.record            # every scenario, both browsers
    uv run python -m tools.fixtures.record auth cors  # just these
    BROWSERS=firefox uv run python -m tools.fixtures.record

Windows Smart App Control can block Playwright's Firefox build; record it in the
official container instead:

    docker run --rm -v "$PWD:/w" -w /w -e BROWSERS=firefox       mcr.microsoft.com/playwright/python:v1.65.2-noble       sh -c "pip install -q cryptography && python -m tools.fixtures.record"

The files land in tests/golden/hars/<browser>/<scenario>.har. Re-recording changes
timestamps and tokens, never the findings: tests/golden checks the findings.
The `network` scenario needs internet access (it visits expired.badssl.com).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from tools.fixtures.fault_server import APP, SCENARIOS, SHOP, reset, serve

OUT = Path(__file__).resolve().parents[2] / "tests" / "golden" / "hars"
HOSTS = "app.test,api.test,shop.test,cdn.test"


def record(names: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        servers = serve(Path(tmp))
        try:
            with sync_playwright() as p:
                launchers = {
                    "chromium": lambda: p.chromium.launch(
                        args=["--host-resolver-rules=MAP *.test 127.0.0.1"]
                    ),
                    "firefox": lambda: p.firefox.launch(
                        firefox_user_prefs={
                            "network.dns.localDomains": HOSTS,
                            "security.mixed_content.upgrade_display_content": False,
                        }
                    ),
                }
                wanted = os.environ.get("BROWSERS", "chromium,firefox").split(",")
                for browser_name, launch in launchers.items():
                    if browser_name not in wanted:
                        continue
                    browser = launch()
                    (OUT / browser_name).mkdir(parents=True, exist_ok=True)
                    for name in names:
                        reset()
                        path = OUT / browser_name / f"{name}.har"
                        context = browser.new_context(
                            record_har_path=str(path),
                            record_har_content="embed",
                            # only shop.test's throwaway certificate
                            ignore_https_errors=name == "mixed-content",
                        )
                        page = context.new_page()
                        base = SHOP if name == "mixed-content" else APP
                        page.goto(f"{base}/scenario/{name}")
                        page.wait_for_function("window.done === true", timeout=60_000)
                        page.wait_for_timeout(300)
                        context.close()
                        print(f"recorded {browser_name}/{name}.har")
                    browser.close()
        finally:
            for s in servers:
                s.shutdown()


if __name__ == "__main__":
    record(sys.argv[1:] or list(SCENARIOS))
