# Live helpdesk testing

HAR Triage was tested end to end against a real **Freshdesk** trial and a real **Zendesk Suite Professional** trial on 19 November 2026. The webhooks reached the local stack through a Cloudflare quick tunnel. This page lists what was tested, on which tickets, what broke, and how each bug was fixed. Every fix has a test, and the fake helpdesk now copies each real behaviour that caused a bug, so the ordinary test suite catches it.

## Setup

| | |
|---|---|
| Stack | `docker compose -f docker-compose.yml -f docker-compose.live.yml up` ([live override](../docker-compose.live.yml)): real helpdesk APIs, public tunnel URL for webhooks |
| Tunnel | `cloudflared tunnel --url http://127.0.0.1:8200` (quick tunnel, no account) |
| Freshdesk | API key; connection verified against `GET /api/v2/agents/me` |
| Zendesk | Confidential OAuth client (`client_credentials` grant); webhook and trigger created through the API ([tools/live/zd_setup.py](../tools/live/zd_setup.py)) |
| Test data | [tools/live/seed.py](../tools/live/seed.py): tickets carrying the repository's recorded Chromium and Firefox HARs; requesters are `@example.com` addresses |
| Credentials | `.env.live` (gitignored); scripts never print a secret |

## What was tested

### Freshdesk

