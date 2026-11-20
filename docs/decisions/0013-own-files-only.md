# 0013. Agents see their own files; admins see all

- **Status:** accepted
- **Date:** 2026-11-20

## Context

Customer HAR files are sensitive even after redaction: they show which customer had which problem. Until now every member of an organisation could list, open and download every file. There was also no way to delete a file before it expired, and no limits on uploads or storage.

## Options considered

1. **Everyone sees everything** (the old behaviour). Simple, but any agent can browse every customer's file.
2. **Own files only.** Agents and viewers see only what they uploaded; admins see every file in the organisation.
3. **Per-team sharing.** Closest to some helpdesks, but needs teams, which HAR Triage doesn't have.

## Decision

Option 2, chosen by the product owner.

- Agents and viewers see, open, download and delete only their own uploads. Admins see and delete every file and can filter to their own.
- Files from helpdesk tickets have no uploader, so they are admin-only. The ticket's own private note still carries the findings for the agent working the ticket.
- Someone else's file answers **404**, never 403, on every route, so file ids can't be probed.
- Deleting purges the redacted copy and the analysis at once and writes an audit entry.
- Admins set retention (7, 30 or 90 days, for new uploads), a maximum file size (never above the server's), an organisation storage quota and an optional daily upload limit per member. Uploads over a limit are refused with `413 file_too_large`, `413 storage_quota_exceeded` or `429 daily_upload_limit`.

## Consequences

- Viewers, who cannot upload, now see no files. If they need to, an admin can share the ticket text instead.
- An agent who leaves keeps nothing; their files stay visible to admins until they expire or are deleted.
