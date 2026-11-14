# 05 · "API returns 413"

**Product:** Relay events API · **Severity:** medium, one order type fails, the rest work · **Tools:** HAR Triage, Relay API logs (by request id), payload measurement

## Symptom (in the customer's words)

> Our back-office tool resends orders to Relay. Normal orders work, but our big wholesale orders fail with "413". HAR attached. Can you raise the limit for us?

## Environment

- Customer's admin page calling `POST /v1/events` from the browser with their API key (recorded as a HAR by [console.py](console.py))
- Relay [Project 1](https://github.com/priyadharshanexe/relay) at `f43ea2f`, `RELAY_MAX_EVENT_BYTES` at its default of 262,144 bytes (256 KB)

## Reproduction

```bash
../relay/up.sh
./reproduce.sh     # records the HAR, runs HAR Triage on it, looks up the request id, measures the bodies
```

Full run: [reproduce-output.txt](reproduce-output.txt).

## Evidence

**1. First, the HAR itself was a risk.** The file the customer attached carried their **live API key** in the `Authorization` header of every events call. HAR Triage replaced it before anything was stored:

```
original HAR:  "Bearer rly_test_8mW… (live key)
redacted copy: "Bearer [REDACTED:99aac434]
```

Only the [redacted copy](customer-console.redacted.har) is kept with this case. The original never leaves the reproduction folder.

**2. HAR Triage's summary** ([hartriage-summary.md](hartriage-summary.md)):

> **First failure:** Request #7: POST http://localhost:8181/v1/events → 413 Request Entity Too Large
> **Likely cause:** localhost refused the request body as too large (332 KB sent).
> *[info] Sign-in check before signing in: 2 requests to localhost (#4, #6)*

The two 401s are the dashboard checking for a session on page load, before the API key is used. The first version of HAR Triage reported one of them as the first failure, which would have sent an agent down the wrong path. This case is why it now recognises sign-in checks (see *Prevention*).

**3. The browser did not record the 413's body.** The server answers before the upload has finished, and Chromium then records no response body. The request id is in the response headers, though, so Relay's API log has the rest:

```
{'timestamp': '2026-11-14T09:35:21Z', 'method': 'POST', 'path': '/v1/events', 'status': 413,
 'duration_ms': 5.2, 'request_id': '27adf4e83da64589bf1ce62a26663313'}
```

The response itself is `{"code": "payload_too_large", "message": "The request body may be at most 262144 bytes.", "details": {"limit": 262144}}`. 5 ms means Relay refused it while reading, without parsing or storing anything.

**4. Measured against the limit:**

```
201     2,841 bytes  (1% of the 262,144-byte limit)      normal order, 20 lines
413   340,121 bytes  (130% of the 262,144-byte limit)    wholesale order, 2,500 lines
```

## Root cause

The wholesale order event embeds all 2,500 order lines (description, SKU, price), producing a 340 KB request. Relay accepts events up to 256 KB and refuses larger ones with `413 payload_too_large`. Normal orders are far below the limit, which is why only wholesale orders fail.

## Fix

Raising the limit would only move the problem: every receiver would then have to accept and process multi-megabyte webhooks, and their limits are often lower than ours. The robust fix is on the customer's side, in either of two ways:

1. **Thin events** (recommended): send identifiers and a link, and let the receiver fetch the details (`{"order_id": 5002, "line_count": 2500, "detail_url": "…"}`).
2. **Split** large orders into several `order.lines_added` events of a few hundred lines each.

## Verification

The same order sent as a thin event:

```
HTTP 201, 131 bytes
```

## Reply to the customer

> Hi Morgan,
>
> Thanks for the HAR file. One important thing first: it contained your live Relay API key. Our tool removed it before the file was stored, but the file did travel by email, so please **rotate that key** under *API keys* in the dashboard (it takes a minute and you can run both keys during the switch).
>
> About the 413: the wholesale order you resent was 340 KB, and Relay accepts events of up to 256 KB. Your regular orders are around 3 KB, which is why only the big ones fail.
>
> Rather than a higher limit (your own receivers would then need to accept very large webhooks too), we recommend sending just the order id and a link to fetch the details, for example `{"order_id": 5002, "detail_url": "https://…/orders/5002"}`. If your receiver needs the lines in the event, splitting them into batches of a few hundred works as well. I tested the first option against your account and it went through straight away.

## KB article

[R008: Payload too large](../../kb/R008-payload.md), 413 section, which links Relay's 256 KB limit and the thin-event pattern.

## Prevention

- **HAR Triage (done):** recognise sign-in checks (a 401 without credentials on a session endpoint, or before the first authenticated success) and report them as *info*, not as the first failure. Added with tests in commit "Recognise sign-in checks…".
- **Product (Relay):** return the limit and the received size in the 413 body (`"limit": 262144, "received": 340121`), so the customer's own logs explain it.
- **Docs:** state the 256 KB limit on the events API reference page, next to the thin-event recommendation.
- **Security:** API keys in a browser-based tool are a risk on their own. The customer's admin page should call their own backend, which holds the key.
