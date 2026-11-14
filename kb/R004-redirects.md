# R004 — Redirect loops and long redirect chains

**What the tool found:** either a **loop** (the same URL appears twice in one chain of redirects, or the browser gave up with `ERR_TOO_MANY_REDIRECTS`), or a **long chain** of 5 or more redirects in a row.

## Redirect loops

A loop looks like a page that "keeps loading" or a browser error saying the page redirected too many times.

**Sign-in loops** are the most common kind: the app sends the user to the sign-in page, the sign-in page sends them back, and the app (still not seeing a session) sends them to sign-in again. The tool flags a chain as a sign-in flow when URLs mention login, auth, SSO, OAuth, SAML or callback. It also notes whether a `Set-Cookie` came back and whether any later request sent a cookie. If a cookie was set but never sent, the browser rejected or dropped it:

- **`SameSite`**: a cookie with `SameSite=Strict` (or `Lax` on a cross-site POST) is not sent on the redirect back from an identity provider.
- **Third-party cookies blocked**: Safari, Firefox and Chrome's incognito mode block cookies set inside iframes or for other domains.
- **Wrong `Domain`/`Path`** or a missing `Secure` flag on an http page.
- **Clock skew** making the cookie already expired on arrival.

**Configuration loops**: `http→https` on one layer and `https→http` on another (often a load balancer that terminates TLS), `www↔apex` rules on both the CDN and the server, or trailing-slash rules that undo each other.

## Long chains

Each redirect costs a round trip. Five hops on a mobile network can add a second or more. Link straight to the final URL, or merge the redirect rules.

## What to do

1. Read the chain in the finding's evidence: each hop's request number, status and URL.
2. For sign-in loops: ask the customer to try a private window with extensions off, then a different browser. If that works, it's cookie settings or an extension.
3. For configuration loops: give engineering the chain, so they can find the two rules that disagree.

## Reply template

> The recording shows your browser being sent between our app and the sign-in page six times without the sign-in being remembered. This usually means the browser isn't keeping our sign-in cookie. Could you try once in a private window, and let us know which browser and version you use?
