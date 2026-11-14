# 0001. Redact in the upload stream; never store the raw file

- **Status:** accepted
- **Date:** 2026-11-14

## Context

HAR files carry live session cookies, bearer tokens and API keys. In October 2023 an attacker inside Okta's support system took session tokens from customers' HAR files and hijacked sessions at five customers. The safest raw file is one that was never stored anywhere: not in object storage, not in a temp file, not in a queue.

But analysis is slow work that belongs in a background job, and a background worker is a different process from the one receiving the upload.

## Options considered

1. **Store the raw upload, redact in the worker.** Simple. But the raw file then exists at rest for at least the queue delay, in a bucket that can be misconfigured, backed up or read by anyone with storage access.
2. **Pass the raw bytes to the worker through Redis.** No object storage, but Redis may persist to disk (RDB/AOF), and a 100 MB message is a poor fit.
3. **Redact in the API while the upload streams in; queue only the analysis.** The API parses the request body as it arrives, redacts each request and streams the redacted output into a multipart upload. The worker then analyses the stored, redacted file.

## Decision

Option 3. The intake (parse → read facts → redact → write) runs in the API for uploads and in the worker for helpdesk attachments; both stream from the source straight into object storage. The rules run in the worker on the redacted copy.

## Consequences

- The API process holds an upload's bytes in memory only one entry at a time. The property and memory tests check both halves of that.
- An upload takes as long as its redaction, which in practice keeps pace with the upload itself. The response is 202 once the redacted file is stored.
- Re-analysis with a newer rule engine works from the stored redacted file, with no need for the original.
- Facts that redaction would destroy (token expiry, which credentials were sent) must be read *before* redacting and stored with the entry. See [0004](0004-rules-see-redacted-data-only.md).
