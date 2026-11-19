# 0012. Connect Zendesk with a confidential OAuth client

- **Status:** accepted
- **Date:** 2026-11-19

## Context

The first design connected Zendesk with an agent email and an API token. On a new live Zendesk trial, the API tokens page has no way to create one: Zendesk shows that API tokens stop working on 30 April 2027 and that integrations should move to OAuth. The authorization-code flow would need a browser redirect back to HAR Triage for every connection.

## Options considered

1. **Paste an OAuth access token.** Simple, but someone has to mint it by hand, and it cannot be renewed.
2. **Authorization-code flow.** The usual "Connect with Zendesk" button; needs a registered redirect URL and an extra page, and a refresh-token store.
3. **Confidential OAuth client, client_credentials grant.** The admin creates a confidential OAuth client and pastes its id and secret; HAR Triage mints tokens itself (`POST /oauth/tokens`), reuses each until shortly before it expires, and mints a new one once on a 401.

## Decision

Option 3, offered first in the connection form. API tokens and pasted OAuth tokens still work for existing accounts.

## Consequences

- New Zendesk accounts can connect, and keep working after API tokens are retired.
- The client secret is stored like the other credentials (encrypted per connection); tokens live only in worker memory.
- Revoking the OAuth client in Zendesk cuts HAR Triage off at once.
