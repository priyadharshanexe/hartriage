# 02 · "Signature verification fails at random"

**Product:** Relay · **Severity:** medium, deliveries arrive late but none are lost · **Tools:** Relay attempt log, SQL on stored response headers

## Symptom (in the customer's words)

> About half of your webhooks fail our signature check, the others pass. Same secret, same code, same endpoint. We copied the verification snippet straight from your docs. Is your signing broken?

## Environment

- Customer receiver: two nodes (`web-1`, `web-2`) behind a round-robin load balancer, verifying Standard Webhooks signatures with the usual 5-minute timestamp tolerance ([receiver.py](receiver.py))
- Relay [Project 1](https://github.com/priyadharshanexe/relay) at `f43ea2f`, run with `../relay/up.sh`

## Reproduction

```bash
../relay/up.sh
./reproduce.sh     # starts the receiver, sends six events, prints attempts, receiver log and SQL
```

Full run: [reproduce-output.txt](reproduce-output.txt).

## Evidence

**1. "Random" is actually alternating.** Of six deliveries, three succeeded at once and three got `401`. The receiver's own response body (Relay keeps a snippet of every response) says why:

```
#1 09:18:05  11 ms  status=401  {"node": "web-2", "error": "timestamp too new (420 s in the future; tolerance 300 s)"}
#1 09:18:05   8 ms  status=200  {"node": "web-1", "ok": true}
```

The signature itself was never wrong. The *timestamp check* failed, and only on one node.

**2. One node is always the one refusing.** Relay stores each attempt's response headers, so the customer's `X-Served-By` header can be queried ([queries.sql](queries.sql), query 1):

```
 node  | ok | rejected
-------+----+----------
 web-1 |  4 |        0
 web-2 |  0 |        3
```

**3. web-2's clock is seven minutes slow.** Each node stamps its `Date` response header with its own clock. Comparing it with the moment Relay sent the attempt (query 2):

```
 node  |        sent_at         |  node_clock  | skew_seconds | status_code
-------+------------------------+--------------+--------------+------------
 web-1 | 2026-11-14 09:18:05.08 | 09:18:05     |            0 |         200
 web-2 | 2026-11-14 09:18:05.08 | 09:11:05     |         -420 |         401
```

By web-2's clock, every webhook was signed 420 seconds in the future, outside the 300-second window. By web-1's clock it was signed now.

## Root cause

The clock on one of the customer's two receiver nodes had drifted seven minutes behind (its NTP client had stopped). Standard Webhooks signatures include a timestamp and receivers reject anything more than five minutes off: this is what stops a captured webhook from being replayed later. The load balancer alternated between nodes, so roughly every second delivery landed on the node with the wrong clock.

## Fix

On the customer's side: restart time synchronisation on web-2 (`timedatectl set-ntp true` / `chronyc makestep`, or the equivalent in their container platform) and add clock drift to their monitoring. Relay keeps retrying refused deliveries, so nothing is lost meanwhile.

They should **not** widen the tolerance or skip the timestamp check: that removes the replay protection instead of fixing the clock.

## Verification

With web-2's clock corrected, every waiting delivery succeeded on its next scheduled retry, including one that landed on web-2:

```
delivery 8a0e061d…  status=succeeded  attempts=2
  #1 09:18:06   status=401  {"node": "web-2", "error": "timestamp too new (420 s in the future; tolerance 300 s)"}
  #2 09:18:12   status=200  {"node": "web-2", "ok": true}
```

## Reply to the customer

> Hi Dana,
>
> Thanks for the details, they made this quick to find. Our signatures are correct; the failures all come from one of your two servers. Every refused webhook was answered by `web-2`, with the message "timestamp too new (420 s in the future)". Your responses' `Date` headers show `web-2`'s clock running about 7 minutes behind `web-1`.
>
> Webhook signatures include the time they were signed, and your verification code (correctly) refuses anything more than 5 minutes off, to stop old messages being replayed. With `web-2` seven minutes slow, every webhook it handles looks like it comes from the future.
>
> Re-syncing the clock on `web-2` (restarting its NTP service) fixes it. Please don't increase the tolerance instead: that would weaken the replay protection. The refused webhooks are being retried automatically and will go through once the clock is right. Nothing needs replaying by hand.

## KB article

New article for Relay's knowledge base, written from this case:

> **Signature check fails with "timestamp too old" or "timestamp too new"**
> Every webhook is signed together with the time it was sent, and receivers refuse signatures more than 5 minutes off their own clock. If only some webhooks fail, check whether they all reach the same server; compare that server's clock with an NTP source (`chronyc tracking`, `timedatectl`). Fix the clock, not the tolerance. Refused webhooks are retried automatically.

For HAR-based tickets the equivalent HAR Triage finding is [R002](../../kb/R002-auth.md), "Not valid yet (clock)".

## Prevention

- **Product (Relay):** show the receiver's `Date` header next to "sent at" in the attempt log, and flag a difference over 60 seconds ("the receiver's clock is 7 min behind"). The evidence in step 3 then appears without SQL.
- **Docs:** add the clock-drift explanation to the signature troubleshooting page, with the exact error messages from the official libraries.
- **Support:** query 1 (outcome by node) is generic for any customer that returns a node or pod name. Added to the runbook.
