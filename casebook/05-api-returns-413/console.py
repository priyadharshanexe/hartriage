"""The customer's back-office "resend order" page, recorded as a HAR.

It runs in a browser on the Relay dashboard's origin and calls the events API with
the customer's API key, the way their admin tool does. One small order, then the
big wholesale order that fails.

    API_KEY=... python console.py http://localhost:8181 customer-console.har
"""

from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

SCRIPT = """
async ([key, lines]) => {
  const order = (id, n) => ({
    type: "order.created",
    payload: {
      order_id: id,
      customer: { name: "Wholesale Customer Ltd", tier: "gold" },
      lines: Array.from({ length: n }, (_, i) => ({
        sku: `SKU-${String(i).padStart(6, "0")}`, qty: 1 + (i % 9), unit_price: 1299,
        description: "Stainless steel fitting, 22 mm, compression, pack of 10, with fixing kit",
      })),
    },
  });
  const send = (body) => fetch("/v1/events", {
    method: "POST",
    headers: { "Authorization": "Bearer " + key, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.status);
  return [await send(order(5001, 20)), await send(order(5002, lines))];
}
"""


def main(base: str, out: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(record_har_path=out, record_har_content="embed")
        page = context.new_page()
        page.goto(base)
        statuses = page.evaluate(SCRIPT, [os.environ["API_KEY"], int(os.environ.get("LINES", "2500"))])
        print("statuses:", statuses)
        context.close()
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
