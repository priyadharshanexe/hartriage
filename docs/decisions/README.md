# Decision records

One file per significant decision, copied from [0000-template.md](0000-template.md).

| # | Decision | Status |
|---|----------|--------|
| [0001](0001-redact-in-the-stream.md) | Redact in the upload stream; never store the raw file | accepted |
| [0002](0002-celery-for-background-jobs.md) | Celery and Redis for background jobs (unlike Relay's Postgres queue) | accepted |
| [0003](0003-waterfall-index-and-range-reads.md) | A waterfall index in PostgreSQL; request detail by byte-range read | accepted |
| [0004](0004-rules-see-redacted-data-only.md) | Rules run on redacted data; facts are read before redaction | accepted |
| [0005](0005-salted-hmac-markers.md) | Replace secrets with salted HMAC markers | accepted |
| [0006](0006-exactly-once-private-notes.md) | One private note per analysis: at-least-once with deduplication | accepted |
| [0007](0007-unsigned-webhooks-are-rechecked.md) | Signed Zendesk webhooks; Freshdesk webhooks re-checked against the API | accepted |
| [0008](0008-rustfs-for-local-object-storage.md) | RustFS for local S3-compatible storage | accepted |
| [0009](0009-no-llm-in-the-analysis.md) | No LLM in the analysis | accepted |
| [0010](0010-one-note-per-har-file.md) | One private note per HAR file, not per tag action | accepted |
| [0011](0011-poll-freshdesk-for-tagged-tickets.md) | Find tagged Freshdesk tickets by polling | accepted |
| [0012](0012-zendesk-oauth-client-credentials.md) | Connect Zendesk with a confidential OAuth client | accepted |
| [0013](0013-own-files-only.md) | Agents see their own files; admins see all | accepted |
