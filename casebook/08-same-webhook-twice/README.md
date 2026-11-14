# 08 · "We received the same webhook twice"

**Product:** Relay · **Severity:** high for the customer (an order shipped twice); expected behaviour on our side · **Tools:** customer's receiver log, Relay worker log, SQL

## Symptom (in the customer's words)

> Order 7001 was shipped twice yesterday. Our logs show your `order.paid` webhook arriving twice, a minute apart, with the same ID. Your docs say each event is delivered once. What happened?

## Environment

- Customer receiver that ships the order as soon as the webhook arrives, then spends 8 s on bookkeeping before answering ([receiver.py](receiver.py))
- Relay [Project 1](https://github.com/priyadharshanexe/relay) at `f43ea2f`: a worker claims a delivery with a 60-second lease; if the worker dies, the lease expires and the delivery is sent again
- The incident (a worker process killed during a deploy) is reproduced with `docker kill` on Relay's worker while the receiver is still working

## Reproduction

```bash
../relay/up.sh
./reproduce.sh
```

Full run: [reproduce-output.txt](reproduce-output.txt).

## Evidence

**1. The customer's log: one webhook-id, two shipments, 61 seconds apart.**

```
18:13:21 b52f1379-067c-4ed4-bd18-6310368b4946 order=7001 SHIPPED
18:14:22 b52f1379-067c-4ed4-bd18-6310368b4946 order=7001 SHIPPED (again!)
```

**2. Relay's worker log, at the moment of the second send:**

```
{'timestamp': '2026-11-14T12:44:22Z', 'event': 'worker.recovered_expired_leases', 'count': 1}
```

**3. Relay recorded only one attempt** ([queries.sql](queries.sql)):

```
 attempt_number |  started_at  | duration_ms | status_code | webhook_id_sent  | seconds_after_event
              1 | 12:44:22.17  |        8023 |         200 | b52f1379-…       |                  61
```

The first send never got a row: the worker died after sending the request and before it could record the answer. The only recorded attempt starts 61 s after the event, which is the 60 s lease running out. The `webhook-id` is the event id, the same on both sends, which is exactly what lets a receiver recognise the repeat.

## Root cause

Relay delivers **at least once**, by design. A worker was stopped between sending the webhook and recording the receiver's answer. Relay could not know whether the receiver had processed it, so when the lease expired it sent it again (the alternative, never re-sending, would lose events whenever a worker dies). The customer's receiver did its side effect (shipping) on every arrival without checking whether it had already handled that `webhook-id`.

## Fix

On the customer's side: make the handler idempotent. Store each `webhook-id` (a unique column, kept for a few days) and acknowledge a repeat with `200` without acting on it. Answering quickly and doing slow work afterwards also shortens the window in which a crash can cause a repeat.

## Verification

Same crash, with deduplication on:

```
18:14:33 bf424c49-… order=7002 SHIPPED
18:15:34 bf424c49-… order=7002 DUPLICATE, acknowledged without shipping
```

## Reply to the customer

> Hi Alex,
>
> Sorry about the double shipment. What happened: one of our delivery workers was restarted while your server was still processing that webhook, before your answer reached us. We couldn't tell whether you had received it, so a minute later we sent it again, with the same `webhook-id`. Sending again is deliberate: the alternative is losing events whenever a server restarts, which would be worse.
>
> Our docs promise *at-least-once* delivery, and I'm sorry if that isn't clear enough on the page. The reliable fix on your side is to store each `webhook-id` you process and skip ones you've already seen (a unique column is enough). We reproduced your setup and with that check the repeat was acknowledged without shipping anything. Responding as soon as you've stored the event and doing the slower work afterwards also makes repeats rarer.

## KB article

New article for Relay's knowledge base:

> **The same webhook arrived twice**
> Relay delivers at least once: after a timeout or a restart on either side, a webhook can arrive again with the same `webhook-id`. Store processed ids and acknowledge repeats without acting. Answer within a few seconds and do slow work afterwards.

## Prevention

- **Product (Relay):** finish in-flight deliveries before a worker stops (graceful shutdown already waits up to 30 s; `docker kill` and crashes can't). Nothing can remove the window entirely.
- **Docs:** move "at least once, deduplicate on `webhook-id`" to the top of the receiving-webhooks guide, with a code sample.
- **Product (Relay):** show "possible repeat: sent again after a worker restart" on the delivery, so support can answer this ticket from the dashboard.
