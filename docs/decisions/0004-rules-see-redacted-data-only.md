# 0004. Rules run on redacted data; facts are read before redaction

- **Status:** accepted
- **Date:** 2026-11-14

## Context

The most useful auth finding is "the token had expired 10 minutes before the request", which needs the token. But a finding, a summary or a helpdesk note that contains a token defeats the purpose of the tool, and summaries get pasted into tickets.

## Options considered

1. **Run the rules on the raw entries, redact the output.** The rules see everything, but every new rule becomes a new place a secret could leak.
2. **Run the rules on redacted entries only, and extract a fixed set of facts before redacting.** Credential kinds present; JWT `exp`, `iat`, `nbf`, `aud`; correlation ids; header and cookie sizes. Stored on the entry as `_hartriage`.

## Decision

Option 2. Rules never see a secret, so no rule can leak one. The facts are deliberately few and contain no values that grant access.

## Consequences

- A rule that needs a new fact needs a change to `metadata.py`, reviewed with the redaction policy in mind.
- JWT claims are linked to their token by the redaction marker, so "token [REDACTED:3f9a01c2] expired" is useful without the token.
- Re-analysis of a stored file uses the stored facts, so results are reproducible.
