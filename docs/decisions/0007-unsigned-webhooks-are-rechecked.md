# 0007. Signed Zendesk webhooks; Freshdesk webhooks re-checked against the API

- **Status:** accepted
- **Date:** 2026-11-14

## Context

The webhook endpoint is public. Zendesk signs webhooks (base64 HMAC-SHA256 of the timestamp header followed by the raw body). Freshdesk automation webhooks are not signed; they can only carry custom headers.

## Options considered

1. **Trust the payload after a shared-secret check.** The payload would then decide which ticket and attachment to fetch.
2. **Use the payload only for the ticket id.** Verify the signature (Zendesk) or a per-connection secret header compared in constant time (Freshdesk), then re-read the ticket, its tags and its attachments through the helpdesk API, and act only on what the API says.

## Decision

Option 2 for both platforms. The trigger tag must still be on the ticket when the API is asked. Attachments are only downloaded from the helpdesk's own hosts, redirects are followed by hand, and API credentials are never sent to another host.

## Consequences

- A forged or replayed webhook can at most make us read a ticket of a connected account and find nothing to do.
- Subdomains are validated, so a connection can't point the client at an arbitrary host (no SSRF through configuration).
- Each webhook costs a few API calls, which matters for rate limits; 429s are retried with the helpdesk's `Retry-After`.
