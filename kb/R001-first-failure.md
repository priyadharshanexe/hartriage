# R001 — First failure

**What the tool found:** the earliest request in the recording that failed: a status of 400 or above, no response at all (status 0), or a network error recorded by the browser. It also lists the failures that came after it on the same host.

## Why the first one matters

When something breaks early in a page load, everything that depends on it breaks too. A customer's HAR often shows thirty red lines, but only the first is the cause:

- the login call returns 401 → every API call after it returns 401 as well;
- the config request times out → the app retries, then shows a blank page;
- a script is blocked → the page never makes the API calls you expected to see.

Fix the first failure, and the rest usually disappear.

## What is ignored

Some failures happen on almost every site and mean nothing, so R001 skips them:

- `favicon.ico` 404s;
- requests the browser cancelled itself (`net::ERR_ABORTED`, `NS_BINDING_ABORTED`), which happen on every navigation;
- requests blocked by an ad blocker (`net::ERR_BLOCKED_BY_CLIENT`). R005 still reports these as information, in case the app needs the blocked host;
- `data:`, `blob:` and extension URLs.

## How to work the case

1. Open request #N from the finding in the waterfall. Read its status, the `WWW-Authenticate` or error body if there is one, and its timing.
2. Check the other findings: a more specific rule (R002 auth, R005 network, R011 server error) often explains the same request. The ticket summary already picks that explanation when there is one.
3. Note the time of the failure. Engineering will need it, together with any correlation ids, to find the server logs.

## Ask the customer

- "Does it happen every time, or only sometimes?" If only sometimes, a second HAR recorded when it works is very useful for comparison.
- "Did anything change: a new browser, VPN, network, password, or plan?"

## Escalate when

The first failure is a 5xx (see R011), or a 4xx you cannot explain from the response. Include the request number, method, URL (already redacted), status, timestamp and correlation ids.
