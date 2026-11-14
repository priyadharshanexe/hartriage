# 07 · "Event API is timing out"

**Product:** Relay events API · **Severity:** critical, ingestion down for everyone for about a minute · **Tools:** client log, request ids, Relay API logs, `pg_stat_activity`, Prometheus metrics, SQL

## Symptom (in the customer's words)

> Between 12:48 and 12:49 every call to `POST /v1/events` either hung until our 40-second timeout or came back 500 after 30 seconds. Request ids below. It recovered by itself. Did we lose events? Our integration retries on failure. Did we create duplicates?

## Environment

- Customer integration: 40 concurrent `POST /v1/events`, 40 s client timeout ([load.py](load.py))
- Relay [Project 1](https://github.com/priyadharshanexe/relay) at `f43ea2f`, database pool at its default: 10 connections plus 10 overflow, 30 s wait for a free connection
- The trigger: a one-off backfill script on our side took a `SHARE` lock on the `events` table for 70 s

## Reproduction

```bash
../relay/up.sh
./reproduce.sh
```

Full run: [reproduce-output.txt](reproduce-output.txt).

## Evidence

**1. The customer's view:** 40 requests, **20 × HTTP 500 after 30.1 s** and **20 × client timeout at 40 s**. Before and after the incident, 20 concurrent requests all returned `201` in milliseconds.

**2. One of their request ids, in our API log:**

```
2026-11-14T12:48:42Z http.unhandled_error 27eabaf82ab04525b7cf74c6cfd44f8c
  sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 30.00
```

The 500s never reached the database: they waited 30 s for a free connection and gave up.

**3. The database during the incident** ([queries.sql](queries.sql)):

```
 state  | wait_event_type | wait_event | count
 active | Lock            | relation   |    20
 active | Timeout         | PgSleep    |     1

  pid  | running_for | blocking_query                                                        | sessions_waiting
 58237 | 00:00:14    | BEGIN; LOCK TABLE events IN SHARE MODE; SELECT pg_sleep(70); COMMIT; |               20
```

All 20 of the API's connections were inserting into `events` and waiting on one lock held by the backfill. With the pool empty, every other request queued for a connection. `GET /readyz` answered **503 in 2 s**, so the health check saw it at once.

**4. Metrics:** the `POST /v1/events` latency histogram has 80 requests above the 10 s bucket across the two runs, after hundreds below 250 ms. An alert on "p99 over 5 s" would have fired within a minute.

**5. Were events lost or duplicated?** Requests the client gave up on were still waiting on the lock, and completed when it was released:

```
events per transaction start time (order ids 9000–9039, second run)
 12:48:11–12 | 20      ← the 20 requests that hit the client's 40 s timeout
```

So: **nothing was lost**; the 20 requests that returned 500 created nothing; and the 20 that timed out on the client side **did create events**. If the integration retried those, it created duplicates.

## Root cause

A maintenance script took a table lock on `events` and held it for 70 s. Every ingestion request waited for that lock while holding one of the API's 20 database connections. Once all 20 were taken, new requests waited 30 s for a connection and failed with 500. The customer's integration then retried requests that had in fact succeeded later.

## Fix

Immediate: the lock was released when the backfill finished. Had it been longer, `SELECT pg_terminate_backend(<pid>)` on the blocking session (query 2 gives the pid) ends it at once.

For the customer: send an `Idempotency-Key` header (Relay supports it). A retry of a request that did succeed then returns the original event instead of creating a second one. We identify the duplicates from this window for them (query below) so they can decide which to ignore.

## Verification

After the backfill ended, 20 concurrent events again returned `201` in milliseconds.

## Reply to the customer

> Hi Riley,
>
> I'm sorry about the disruption. Between 12:48:12 and 12:49:22 UTC a maintenance job on our side locked the table that stores incoming events. Your requests queued behind it: the ones that came back with 500 (for example `27eabaf8…`) were never stored, so retrying them was correct. The ones your integration timed out on at 40 s *were* stored about 30 seconds later, once the lock was released. If you retried those, the events exist twice; I've attached the list of event ids from that window.
>
> Two things will stop this from affecting you again: on our side, maintenance jobs now have a lock timeout, and we've added an alert on slow ingestion. On your side, sending an `Idempotency-Key` header with each event (your order id works well) means a retry can never create a duplicate: we return the original event instead.

## KB article

New article for Relay's knowledge base:

> **Events API returns 500 after 30 s or times out**
> Usually an incident on our side: check the status page. Requests that returned 500 were not stored; retry them. Requests your client timed out on may have been stored. Use an `Idempotency-Key` so retries are always safe.

## Prevention

- **Operations:** run maintenance with `SET lock_timeout = '2s'` and `statement_timeout`, and backfill in small batches without table locks.
- **Product (Relay):** fail fast and clearly when the pool is exhausted: a `503` with `Retry-After` after a few seconds, instead of a 500 after 30. Set a database `statement_timeout` for API requests below the pool timeout.
- **Monitoring:** alert on events API p99 latency and on connections waiting on locks (`pg_stat_activity`), not only on errors.
- **Docs:** recommend `Idempotency-Key` in the events API quick start, not just in the reference.
