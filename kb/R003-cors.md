# R003 — CORS failures (likely)

**What the tool found:** a web page on one origin (for example `https://app.example.com`) tried to call an API on another origin (`https://api.partner.com`), and the API's answer did not give the browser permission to share the response with the page.

Findings from this rule are marked **likely**. Browsers enforce CORS *after* the network request completes, and HAR files often record the request as if nothing went wrong. The browser console has the final word: it prints a line starting with "Access to fetch at … has been blocked by CORS policy".

## What the tool looks for

- **Failed preflight.** Before a "non-simple" request (PUT/DELETE, JSON bodies, custom headers) the browser sends an `OPTIONS` request. If that returns an error, no `Access-Control-Allow-Origin`, the wrong origin, or does not allow the method or headers, the real request is never sent.
- **Missing `Access-Control-Allow-Origin`** on a cross-origin response.
- **Origin mismatch:** the response allows `https://staging.example.com` but the page is `https://app.example.com`.
- **Wildcard with cookies:** `Access-Control-Allow-Origin: *` cannot be used when the request sends cookies; the server must echo the origin and send `Access-Control-Allow-Credentials: true`.
- **No response at all** on a cross-origin request (`status 0`, `net::ERR_FAILED`), which is how many CORS blocks look in a HAR.

## What to do

1. Confirm with a screenshot of the browser console (DevTools → Console) while reproducing.
2. Identify who owns the API origin:
   - **Your own API:** engineering needs to add the customer's origin to the allowed list. Common causes: a new custom domain, `www` vs no `www`, `http` vs `https`, a staging origin in production config.
   - **A third party** (payment widget, analytics, a customer's own server in an integration): the fix is on their side.
3. If the customer uses a **browser extension or proxy** that rewrites headers, ask them to try a private window.

## Not CORS

- A 401/403 on a cross-origin request is an auth problem first (R002); some APIs omit CORS headers on errors, which then looks like CORS.
- A network error such as `ERR_NAME_NOT_RESOLVED` is R005.

## Escalate when

The API is yours and the customer's origin should be allowed. Include the page origin, the API origin, the method, and the preflight's status and headers from the finding.
