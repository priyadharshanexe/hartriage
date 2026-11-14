"""The analysis job: read the redacted file back, run the rules, store the results.

It works from the stored redacted file alone, so an analysis can be re-run with a
newer rule engine at any time until the file expires.
"""

from __future__ import annotations

import uuid
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from hartriage.core.config import Settings
from hartriage.db.models import Analysis, EntryIndex, FindingRow
from hartriage.har.stream_reader import NO_LIMITS
from hartriage.pipeline import EntryRow, process
from hartriage.rules import RuleConfig
from hartriage.services.intake import load_offsets
from hartriage.storage.s3 import Storage
from hartriage.summary import build_summary, to_markdown

log = structlog.get_logger()
BATCH = 500


def run_analysis(
    db: Session, storage: Storage, settings: Settings, analysis_id: uuid.UUID
) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise LookupError(f"analysis {analysis_id} not found")
    artifact = analysis.artifact
    if artifact.storage_key is None or artifact.deleted_at is not None:
        analysis.status, analysis.error = "failed", "The file has expired and was deleted."
        db.commit()
        return analysis

    analysis.status, analysis.started_at, analysis.error = "running", datetime.now(UTC), None
    db.execute(delete(FindingRow).where(FindingRow.analysis_id == analysis.id))
    db.execute(delete(EntryIndex).where(EntryIndex.analysis_id == analysis.id))
    db.commit()

    try:
        offsets = load_offsets(storage, artifact.storage_key)
        batch: list[dict[str, Any]] = []
        aid = analysis.id

        def on_row(row: EntryRow) -> None:
            start, length = offsets[row.number - 1] if row.number <= len(offsets) else (None, None)
            batch.append(
                {
                    "analysis_id": aid,
                    "number": row.number,
                    "started_ms": row.started_ms,
                    "method": row.method[:16],
                    "url": row.url,
                    "host": row.host[:255],
                    "status": row.status,
                    "error": row.error,
                    "mime": row.mime,
                    "resource_type": row.resource_type,
                    "time_ms": row.time_ms,
                    "timings": row.timings,
                    "request_bytes": row.request_bytes,
                    "response_bytes": row.response_bytes,
                    "failed": row.failed,
                    "byte_offset": start,
                    "byte_length": length,
                }
            )
            if len(batch) >= BATCH:
                db.execute(insert(EntryIndex), batch)
                batch.clear()

        with closing(storage.reader(artifact.storage_key)) as source:
            result = process(
                source,
                trusted_redacted=True,
                keep_rows=False,
                on_row=on_row,
                limits=NO_LIMITS,
                config=RuleConfig(slow_ms=settings.slow_ms),
            )
        if batch:
            db.execute(insert(EntryIndex), batch)

        fields = result.redacted_log_fields
        pages = [
            str(p.get("title") or "") for p in fields.get("pages") or [] if isinstance(p, dict)
        ]
        browser = ""
        for key in ("browser", "creator"):
            value = fields.get(key)
            if isinstance(value, dict) and value.get("name"):
                browser = f"{value.get('name')} {value.get('version', '')}".strip()
                break
        summary = build_summary(
            result.findings,
            result.stats.to_dict(),
            str(artifact.redaction_summary.get("sentence", "")),
            pages=[p for p in pages if p],
            browser=browser,
            truncated=result.truncated,
            kb_url_template=settings.kb_url_template,
        )
        for position, finding in enumerate(result.findings):
            data = finding.to_dict()
            db.add(
                FindingRow(
                    analysis_id=analysis.id,
                    position=position,
                    rule_id=finding.rule_id,
                    severity=finding.severity.value,
                    entry_index=finding.entry,
                    title=finding.title,
                    cause=finding.cause,
                    next_step=finding.next_step,
                    confidence=finding.confidence,
                    kb=data["kb"],
                    entries=finding.entries[:500],
                    evidence=_jsonable(finding.evidence),
                )
            )
        analysis.summary = summary.to_dict()
        analysis.summary_md = to_markdown(summary)
        analysis.stats = {
            **result.stats.to_dict(),
            "truncated": result.truncated,
            "findings": len(result.findings),
        }
        analysis.engine_version = result.engine_version
        analysis.status = "done"
        analysis.finished_at = datetime.now(UTC)
        db.commit()
        log.info("analysis_done", analysis_id=str(analysis.id), findings=len(result.findings))
    except Exception as exc:
        db.rollback()
        failed = db.get(Analysis, analysis_id)
        if failed is None:
            raise
        analysis = failed
        analysis.status = "failed"
        analysis.error = (
            "The analysis failed unexpectedly. The redacted file is kept; try re-running it."
        )
        analysis.finished_at = datetime.now(UTC)
        db.commit()
        log.exception("analysis_failed", analysis_id=str(analysis_id), error=type(exc).__name__)
        raise
    return analysis


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
