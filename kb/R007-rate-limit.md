# R007 — Rate limiting (429 Too Many Requests)

**What the tool found:** responses with status 429, meaning the client sent more requests than the API allows. The finding also reads:

- `Retry-After`: how long the server asked the client to wait, in seconds or as a date;
- `X-RateLimit-Limit`, `-Remaining`, `-Reset` (and the newer `RateLimit-*` headers): the limit and when it resets;
- **early retries**: requests to the same endpoint sent *before* `Retry-After` had passed. Those almost always get another 429 and keep the client locked out.

## Common causes

- **A retry loop without backoff.** The app retries immediately on failure, which turns one 429 into dozens. The "early retries" line in the evidence is the proof.
- **Many tabs, scripts or integrations sharing one API key**: each is within limits on its own, but not together.
- **A bulk job** (import, sync, migration) sending requests as fast as possible.
- **After an outage**, queued work flushes all at once. See casebook case 03.

## What to do

1. Read the limit from the evidence (for example "100 per window") and compare with the request rate in the waterfall.
2. If the client retried early, the fix is on the client: honour `Retry-After`, then back off exponentially with jitter (1 s, 2 s, 4 s… plus a random fraction).
3. If the customer genuinely needs more throughput, check their plan's limits and whether batching endpoints exist.

## Reply template

> Our API limits each key to 100 requests per minute. Your recording shows the integration sending a burst of requests and then retrying immediately after we asked it to wait 30 seconds, which kept it blocked. If the integration waits for the time given in the Retry-After header before retrying, it will recover on its own.

## Escalate when

429s arrive while the client is clearly under the documented limit, or `Retry-After` is missing or wrong.
