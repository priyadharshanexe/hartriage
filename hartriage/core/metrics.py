"""Prometheus metrics. Labels never carry customer data."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

UPLOADS = Counter("hartriage_uploads_total", "Uploads by outcome", ["outcome"])
ANALYSES = Counter("hartriage_analyses_total", "Finished analyses by status", ["status"])
ANALYSIS_SECONDS = Histogram(
    "hartriage_analysis_seconds",
    "Time to analyse a stored file",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
FINDINGS = Counter("hartriage_findings_total", "Findings by rule", ["rule"])
SECRETS = Counter("hartriage_secrets_redacted_total", "Distinct secrets removed")
WEBHOOKS = Counter("hartriage_webhooks_total", "Inbound helpdesk webhooks", ["platform", "outcome"])
NOTES = Counter(
    "hartriage_notes_total", "Private notes posted to helpdesks", ["platform", "outcome"]
)
HELPDESK_CALLS = Counter(
    "hartriage_helpdesk_requests_total", "Calls to helpdesk APIs", ["platform", "status"]
)
ORPHANS = Counter(
    "hartriage_orphan_objects_deleted_total",
    "Stored objects deleted because no row came to own them",
    ["reason"],
)
