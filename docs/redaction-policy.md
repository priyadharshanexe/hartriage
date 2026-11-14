# Redaction policy

What HAR Triage removes from a HAR file before anything is stored, what it keeps, and why. The code is [`hartriage/har/redactor.py`](../hartriage/har/redactor.py); the property test that holds it to this policy is [`tests/property/test_redaction_never_leaks.py`](../tests/property/test_redaction_never_leaks.py).

## The principle

**Values are removed; names are kept.** A header called `Authorization`, a cookie called `sid`, a query parameter called `code`, a JSON key called `password`: the name stays, so an engineer can still see *that* a credential was sent and *where*. The value is replaced with a marker.

**Redaction happens in the stream.** The upload is parsed one request at a time and each request is redacted before it is written. The unredacted file is never written to disk, a temporary file or object storage.

## Markers

Every removed value becomes `[REDACTED:<8 hex>]`, where the hex is the first 32 bits of `HMAC-SHA256(salt, value)`.

- **Same value, same marker, within one file.** "The token in request 3 is the one rejected in request 7" stays visible. JWT claims read before redaction are linked to their token by this marker.
- **Different files, different markers.** The salt is 32 random bytes created for each file and never stored, so markers cannot be compared across files or reversed.
- **Idempotent.** A value that is already a marker is left alone, so redacting a redacted file changes nothing.

In URL user-info (`https://user:password@host`) the marker is percent-encoded, because brackets are not allowed there.

## What is removed

| Where | What | Notes |
|---|---|---|
| Request and response headers | `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, `X-Auth-Token`, `X-CSRF-Token`, `X-XSRF-Token`, `X-Amz-Security-Token` | `Authorization: Bearer …` keeps the scheme word (`Bearer [REDACTED:…]`) when it is a known scheme. |
| | Any header whose name contains a sensitive word | Words, not substrings: `X-Shopify-Access-Token`, `Private-Token`, `X-Hub-Signature-256`, `Ocp-Apim-Subscription-Key` are removed; `Keep-Alive` and `X-Author` are not. |
| Cookies | Every value, request and response | Names and attributes (`Path`, `Domain`, `Expires`, `Secure`, `HttpOnly`, `SameSite`) are kept: they explain sign-in loops. |
| Query strings | `access_token`, `id_token`, `refresh_token`, `token`, `code`, `api_key`, `key`, `password`, `secret`, `client_secret`, `signature`, `sig`, `X-Amz-Signature`, `X-Amz-Credential`, `session`, `sid`, `jwt`, `assertion`, `SAMLResponse`, `otp`, `ticket` and any name with a sensitive word | In the `url`, in `queryString`, in `Referer` and `Location` headers, in `redirectURL`, in page titles, and in URL fragments (`#access_token=…`). |
| Request bodies | Form fields, multipart fields and JSON values under a sensitive key | JSON is walked recursively; everything under a sensitive key is removed (`"auth": {"user": …, "pass": …}`). Uploaded file contents in multipart bodies are dropped. |
| | Request bodies over 64 KB | Dropped whole, size kept. |
| Anywhere in text | JWTs and JWEs (`eyJ…`), `Bearer …` and `Basic …` credentials, AWS access key ids, private key blocks, GitHub, Slack, Stripe, Google and `sk-…` style keys, `name=value` pairs with a sensitive name, `"name": "value"` pairs in JSON that failed to parse | Every string in the entry is scanned, including custom fields such as `_initiator` and fields this tool doesn't know. |
| Custom fields | Values under `_`-prefixed keys whose name is sensitive | |
| WebSocket messages | Message contents | Replaced with their size. |

"Sensitive word" means one of: token, secret, key, apikey, session, sid, auth, authorization, authentication, password, passwd, pwd, pass, passphrase, signature, sig, credential(s), cookie, csrf, xsrf, jwt, bearer, otp, pin, cvv, cvc, privatekey, assertion. Names are split into words at punctuation and camelCase boundaries (`accessToken` → access, token), and a few strong substrings (token, secret, passw, signature, credential, session, apikey, authoriz) also count, so `xauthtoken` is caught too.

## What is dropped

**Response bodies, by default.** They are the largest part of a HAR file and the most likely to hold customer data (names, addresses, order contents). Only their size and MIME type are kept, with a comment saying the body was removed.

Two exceptions, both redacted with the same rules as request bodies:

- **Small JSON error bodies**: status 400 or above, under 16 KB. The error code and message are often the whole diagnosis (rule R009).
- **GraphQL errors**: a JSON body under 16 KB with a non-empty `errors` array keeps the `errors` array only; `data` is dropped. GraphQL reports errors with status 200.

## What is kept, and why

| Kept | Why |
|---|---|
| Methods, URLs (with secrets removed), status codes, timings, sizes, MIME types | The analysis needs them. |
| Header names and non-sensitive header values | `WWW-Authenticate`, `Retry-After`, `Access-Control-*`, `Server`, `Location` explain failures. |
| Correlation ids (`X-Request-Id`, `CF-Ray`, `traceparent`, …) | Engineering needs them to find the server's log lines. They identify a request, not a person, and grant no access. |
| `serverIPAddress`, TLS details (`_securityDetails`) | Network and certificate diagnosis. These are the server's details, not the user's. |
| JWT `exp`, `iat`, `nbf`, `aud` | Read *before* redaction to answer "had the token expired?". No other claim is kept (`sub` identifies a person). |
| Which kinds of credentials were present | `authorization:bearer`, `cookie`, `header:x-api-key`, `query:access_token`, never their values. |
| Header and cookie sizes | A 431 is often an oversized Cookie header. |

These facts are stored on each redacted entry as `_hartriage`, so a stored file can be re-analysed later without the secrets.

## Known limits

- **Secrets with no recognisable name or shape** are not found: a random token in a URL path (`/invite/9f8a7b…`) or under an innocent key (`"x": "…"`). Redacting every long random string would also remove content hashes and ids that make a HAR useful. This is the main reason the stored copy is still encrypted, access-controlled and deleted on a schedule.
- **Personal data** (names, emails, addresses) in request bodies and URLs is not removed. Response bodies, where most of it lives, are dropped; request bodies over 64 KB are dropped.
- **The original attachment on a helpdesk ticket** still contains everything until an admin enables *replace the original* on the connection.

## How it is tested

- **Property test** (Hypothesis): builds HAR files with random secrets planted in 25 kinds of places (headers, cookies, query strings, Referer, Location, form, multipart and nested JSON bodies, error bodies, GraphQL errors, WebSocket messages, custom fields, page titles, URL user-info, and JWTs, bearer tokens, AWS keys and private keys in free text). It then checks the redacted file, the findings, the summary in every format and the waterfall rows for each secret in raw, URL-encoded and JSON-escaped form. CI runs 3,000 generated files on every push.
- **Golden files**: HARs recorded in Chromium and Firefox with real (throwaway) JWTs; the redacted output must not contain them.
- **Unit tests** for each rule in this document, including the cases that must *not* be redacted (`WWW-Authenticate`, `Bearer authentication required`, `keyword=…`, error codes named `code` in JSON).
