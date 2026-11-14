# 01 · "My endpoint stopped receiving webhooks"

**Product:** Relay (webhook delivery) · **Severity:** high, the customer is missing orders · **Tools:** Relay delivery log, SQL, HAR Triage, `openssl`/Python `ssl`

## Symptom (in the customer's words)

> Since this morning our order system hasn't received a single `order.paid` webhook. Nothing changed on our side. Your status page is green. Are you dropping our events?

## Environment

- Endpoint: `https://expired.badssl.com/` (stands in for the customer's receiver; the real host is irrelevant to the cause)
- Relay as in [Project 1](https://github.com/priyadharshanexe/relay), commit `f43ea2f`, run locally with `../relay/up.sh`
- Retry schedule shortened to `[0, 5, 15, 30, 60]` seconds for the reproduction (production: 0 s → 24 h over 7 attempts)

## Reproduction

```bash
../relay/up.sh          # Relay on :8101, its own database on :5444
./reproduce.sh          # creates the endpoint, sends one event, prints the attempt log and the SQL below
```

The full run is in [reproduce-output.txt](reproduce-output.txt).

## Evidence

**1. Relay received the events.** `POST /v1/events` returned `202` and created a delivery, so ingestion is fine. The problem is between Relay and the customer.

**2. Every attempt failed before HTTP.** The delivery's attempt log:

```
delivery 3d71cedf…  status=retrying  attempts=2  endpoint=https://expired.badssl.com/
  last_error: tls: TLS handshake failed:
  #1 09:15:35   1641 ms  status=None  error=tls
  #2 09:15:42   1454 ms  status=None  error=tls
```

`status_code` is empty and `error_kind` is `tls`: the connection was refused during the TLS handshake, so no request ever reached the customer's application. That also explains why their own logs show nothing.

**3. SQL across the endpoint** ([queries.sql](queries.sql)) shows no success since the first TLS failure, plus a few attempts that hit the 5-second timeout during the handshake. An earlier delivery in the reproduction went to the dead-letter queue that way (`timeout: the receiver did not respond in time`). Query 4 confirms it is this endpoint only: other customers' deliveries are fine, which matches the green status page.

**4. Relay's error text stops short.** `last_error` reads `TLS handshake failed:` with nothing after the colon. It says *where* it failed, not *why*. I checked the certificate directly:

```
$ python -c "…ssl.get_server_certificate…"
subject:    CN=*.badssl.com
not after:  2015-04-12 23:59:59+00:00
verify:     certificate has expired
```

**5. The customer's browser agrees.** I asked them to open their endpoint URL in Chrome and send a HAR file ([endpoint-check.har](endpoint-check.har)). HAR Triage ([full summary](hartriage-summary.md)):

> **First failure:** Request #1: GET https://expired.badssl.com/ → net::ERR_CERT_DATE_INVALID
> **Likely cause:** The secure connection to expired.badssl.com failed because the certificate has expired (or the device clock is wrong).

Two independent clients (Relay's worker and the customer's own browser) failing the same way rules out anything specific to Relay.

## Root cause

The TLS certificate on the customer's webhook endpoint expired. Relay verifies certificates (as it must: delivering signed business events over an unverified connection would expose them), so every delivery attempt failed at the handshake and was scheduled for retry.

## Fix

On the customer's side: renew the certificate, and check the full chain is served (an expired *intermediate* fails the same way). On our side: nothing to fix for this ticket; the deliveries are waiting, not lost.

## Verification

After the "renewal" (simulated by pointing the endpoint at a host with a valid certificate), the waiting delivery was replayed and succeeded:

```
delivery 3d71cedf…  status=succeeded  attempts=3
  #1 … error=tls
  #2 … error=tls
  #3 09:15:59   1119 ms  status=200  error=None
```

Deliveries already in the dead-letter queue are replayed with **Replay all** on the dead-letter page (or `POST /v1/deliveries/replay` filtered to this endpoint), so nothing is lost.

## Reply to the customer

> Hi Alex,
>
> Thanks for the quick report, and sorry for the stress around missing orders. I've found the cause: we are sending your `order.paid` events, but your endpoint's TLS certificate expired, so our servers can't open a secure connection to it. Your own browser shows the same error ("NET::ERR_CERT_DATE_INVALID") when it opens the endpoint URL.
>
> Nothing is lost. Every event since the certificate expired is waiting in Relay and will be retried. Once the certificate is renewed:
>
> 1. Check it at https://www.ssllabs.com/ssltest/ (the whole chain should be valid).
> 2. Reply here and I'll replay everything waiting for your endpoint, or use **Replay all** on the dead-letter page yourself.
>
> To avoid a repeat, an expiry reminder 30 days ahead (most certificate providers offer one) or automatic renewal with Let's Encrypt will help.

## KB article

[R005: DNS, connection and TLS failures](../../kb/R005-network.md) (TLS row). The same categories apply to server-to-server webhook deliveries.

## Prevention

- **Product (Relay):** include the TLS verification reason in the attempt's error (Python exposes it as `SSLCertVerificationError.verify_message`, here "certificate has expired"). The agent would have had the root cause in the first minute instead of confirming it by hand. Raised as a follow-up for engineering.
- **Product (Relay):** warn endpoint owners by email when TLS failures start. The circuit breaker already notices; the customer doesn't.
- **Support:** a saved SQL query (query 3 above) for "since when has this endpoint been failing" goes into the support runbook.
