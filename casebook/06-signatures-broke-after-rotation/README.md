# 06 · "Signatures broke after we rotated the secret"

**Product:** Relay · **Severity:** high, every delivery refused · **Tools:** attempt log, SQL on `endpoint_secrets` and the audit log

## Symptom (in the customer's words)

> We rotated our signing secret yesterday as our security policy requires. Everything kept working, and then this morning every webhook started failing verification.

## Reproduction

```bash
../relay/up.sh
./reproduce.sh
```

The overlap window (24 h in production, 1 h here) is fast-forwarded by expiring the old secret in the database. Full run: [reproduce-output.txt](reproduce-output.txt).

## Evidence

- **Before rotation:** one signature sent, receiver OK.
- **During the overlap:** Relay signed with both secrets (`signatures_received: 2`), so the receiver, still holding secret A, kept passing. This is why "everything kept working".
- **After the overlap:** one signature (secret B only) → `401 no matching signature`.
- [queries.sql](queries.sql) shows the old secret's `expires_at`, the audit log entry `endpoint.secret_rotated` (who rotated, and when), and the number of signatures on each attempt.

## Root cause

The new secret was generated in the dashboard but never deployed to the receiver. Relay's overlap window hid this for 24 hours; when it ended, only the new signature was sent.

## Fix and verification

Deploy secret B to the receiver. The refused delivery succeeded on its next automatic retry (`#2 status=200`).

## Reply to the customer

> Hi Lee, your rotation worked on our side. For 24 hours we signed every webhook with both the old and the new secret, so your receiver (still using the old one) kept passing. When that window ended, only the new signature remained. Please deploy the secret shown when you rotated it (or rotate again and deploy that one). Refused webhooks are retried automatically.

## Prevention

- **Product (Relay):** show "still verifying with the old secret?" in the dashboard when receivers keep accepting during the overlap but never after a test with only the new signature; email a reminder before the overlap ends.
- **Docs:** rotation checklist: rotate → deploy → send a test event → done.
