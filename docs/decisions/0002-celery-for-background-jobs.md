# 0002. Celery and Redis for background jobs

- **Status:** accepted
- **Date:** 2026-11-14

## Context

Analyses of large files take seconds to minutes, helpdesk calls must be retried with backoff when rate limited, and retention must run on a schedule. Project 1 (Relay) used PostgreSQL as its queue, because there the job *is* the data: each delivery row is the queue entry, and claiming it with `SKIP LOCKED` inside the same transaction is the whole point.

## Options considered

1. **PostgreSQL queue, as in Relay.** One less service. But here the jobs are not the data: an analysis job is "process this file", and its retries, countdowns and schedules would all need writing by hand.
2. **Celery with Redis as the broker.** Retries with countdowns (`self.retry(countdown=retry_after)`), a beat scheduler for retention, acks-late delivery, and inline (eager) execution in tests.
3. **RQ or Dramatiq.** Smaller, but a weaker scheduler story and less familiar to most teams.

## Decision

Celery with Redis as the broker. Results are stored by the tasks in PostgreSQL (no result backend). Tasks are acknowledged after they finish (`acks_late`) and re-queued if a worker dies, so every task is written to be safe to run twice.

## Consequences

- Redis runs without persistence: it is a queue, not a store. A lost queue entry is recovered by re-tagging a ticket or re-running an analysis.
- "Safe to run twice" is a hard rule. The note task in particular is exactly-once by design (see [0006](0006-exactly-once-private-notes.md)).
- Retries in tests run inline, so the 429-retry path is tested end to end without a running worker.