| # | Scenario | Ticket | Result |
|---|---|---|---|
| 1 | Tag a ticket with one HAR | 4 | One private note with the findings; tag became `har_analyzed` |
| 2 | Same webhook delivered twice | 4 | Freshdesk sent the delivery twice by itself; the second answered `200 duplicate` |
| 3 | Missing or wrong secret header | — | `401` |
| 4 | Two HARs + a PNG on the ticket, a third HAR in a later private note | 5 | One note per HAR (three); the PNG ignored |
| 4 | An 18 MB HAR (Freshdesk's limit is 20 MB) | 6 | Analysed: 102 requests, one note |
| 4 | A ticket with no attachment | 7 | No note; tag cleared |
| 5 | A real 429: 47 calls used up the minute's allowance, `Retry-After: 29` | 7 | The poll skipped that connection, showed "poll error: rate limited", and picked the ticket up next round |
| 6 | Replace the original HAR with the redacted copy | 8 | Original deleted (`DELETE /api/v2/attachments/:id` → 204); note carries `firefox-auth.redacted.har` |
| 7 | Re-tag a ticket that has nothing new | 4 | Tag cleared, no second note |

### Zendesk

| # | Scenario | Ticket | Result |
|---|---|---|---|
| 1 | Tag a ticket with one HAR | 3 | One private note; the original redacted by Zendesk; tag became `har_analyzed` |
| 2 | Zendesk re-fires the trigger after each note (the ticket was updated while still tagged) | 3, 4, 5, 6 | 3–4 extra signed deliveries per ticket, each with a new invocation id; all handled with no extra note |
| 2 | Replay of an identical signed delivery | 3 | First `202`, the identical second `200 duplicate` |
| 3 | Forged signature, missing signature, a valid signature 3 hours old | — | `401` each |
| 4 | Two HARs + an inline screenshot, a third HAR in a private comment | 4 | Three notes, three originals redacted, the screenshot untouched and still rendered inline |
| 4 | A 45 MB HAR (Zendesk's limit is 50 MB) | 5 | Analysed; redacted copy 0.45 MB attached to the note |
| 4 | A ticket with no attachment | 6 | No note; tag swapped |
| 6 | Replace the original with the redacted copy | 3, 4, 5 | Originals redacted (`.../attachments/:id/redact.json`), notes carry the redacted copies |
| 7 | Re-tag a ticket that has nothing new | 3 | Tag cleared, still one note |

Not provoked on Zendesk: a 429. The trial allows several hundred calls a minute, so hitting it would mean hammering the account. 429 handling is covered by the live Freshdesk 429 and the fake-helpdesk tests.

## Bugs found and fixed

| Bug | Found on | Fix | Commit |
|---|---|---|---|
| **httpx logged pre-signed attachment URLs** (S3 `X-Amz-Credential`/`Signature`) at INFO: anyone with log access could download a customer's original, unredacted HAR until the link expired. | Freshdesk | httpx and httpcore log at WARNING only; test | `1981e1d` |
| **Tagging a Freshdesk ticket never sent the webhook.** There is no "Tag is added" event, and "Ticket is updated" does not fire when only a tag changes, whether the tag is added through the API or by an agent in the UI. The setup steps named an event that does not exist. | Freshdesk | Poll the search API every 60 s for tagged tickets; the webhook becomes optional; setup steps rewritten ([decision 0011](decisions/0011-poll-freshdesk-for-tagged-tickets.md)) | `f32aa47` |
| **New Zendesk accounts cannot create API tokens** (Zendesk retires them on 30 April 2027), and the form only offered email + API token. | Zendesk | Confidential OAuth client: tokens minted with `client_credentials`, reused until shortly before expiry, re-minted once on 401; offered first in the form; migration 0002 ([decision 0012](decisions/0012-zendesk-oauth-client-credentials.md)) | `c1a963e` |
| **A Zendesk connection could not be created**: it required the webhook's signing secret, which Zendesk only shows after the webhook exists, and the webhook needs the connection's URL. | Zendesk | Secret optional at creation and added on the connection; until then every webhook is refused (an empty HMAC key is never accepted) | `c1a963e` |
| **The Zendesk trigger tag was never cleared**: a single-ticket update silently ignores `additional_tags` / `remove_tags` (they only work in `update_many`). | Zendesk | Tags API (`PUT` then `DELETE /tickets/:id/tags.json`); the fake helpdesk now ignores those fields too | `51ee64e` |
| **Zendesk refused the redacted copy** with `422 "The file type and file extension do not match"` whenever the file started `{"log":{"entries":[`. The same JSON with a line break after the opening brace is accepted. | Zendesk | `HarWriter` starts with `{\n"log":`; older stored copies are re-laid-out on upload; the fake refuses the old layout | `31c6351` |
| **"Request #3" linked to ticket 3**: Zendesk auto-links `#<number>` in comments, so request numbers pointed agents at other customers' tickets. | Zendesk | Written `#<span>3</span>`, which reads the same and is not linked | `85cc073` |

## Decisions recorded

- [0010](decisions/0010-one-note-per-har-file.md): one private note per HAR file. The spec's "exactly one note" is about duplicates, not about merging different files.
- [0011](decisions/0011-poll-freshdesk-for-tagged-tickets.md): poll Freshdesk for tagged tickets.
- [0012](decisions/0012-zendesk-oauth-client-credentials.md): connect Zendesk with a confidential OAuth client.

## Recorded traffic in CI

[tests/contract/test_helpdesk_cassettes.py](../tests/contract/test_helpdesk_cassettes.py) drives HAR Triage's real Zendesk and Freshdesk clients through the whole flow: check the credentials, search for tagged tickets (Freshdesk), read the ticket, download the HAR, post a private note with an attachment, find the note again, swap the tags, remove the original. The traffic from the live trials is stored in [tests/cassettes](../tests/cassettes) and replayed on every CI run, with no network and no credentials.

Before anything is written, [scrub.py](../tests/contract/scrub.py) removes:
- credentials and OAuth tokens
- signed download links
- Zendesk attachment tokens
- the accounts' subdomains
- any email address that isn't `@example.com`
- the agent's name

If a private value survives, the recording fails. To record again (this creates a ticket and posts a note on each trial):

```bash
HARTRIAGE_RECORD_LIVE=1 HARTRIAGE_SCRUB_WORDS="<agent name>" uv run pytest tests/contract -m live_helpdesk
```

## Still open

- On a ticket with several HAR files, the tag changes to `har_analyzed` after the *first* note is posted, while the others are still being posted. It would be clearer to change it only once every file on the ticket has its note.
- A live Zendesk 429.
