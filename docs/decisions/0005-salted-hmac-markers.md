# 0005. Replace secrets with salted HMAC markers

- **Status:** accepted
- **Date:** 2026-11-14

## Context

A redacted file must still answer questions like "was the same token used in requests 3 and 7?" or "did the cookie change after sign-in?", without letting anyone recover or match the secret.

## Options considered

1. **A fixed placeholder (`[REDACTED]`).** Safe, but loses all correlation.
2. **A plain hash of the value.** Correlates, but the same token gets the same hash in every file, and short secrets can be brute-forced.
3. **HMAC-SHA256 with a random salt per file, truncated to 32 bits.** Correlates within a file; the salt is never stored, so markers can't be matched across files or reversed.

## Decision

Option 3: `[REDACTED:<8 hex>]`. 32 bits are plenty to tell a file's few hundred secrets apart and too few to be useful for anything else.

## Consequences

- Two analyses of the same original file produce different markers; the property test checks this.
- Re-redacting a redacted file leaves markers alone (idempotent).
