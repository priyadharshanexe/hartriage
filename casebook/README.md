# Casebook

Eight support cases against [Relay](https://github.com/priyadharshanexe/relay) (Project 1, a webhook delivery service), worked the way a real ticket is worked: the customer's words, a reproduction anyone can run, the evidence (attempt logs, SQL, logs, metrics, HAR files), the root cause, the fix, proof that it worked, and the reply to the customer.

Each case reads in about three minutes.

| # | The customer says | Root cause | Evidence used |
|---|---|---|---|
| [01](01-endpoint-stopped-receiving/) | "My endpoint stopped receiving webhooks" | The receiver's TLS certificate expired | Attempt log (`tls`), certificate check, HAR Triage on the customer's browser HAR |
| [02](02-signatures-fail-at-random/) | "Signature verification fails at random" | One of two receiver nodes has a clock 7 minutes slow | Stored response headers: outcome per node, each node's `Date` vs send time |
| [03](03-flooding-after-outage/) | "You're flooding us after an outage" | Retries due together hit a 2 req/s gateway; 429s tripped the circuit breaker | Requests per second, `Retry-After` vs actual waits, 14-minute recovery |
| [04](04-endpoint-never-called/) | "Our endpoint never gets called" | The hostname resolves to a non-public address, refused by the SSRF guard | 0 ms attempts, DNS from inside the worker |
| [05](05-api-returns-413/) | "API returns 413" | A 340 KB event against a 256 KB limit; the HAR also held a live API key | HAR Triage, request id → API log, payload measurement |
| [06](06-signatures-broke-after-rotation/) | "Signatures broke after we rotated the secret" | The new secret was never deployed; the 24 h overlap hid it | Secret expiry, audit log, signatures per attempt |
| [07](07-event-api-timing-out/) | "Event API is timing out" | A table lock emptied the database connection pool | `pg_stat_activity`, blocking query, API log by request id, metrics, late commits |
| [08](08-same-webhook-twice/) | "We received the same webhook twice" | A worker died mid-delivery; at-least-once delivery re-sent it | Receiver log, lease recovery in the worker log, attempt rows |

## Running the cases

```bash
./relay/up.sh          # a separate copy of Relay: API :8101, dashboard :8181, Postgres :5444
cd 01-endpoint-stopped-receiving && ./reproduce.sh
./relay/down.sh        # remove it again
```

`RELAY_DIR` points at a Relay checkout (default `../../webhook`). The scripts need `curl`, Docker and Python 3. Cases 01 and 04 need internet access. Case 05 uses this repo's `uv` environment (Playwright and the `hartriage` CLI). Retry schedules and the secret-rotation overlap are shortened in [relay/compose.override.yml](relay/compose.override.yml) so each case runs in minutes.

## What the cases fed back

Working these cases changed both projects:

- **HAR Triage:** case 05 showed the dashboard's normal sign-in checks being reported as the first failure. Sign-in checks are now recognised and reported as *info* ([R002](../kb/R002-auth.md)).
- **Relay, for engineering:** TLS errors without the reason (case 01), 429s counted as circuit-breaker failures (case 03), 500 after 30 s instead of a fast 503 when the pool is exhausted (case 07). Each case's *Prevention* section has the details.
