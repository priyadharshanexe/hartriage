# 0006. Exactly one private note per analysis

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
   - if a worker died after posting but before recording it, the retry searches the ticket for the note's marker (`HAR Triage analysis <id>`) and records the existing note instead of posting again.

## Decision

Option 2. Each layer handles a failure the others can't.

## Consequences

- The note carries its analysis id, visible to agents, which doubles as the remote idempotency key.
- A new attachment on the same ticket is analysed and gets its own note, as it should.
- The crash window is covered by a test that removes the record of a posted note and runs the task again.
