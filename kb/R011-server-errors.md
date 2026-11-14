# R011 — Server errors (5xx)

**What the tool found:** responses with status 500–599, grouped by **endpoint** (method, host and path, with ids folded into `{id}`, so `/orders/123` and `/orders/456` count as one), together with the **correlation ids** the server returned (`X-Request-Id`, `X-Amzn-RequestId`, `CF-Ray`, `traceparent` and similar).

A 5xx means the server failed. It is almost never something the customer did wrong, and almost never something support can fix alone. The job is a fast, complete escalation.

## Reading the status

| Status | Meaning |
|---|---|
| 500 | The application crashed or hit an unhandled error. |
| 502 | A proxy or load balancer got a bad answer from the app behind it (often the app crashed or restarted). |
| 503 | The service is unavailable: overloaded, in maintenance, or out of capacity. Check `Retry-After`. |
| 504 | A proxy timed out waiting for the app: a slow query, a stuck dependency. |

## What a good escalation contains

The finding's evidence has most of it already:

1. **Endpoint**: `POST api.example.com/v1/orders/{id}`
2. **Status and count**: `500 ×3`
3. **Correlation ids**: one per failed request. These let engineering jump straight to the right log lines.
4. **Time**: from the waterfall (UTC).
5. **Customer impact**: what they could not do, and whether there is a workaround.
6. Is it **one customer or many?** Check the status page and other tickets.

## Reply template

> Thanks for the recording. It shows our server returning an error when you saved the order (reference req-8f2c1a). That's a problem on our side, not something you did. I've passed the details to our engineering team and will update you as soon as I hear back.

## Before escalating

- Check the status page and recent incidents.
- Re-run the action yourself if you can: does it fail for you too?
- If the 5xx follows a 401 (see R001), fix the auth problem first; some backends answer 500 when they get a malformed token.
