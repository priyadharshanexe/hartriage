# 04 · "Our endpoint never gets called"

**Product:** Relay · **Severity:** high for the customer (no events at all), working as designed on our side · **Tools:** Relay attempt log, DNS lookup from the worker, SQL

## Symptom (in the customer's words)

> We set up our endpoint yesterday and your dashboard shows deliveries "retrying", but our server logs show zero requests from you. Not a single hit. Our firewall team says nothing is being blocked. What IP do you send from?

## Environment

- Customer endpoint: `http://169.254.169.254.nip.io/webhooks/relay`, a public DNS name that resolves to a non-public address
- Relay [Project 1](https://github.com/priyadharshanexe/relay) at `f43ea2f`, run with `../relay/up.sh`

> **Reproduction note.** Production Relay refuses every private range (10/8, 172.16/12, 192.168/16) and more. The local stack allows private ranges so test receivers on your own machine work, so this reproduction uses a name that resolves into 169.254.0.0/16 (link-local, which includes cloud metadata services), which stays blocked even in development. The code path is identical: resolve the name, check every address, refuse before connecting. In the customer's real case the record pointed at an internal load balancer, `10.20.3.15`.

## Reproduction

```bash
../relay/up.sh
./reproduce.sh
```

Full run: [reproduce-output.txt](reproduce-output.txt).

## Evidence

**1. The attempts never leave Relay.** Every attempt took 0 ms and has no status code:

```
delivery 9796ba14…  status=retrying  attempts=2
  last_error: ssrf_blocked: 169.254.169.254 is blocked: link-local address (includes cloud metadata)
  #1 09:30:26   0 ms  status=None  error=ssrf_blocked
  #2 09:30:31   0 ms  status=None  error=ssrf_blocked
```

0 ms is the giveaway: no connection was attempted, so the customer's firewall and logs genuinely saw nothing. Their firewall team was right.

**2. The name resolves to a non-public address.** Asked from inside Relay's worker container, which is where deliveries are made from:

```
169.254.169.254.nip.io -> ['169.254.169.254']
```

**3. Relay explains it when the address is entered directly.** Registering the IP itself is refused with the reason at once:

```json
{"code": "invalid_endpoint_url", "message": "169.254.169.254 is blocked: link-local address (includes cloud metadata)"}
```

A *name* is accepted at registration, because DNS can change between then and delivery, so the check runs on every delivery, against every address the name resolves to.

**4. The SQL view** ([queries.sql](queries.sql), query 2) lists endpoints that have never succeeded but have blocked attempts. Support can run it proactively and contact customers before they write in.

## Root cause

The customer registered a hostname whose DNS record points to a non-public address (an internal load balancer). Relay never connects to private, loopback, link-local or other non-public addresses, and re-checks after every DNS lookup. Without this, anyone could point a webhook at an internal service and use Relay to reach it: the classic example is a cloud metadata endpoint that hands out credentials. The block happens before any packet is sent, which is why the customer saw no traffic at all.

## Fix

The customer exposes the receiver on a public address: a public load balancer or API gateway with HTTPS, and a firewall rule allowing Relay's published egress IPs. Then they update the endpoint URL; the waiting deliveries continue on their own.

What we must **not** do is add an exception for this customer: the protection only works if there are no exceptions.

## Verification

After moving the endpoint to a public HTTPS address (here `https://httpbin.org/post`), the same waiting delivery succeeded on its next attempt, with no replay needed:

```
delivery 9796ba14…  status=succeeded  attempts=3
  #1 09:30:26     0 ms  error=ssrf_blocked
  #2 09:30:31     0 ms  error=ssrf_blocked
  #3 09:30:43  1178 ms  status=200
```

## Reply to the customer

> Hi Sam,
>
> Thanks for checking with your firewall team. They're right that nothing reached you, and here's why: your endpoint's hostname resolves to `10.20.3.15`, a private network address. For security, Relay never sends webhooks to private or internal addresses. If it did, anyone could use it to reach internal systems. So we stop before connecting, which is why your logs are empty.
>
> To start receiving events:
>
> 1. Expose the receiver on a public HTTPS address (for example through your public load balancer or API gateway).
> 2. Allow our egress IPs on your firewall: [list in our docs].
> 3. Update the endpoint URL in Relay.
>
> Everything sent so far is queued and will be delivered automatically once the endpoint is reachable. Nothing to resend.

## KB article

New article for Relay's knowledge base, written from this case:

> **Deliveries show "ssrf_blocked" and the receiver sees no traffic**
> Relay only delivers to public addresses. Check what the endpoint's hostname resolves to (`dig +short <host>`). A private (10.x, 172.16–31.x, 192.168.x), loopback or link-local answer is refused before connecting. Fix: a public HTTPS address for the receiver. Relay makes no exceptions.

## Prevention

- **Product (Relay):** resolve the hostname when the endpoint is *saved* as well, and warn ("this name currently resolves to a private address; deliveries will be refused") without blocking the save. The customer would have known in the first minute.
- **Product (Relay):** show "Blocked before connecting: your hostname resolves to 10.20.3.15" in the dashboard instead of the code `ssrf_blocked`.
- **Support:** schedule query 2 weekly; reach out to customers whose new endpoints have never succeeded.
