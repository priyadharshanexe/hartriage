# 0003. A waterfall index in PostgreSQL; request detail by byte-range read

- **Status:** accepted
- **Date:** 2026-11-14

## Context

The web app shows every request in a waterfall (filterable by status, host and duration) and, on click, one request's headers and body. A HAR file can hold 50,000 requests and 100 MB. Findings must point at requests, and the redacted file in object storage should stay the single copy of request contents.

## Options considered

1. **Store every redacted entry as JSONB in PostgreSQL.** Fast detail views, but it duplicates the file's contents into the database, which then needs the same retention and access care as the bucket.
2. **Read the whole file from storage for each detail view.** No duplication, but opening one request of a 100 MB file means downloading and parsing up to 100 MB.
3. **A small index row per request in PostgreSQL (no headers, no bodies), plus the entry's byte offset and length in the stored file.** The waterfall and its filters are SQL; request detail is one HTTP range read of a few kilobytes.

## Decision

Option 3. The writer records each entry's `(offset, length)` while streaming the redacted file and stores them in a small binary index next to it. The analysis job copies them onto the `entries` rows.

## Consequences

- The stored redacted file must not be compressed, or range reads stop working. Object storage encryption still applies.
- The index is derived data: re-running an analysis rebuilds it from the file.
- Findings store request numbers, never request copies.
