# R010 — Mixed content

**What the tool found:** a secure page (`https://`) loading resources over plain `http://`. Browsers treat this differently by type:

- **Active content** (scripts, stylesheets, API calls, iframes) is **blocked**. A blocked script can leave the page half-working with no visible error.
- **Passive content** (images, audio, video) is upgraded to `https://` automatically by modern browsers, or blocked if the upgrade fails.

Local development hosts (`localhost`, `127.0.0.1`) are ignored.

## Common causes

- Hard-coded `http://` URLs in templates, CMS content or emails rendered in the app.
- A CDN or asset host configured with an `http://` base URL.
- Content pasted by users (images in rich-text fields).
- A third-party widget that still uses `http://`.

## What to do

1. The evidence lists example URLs. Search the codebase or CMS for them.
2. Change them to `https://`. Every major CDN serves both.
3. Adding the header `Content-Security-Policy: upgrade-insecure-requests` upgrades the remaining ones automatically.

## Reply template

> Our page was loading one of its scripts over an insecure connection, which your browser blocks for your safety. We've passed this to our team to fix. In the meantime, the feature works in the desktop app.
