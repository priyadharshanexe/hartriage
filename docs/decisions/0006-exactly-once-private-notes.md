# 0006. One private note per analysis: at-least-once delivery with deduplication

- **Status:** accepted
- **Date:** 2026-11-14

## Context

Helpdesks deliver webhooks at least once: retries after timeouts, duplicate triggers, an agent re-adding the tag. Celery tasks can also run twice (acks-late, worker crashes). A ticket with three identical private notes is noise agents learn to ignore.

## Options considered

1. **Deduplicate on the webhook only.** Catches retries of the same delivery, but not a task that runs twice, nor a crash after posting.
2. **Layered keys plus a remote check:**
   - `webhook_receipts (connection, delivery_key)` unique: Zendesk's invocation id, or a body hash in a 10-minute bucket for Freshdesk, which sends no delivery id;
   - `artifacts (case, attachment)` unique: an attachment is analysed once per ticket;
   - `posted_notes (case, analysis)` unique, with the row locked while posting, so a second task waits and then sees "posted";
   - before every post, the task searches the ticket for the note's marker (`HAR Triage analysis <id>`); if the note is there, it records it instead of posting again.

## Decision

Option 2. Each layer handles a failure the others can't.

## Consequences

- The note carries its analysis id, visible to agents, which doubles as the remote idempotency key.
- A new attachment on the same ticket is analysed and gets its own note, as it should.
- The crash window is covered by a test that puts the row back exactly as a crash leaves it (pending, 0 attempts) with the note already on the ticket, and runs the task again; and by a test where six workers run the task for the same file at once.

## The guarantee, precisely

Delivery is **at-least-once with deduplication**, not exactly-once: no system can make "post to another company's API" and "commit to our database" one atomic step.

- Each task is sent at least once: the row is committed before its task is sent, and a sweep every five minutes re-sends analyses and notes whose task was lost.
- Before posting, the task takes the row lock and searches the ticket for its marker, so a task that runs again after a crash, a duplicate webhook, or a redelivery finds the earlier note and posts nothing.
- One case remains: the helpdesk accepted the POST but the note is not yet visible when the retry searches (an eventually consistent comment list). Then a second note can appear. Neither Zendesk nor Freshdesk showed this in live testing.

## Amended

- **2026-11-25:** the search used to run only when the row's attempt counter was above zero. A worker killed right after the POST rolls its increment back, so the redelivered task skipped the search and posted a second note (reproduced in a test). The search now runs before every post.
