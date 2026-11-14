#!/usr/bin/env bash
# Case 05: "API returns 413" — an order.created event over the 256 KB limit.
# Needs ../relay/up.sh and the HAR Triage dev environment (uv sync) for Playwright.
cd "$(dirname "$0")"
. ../relay/lib.sh
ROOT="$(cd ../.. && pwd)"
if command -v uv >/dev/null 2>&1; then UV=(uv); else UV=("$PY" -m uv); fi

say "The customer's admin page sends two orders through the events API (recorded as a HAR)"
relay_setup case05
(cd "$ROOT" && API_KEY="$API_KEY" "${UV[@]}" run python casebook/05-api-returns-413/console.py http://localhost:8181 casebook/05-api-returns-413/customer-console.har)

say "HAR Triage on the HAR the customer attached"
(cd "$ROOT" && "${UV[@]}" run hartriage analyze casebook/05-api-returns-413/customer-console.har --redacted-out casebook/05-api-returns-413/customer-console.redacted.har) | tee hartriage-summary.md

say "The API key in the original HAR, and in the redacted copy"
grep -o '"Bearer [^"]\{0,24\}' customer-console.har | head -1 | sed 's/\(Bearer .\{12\}\).*/\1… (live key)/'
grep -o '"Bearer [^"]*' customer-console.redacted.har | head -1

say "The request id from the HAR, looked up in Relay's API log"
rid="$(grep -o '"[Xx]-[Rr]equest-[Ii][Dd]","value":"[0-9a-f]*"' customer-console.redacted.har | tail -1 | grep -o '[0-9a-f]\{32\}')"
docker logs relay-casebook-api-1 2>&1 | grep "$rid" | "$PY" -c "import json,sys; [print({k: json.loads(l)[k] for k in ('timestamp','method','path','status','duration_ms','request_id')}) for l in sys.stdin]"

say "Measure the body against the limit"
"$PY" - <<'PY'
import json
har = json.load(open("customer-console.har", encoding="utf-8"))
for e in har["log"]["entries"]:
    if e["request"]["url"].endswith("/v1/events"):
        size = len((e["request"].get("postData") or {}).get("text", "").encode())
        print(f'{e["response"]["status"]}  {size:>8,} bytes  ({size / 262144:.0%} of the 262,144-byte limit)')
PY

say "Verification: the same order sent as a thin event (ids, not line items)"
curl -sS -o /dev/null -w 'HTTP %{http_code}, %{size_upload} bytes\n' \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  -X POST "$RELAY_URL/v1/events" \
  -d '{"type":"order.created","payload":{"order_id": 5002, "line_count": 2500, "detail_url": "https://shop.example.com/api/orders/5002"}}'
