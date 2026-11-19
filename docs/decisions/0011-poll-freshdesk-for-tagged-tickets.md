# 0011. Find tagged Freshdesk tickets by polling

- **Status:** accepted
- **Date:** 2026-11-19

## Context

The design (and [0007](0007-unsigned-webhooks-are-rechecked.md)) assumed both helpdesks call HAR Triage when an agent adds the `har_analyze` tag. Measured on a live Freshdesk trial (see [live-helpdesk-testing.md](../live-helpdesk-testing.md)):

- Freshdesk automations have no "tag is added" event. The automation API rejects `tag` and `tags` as events, and the agent UI lists none.
- The closest event, "Ticket is updated", does **not** fire when only a tag changes: not when the tag is added through the API, and not when an agent adds it in the ticket's properties and clicks Update. It does fire when, say, the priority changes on a tagged ticket.

So in Freshdesk, tagging a ticket never sent the webhook.

## Options considered

1. **Ask agents to change a field as well** (priority, status) so the rule fires. Fragile, easy to forget, and it changes ticket data for a tooling reason.
2. **An hourly-trigger automation** with a tag condition. Fires on tags, but only once an hour: too slow for an agent waiting on a ticket.
3. **Poll the search API** (`GET /api/v2/search/tickets?query="tag:'har_analyze'"`) every minute per Freshdesk connection, and ingest each hit exactly as if its webhook had arrived. One API call a minute (Freshdesk trials allow 50); search results were current within seconds in testing.

## Decision

Option 3, with the webhook kept as an optional speed-up for updates that do fire it. A polled ticket is recorded in `webhook_receipts` with the key `poll:<ticket id>:<updated_at>`, so a ticket that stays tagged is not re-queued every minute, and the existing exactly-once layers ([0006](0006-exactly-once-private-notes.md)) apply unchanged.

## Consequences

- Freshdesk works with no automation at all: the setup steps say so.
- Pick-up takes up to a minute (`HARTRIAGE_FRESHDESK_POLL_SECONDS`, 0 turns it off).
- A 429 skips that connection for the round, and the connection page shows "poll error: rate limited" until the next successful poll.
- Zendesk keeps its signed webhook: its triggers do fire on tag changes.
