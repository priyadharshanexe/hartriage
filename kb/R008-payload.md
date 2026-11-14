# R008 — Payload too large (413, 414, 431)

**What the tool found:** one of three "too big" errors, or an unusually large upload:

| Status | Name | What was too big |
|---|---|---|
| **413** | Payload Too Large | The request **body**: an upload, an import, a large JSON document. |
| **414** | URI Too Long | The **URL**: usually a search or filter that put too much data in the query string. |
| **431** | Request Header Fields Too Large | The **headers**, nearly always the `Cookie` header. |
| (info) | Large upload | A request body of 5 MB or more that succeeded, worth knowing about if uploads fail intermittently. |

The tool measures header and cookie sizes *before* redaction, so the evidence reports real sizes even though the cookie values are removed.

## 413: body too large

- Which limit applies? Proxies, load balancers and the app can each have their own (nginx defaults to 1 MB; many APIs use 256 KB to 10 MB).
- The fix is usually on the client: send fewer items per request, compress, or upload files through the dedicated upload endpoint.
- For webhook or event APIs, see casebook case 05: the event payload exceeded the documented maximum.

## 431: headers too large

Almost always **cookie bloat**: a site sets more and more cookies (A/B tests, analytics, preferences) until the `Cookie` header passes the server's limit (often 8 KB or 16 KB). The evidence gives the size of the `Cookie` header.

- Quick fix for the customer: clear cookies for the site.
- Real fix: engineering finds which cookies grow and stops setting them, or scopes them with `Path`/`Domain`.

## 414: URL too long

Move the data from the query string into a POST body.

## Reply template (413)

> The import request was 12 MB, and our API accepts up to 10 MB per request. Splitting the file into two smaller imports will work right away. We've also noted your request for a higher limit.
