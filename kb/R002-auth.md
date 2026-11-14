# R002 — Authentication and permission errors (401 / 403)

**What the tool found:** responses with status 401 (Unauthorized: "who are you?") or 403 (Forbidden: "I know who you are, and the answer is no"). For each group of requests it answers three questions, using facts it read *before* removing the secrets:

1. **Were credentials sent at all?** An `Authorization` header, a cookie, an API key header or a token in the URL.
2. **Had the token expired?** If the token was a JWT, its `exp` (expiry), `iat` (issued at) and `aud` (audience) are decoded without verification and compared with the time of the request.
3. **What did the server say?** The `WWW-Authenticate` header often names the problem: `error="invalid_token"`, `error="insufficient_scope"`.

The token itself never appears in the finding. It shows up as a marker such as `[REDACTED:3f9a01c2]`. The same marker in two requests means the same token.

## The causes and what to do

| The finding says | What it means | Next step |
|---|---|---|
| **Token had expired** | The app sent a token past its expiry time. | Ask the customer to sign out and in again. If it keeps happening, the app is not refreshing tokens before they expire: escalate. |
| **Not valid yet (clock)** | The token's `nbf`/`iat` lies in the future by the browser's clock. | The customer's device clock is wrong. Ask them to set it to update automatically. |
| **No credentials sent** | The request reached the API without a token or cookie. | Is the user signed in? If yes, the cookie may be blocked (SameSite, third-party cookies in Safari/Firefox, a different domain) or the app is not attaching the token. |
| **Invalid token** | The server rejected the token itself. | Sign out and in. Check the token is for this environment (sandbox vs production) and was not revoked (password change, admin sign-out). |
| **Insufficient scope / forbidden** | Signed in, but not allowed to do this. | Check the user's role, permissions and plan. The `error_description` often names the missing scope. |
| **Blocked by CDN or firewall** | A 403 with an HTML page from Cloudflare, Akamai or similar. | The request never reached the app. Ask the site owner to check their WAF logs. |

## Checks before you reply

- Compare the **time of the request** with the token expiry shown in the evidence. A token that expired 2 minutes before is a refresh bug; one that expired 3 months before is a user who never signed out.
- If 401s appear on **every** API call after one sign-in request, look at that first request (see R001).
- If only **one** endpoint returns 403, it is almost always a permission, not a sign-in problem.

## Reply template

> Thanks for the recording. Your browser sent a sign-in token that had expired at 14:02, about 10 minutes before the page loaded, and our server refused it. Please sign out, sign back in and try again. If it happens again, let us know the time and we'll look into why the session wasn't renewed.

## Escalate when

Tokens expire well before their documented lifetime, refresh calls fail, or the same user gets 401s with a freshly issued token. Include request numbers, the token marker, `exp`/`iat` times and correlation ids.
