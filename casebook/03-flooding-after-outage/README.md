# 03 · "You're flooding us after an outage"

**Product:** Relay · **Severity:** medium, deliveries slow and noisy, two lost to the dead-letter queue · **Tools:** attempt log, stored response headers, SQL, receiver log

## Symptom (in the customer's words)

> Our API was down for maintenance this morning. The moment it came back, Relay hammered it: our gateway logged hundreds of 429s from your IPs. Please slow down. And why are some orders still not here 15 minutes later?

## Environment

- Customer receiver behind a gateway that allows **2 requests/second** and answers the rest with `429` and `Retry-After: 30` ([receiver.py](receiver.py))
- Relay [Project 1](https://github.com/priyadharshanexe/relay) at `f43ea2f` with its defaults: circuit breaker opens after 5 failures in a row, 60 s cool-down; retry schedule shortened to `[0, 5, 15, 30, 60]` s for the reproduction
- 30 `order.paid` events sent while the receiver was down

## Reproduction

```bash
../relay/up.sh
./reproduce.sh     # about 20 minutes: that slowness is the case
```

Full run: [reproduce-output.txt](reproduce-output.txt).

## Evidence

**1. During the outage**, attempts failed with `connect` errors and were scheduled for retry. Nothing was lost.

**2. When the receiver came back, retries arrived in bursts.** Busiest seconds ([queries.sql](queries.sql), query 3):

```
         second         | requests | got_429
 2026-11-14 09:47:40+00 |       17 |      15
 2026-11-14 09:49:52+00 |       10 |       8
 2026-11-14 09:45:39+00 |        9 |       7
```

Every retry that came due at the same moment was sent at once: 9 to 17 requests in one second, against a limit of 2.

**3. Relay did honour `Retry-After`.** For each 429, the receiver asked for 30 s; Relay never retried sooner (query 2: the shortest wait was 30 s, most were 66 s, some 197 s). So the customer's gateway saw bursts, not a continuous hammering.

**4. But the recovery was slow, and two deliveries died.** Totals for the backlog: **58 × 429, 28 × 200, 18 × connect**. It took **832 s** after the outage ended, and 2 of the 30 deliveries were still not delivered: they used up their attempts and went to the dead-letter queue. The waits of 60–200 s are Relay's circuit breaker: each burst produced more than 5 failures in a row (the 429s), the breaker opened for 60 s, one probe went through, the breaker closed, and the next burst repeated the cycle. Roughly 3 deliveries got through per minute.

## Root cause

Two things combined:

1. **No pacing for this endpoint.** Relay sends every due retry at once. After an outage, the whole backlog is due together, which a 2-requests-per-second gateway can't absorb.
2. **The circuit breaker counts 429 as a failure.** A 429 means "slow down", not "I'm broken". Treating it as failure opened the breaker repeatedly, which stretched a 15-second job into 14 minutes and ran deliveries out of attempts.

## Fix

Immediately, for this customer: set the endpoint's rate limit to their gateway's capacity (`rate_limit_per_sec: 2`, a setting Relay already has), and replay the two dead deliveries.

## Verification

With the rate limit set, 30 new events: **30 attempts, 30 × 200, zero 429s**, done in 168 s.

## Reply to the customer

> Hi Jordan,
>
> Sorry for the noise this morning. Here's what happened: while your API was down, 30 orders queued up on our side. When it came back, the retries were all due at once, and we sent up to 17 in the same second. Your gateway allows 2 per second, so most got 429. We did wait the 30 seconds your gateway asked for each time, but the bursts repeated and recovery took about 14 minutes; 2 orders ran out of retries.
>
> I've done two things: your endpoint is now limited to 2 deliveries per second, matching your gateway, and I've replayed the 2 undelivered orders, which have arrived. In a test with the limit on, 30 orders went through with no 429s at all. If you raise your gateway's limit, tell us and we'll raise ours to match.

## KB article

[R007: Rate limiting](../../kb/R007-rate-limit.md) explains `Retry-After` and backoff from the browser side; the same reasoning applies here with the roles reversed (Relay is the client).

## Prevention

- **Product (Relay):** don't count a 429 with `Retry-After` as a circuit-breaker failure. It is back-pressure, not an outage. Filed for engineering with this reproduction attached.
- **Product (Relay):** spread retries that come due together (jitter across the window), and learn a rate from `X-RateLimit-Limit` when the receiver sends one.
- **Support:** when a customer reports an outage on their side, suggest setting an endpoint rate limit *before* they come back up.
