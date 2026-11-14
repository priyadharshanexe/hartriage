# 0008. RustFS for local S3-compatible storage

- **Status:** accepted
- **Date:** 2026-11-14

## Context

The plan was S3 in production and MinIO locally. On 2026-11-14 the official `minio/minio` image could no longer be pulled from Docker Hub (access denied), and `quay.io/minio/minio:latest` had no manifest.

## Options considered

1. **An old, pinned MinIO image from a mirror.** Unmaintained, and of uncertain origin.
2. **LocalStack or moto server.** Good for tests, but in-memory, or heavier than a dev stack needs.
3. **RustFS** (Apache-2.0, S3-compatible, actively released). Supports multipart uploads, range reads and bucket lifecycle rules, which is everything this app uses.
4. **SeaweedFS or Garage.** Capable, but more setup for a single-node dev stack.

## Decision

RustFS `1.0.4` in docker compose; moto (in-process) in the unit tests; real S3 in production. The app only speaks the S3 API, so nothing in the code is specific to any of them.

## Consequences

- One S3 test runs against both moto and RustFS (when it is running), covering multipart, range reads, aborted uploads and the lifecycle rule.
- If RustFS lags on an S3 feature, the app degrades gracefully: the lifecycle rule is a backstop to the retention job, and failing to set it only logs a warning.
