"""Analyses: history, status, findings, the waterfall, request detail and exports."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from hartriage.api.deps import AdminDep, AgentDep, DbDep, PrincipalDep, SettingsDep, StorageDep
from hartriage.core.errors import AppError, NotFound
from hartriage.db.models import (
    Analysis,
    Artifact,
    AuditLog,
    Case,
    EntryIndex,
    FindingRow,
    HelpdeskConnection,
    User,
)
from hartriage.rules.base import Finding, Severity
from hartriage.services import audit
from hartriage.services.retention import purge
from hartriage.summary.builder import Summary, evidence_lines, to_html, to_markdown, to_text
from hartriage.worker.dispatch import enqueue_analysis

router = APIRouter(prefix="/analyses", tags=["analyses"])


def visible_to(principal: PrincipalDep, analysis: Analysis) -> bool:
    """Admins see every analysis in their organisation. Agents and viewers see only the
    files they uploaded; a file that came from a helpdesk ticket has no uploader, so it
    is visible to admins only (see docs/decisions/0013-own-files-only.md)."""
    if analysis.org_id != principal.org_id:
        return False
    return principal.role == "admin" or analysis.created_by == principal.user_id


def get_owned(db: DbDep, principal: PrincipalDep, analysis_id: uuid.UUID) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    # Someone else's analysis is "not found", never "forbidden": ids leak nothing.
    if analysis is None or not visible_to(principal, analysis):
        raise NotFound("Analysis not found.")
    return analysis


def _source(db: DbDep, artifact: Artifact) -> dict[str, Any]:
    data: dict[str, Any] = {"kind": artifact.source}
    if artifact.case_id:
        case = db.get(Case, artifact.case_id)
        if case and case.connection_id:
            conn = db.get(HelpdeskConnection, case.connection_id)
            if conn:
                data.update(
                    platform=conn.platform,
                    ticket_id=case.external_ticket_id,
                    ticket_url=ticket_url(conn, case.external_ticket_id or ""),
                )
    return data


def ticket_url(conn: HelpdeskConnection, ticket_id: str) -> str:
    if conn.platform == "zendesk":
        return f"https://{conn.subdomain}.zendesk.com/agent/tickets/{ticket_id}"
    return f"https://{conn.subdomain}.freshdesk.com/a/tickets/{ticket_id}"


def _uploader(db: DbDep, a: Analysis) -> dict[str, str] | None:
    if a.created_by is None:
        return None
    user = db.get(User, a.created_by)
    return {
        "id": str(a.created_by),
        "name": user.name if user else "",
        "email": user.email if user else "",
    }


def serialize(db: DbDep, a: Analysis, *, full: bool = False) -> dict[str, Any]:
    art = a.artifact
    data: dict[str, Any] = {
        "id": str(a.id),
        "status": a.status,
        "error": a.error,
        "engine_version": a.engine_version,
        "created_at": a.created_at.isoformat(),
        "finished_at": a.finished_at.isoformat() if a.finished_at else None,
        "filename": art.original_filename,
        "size_bytes": art.size_bytes,
        "original_size_bytes": art.original_size_bytes,
        "entry_count": art.entry_count,
        "expires_at": art.expires_at.isoformat(),
        "source": _source(db, art),
        "redaction": art.redaction_summary,
        "stats": a.stats,
        "lead": (a.summary or {}).get("likely_cause"),
        "uploaded_by": _uploader(db, a),
    }
    if full:
        data["summary"] = a.summary
        data["summary_md"] = a.summary_md
        data["sha256_of_redacted"] = art.sha256_of_redacted
    return data


@router.get("")
def list_analyses(
    principal: PrincipalDep,
    db: DbDep,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = None,
    q: str | None = Query(None, max_length=100),
    scope: Literal["mine", "all"] = "all",
    source: Literal["upload", "cli", "ticket"] | None = None,
    status: Literal["queued", "running", "done", "failed"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    stmt = (
        select(Analysis)
        .join(Artifact, Artifact.id == Analysis.artifact_id)
        .where(Analysis.org_id == principal.org_id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
    )
    # Agents and viewers only ever list their own files; admins can narrow to theirs.
    if principal.role != "admin" or scope == "mine":
        stmt = stmt.where(Analysis.created_by == principal.user_id)
    if source:
        stmt = stmt.where(Artifact.source == source)
    if status:
        stmt = stmt.where(Analysis.status == status)
    if since:
        stmt = stmt.where(Analysis.created_at >= since)
    if until:
        stmt = stmt.where(Analysis.created_at < until)
    if q:
        stmt = stmt.where(Artifact.original_filename.ilike(f"%{q}%"))
    if cursor:
        try:
            anchor = db.get(Analysis, uuid.UUID(cursor))
        except ValueError as exc:
            raise AppError("Invalid cursor.", code="invalid_cursor") from exc
        if anchor is not None and visible_to(principal, anchor):
            stmt = stmt.where(
                or_(
                    Analysis.created_at < anchor.created_at,
                    (Analysis.created_at == anchor.created_at) & (Analysis.id < anchor.id),
                )
            )
    rows = db.scalars(stmt.limit(limit + 1)).all()
    items = [serialize(db, a) for a in rows[:limit]]
    return {"items": items, "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None}


@router.get("/{analysis_id}")
def get_analysis(analysis_id: uuid.UUID, principal: PrincipalDep, db: DbDep) -> dict[str, Any]:
    analysis = get_owned(db, principal, analysis_id)
    recently_viewed = db.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.actor_user_id == principal.user_id,
            AuditLog.action == "analysis.viewed",
            AuditLog.target_id == str(analysis.id),
            AuditLog.at > datetime.now(UTC) - timedelta(minutes=30),
        )
        .limit(1)
    )
    if analysis.status == "done" and recently_viewed is None:
        audit.record(
            db,
            org_id=principal.org_id,
            actor=principal.user_id,
            action="analysis.viewed",
            target_type="analysis",
            target_id=analysis.id,
        )
        db.commit()
    return serialize(db, analysis, full=True)


@router.get("/{analysis_id}/findings")
def findings(analysis_id: uuid.UUID, principal: PrincipalDep, db: DbDep) -> dict[str, Any]:
    analysis = get_owned(db, principal, analysis_id)
    rows = db.scalars(
        select(FindingRow)
        .where(FindingRow.analysis_id == analysis.id)
        .order_by(FindingRow.position)
    ).all()
    return {
        "items": [
            {
                "id": str(f.id),
                "rule_id": f.rule_id,
                "severity": f.severity,
                "title": f.title,
                "cause": f.cause,
                "next_step": f.next_step,
                "confidence": f.confidence,
                "kb": f.kb,
                "entry": f.entry_index,
                "entries": f.entries,
                "evidence": f.evidence,
                "evidence_lines": evidence_lines(
                    Finding(
                        rule_id=f.rule_id,
                        severity=Severity(f.severity),
                        title=f.title,
                        cause=f.cause,
                        next_step=f.next_step,
                        entries=list(f.entries),
                        evidence=dict(f.evidence),
                        confidence=f.confidence,
                    )
                ),
            }
            for f in rows
        ]
    }


@router.get("/{analysis_id}/entries")
def entries(
    analysis_id: uuid.UUID,
    principal: PrincipalDep,
    db: DbDep,
    status: Literal["all", "failed", "2xx", "3xx", "4xx", "5xx", "none"] = "all",
    host: str | None = Query(None, max_length=255),
    min_ms: float | None = Query(None, ge=0),
    numbers: str | None = Query(
        None, max_length=2000, description="Comma-separated request numbers"
    ),
    cursor: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
) -> dict[str, Any]:
    analysis = get_owned(db, principal, analysis_id)
    stmt = select(EntryIndex).where(
        EntryIndex.analysis_id == analysis.id, EntryIndex.number > cursor
    )
    if status == "failed":
        stmt = stmt.where(EntryIndex.failed.is_(True))
    elif status == "none":
        stmt = stmt.where(EntryIndex.status == 0)
    elif status != "all":
        base = int(status[0]) * 100
        stmt = stmt.where(EntryIndex.status >= base, EntryIndex.status < base + 100)
    if host:
        stmt = stmt.where(EntryIndex.host == host.lower())
    if min_ms is not None:
        stmt = stmt.where(EntryIndex.time_ms >= min_ms)
    if numbers:
        try:
            wanted = [int(n) for n in numbers.split(",") if n.strip()][:500]
        except ValueError as exc:
            raise AppError(
                "numbers must be comma-separated integers.", code="invalid_numbers"
            ) from exc
        stmt = stmt.where(EntryIndex.number.in_(wanted))
    rows = db.scalars(stmt.order_by(EntryIndex.number).limit(limit + 1)).all()
    hosts = db.execute(
        select(EntryIndex.host, func.count())
        .where(EntryIndex.analysis_id == analysis.id)
        .group_by(EntryIndex.host)
        .order_by(func.count().desc())
        .limit(50)
    ).all()
    return {
        "items": [
            {
                "number": e.number,
                "started_ms": e.started_ms,
                "method": e.method,
                "url": e.url,
                "host": e.host,
                "status": e.status,
                "error": e.error,
                "mime": e.mime,
                "resource_type": e.resource_type,
                "time_ms": e.time_ms,
                "timings": e.timings,
                "request_bytes": e.request_bytes,
                "response_bytes": e.response_bytes,
                "failed": e.failed,
            }
            for e in rows[:limit]
        ],
        "next_cursor": rows[limit - 1].number if len(rows) > limit else None,
        "hosts": [{"host": h, "count": c} for h, c in hosts],
    }


@router.get("/{analysis_id}/entries/{number}")
def entry_detail(
    analysis_id: uuid.UUID, number: int, principal: PrincipalDep, db: DbDep, storage: StorageDep
) -> dict[str, Any]:
    """One request, read from the redacted file with a byte-range read."""
    analysis = get_owned(db, principal, analysis_id)
    row = db.get(EntryIndex, (analysis.id, number))
    key = analysis.artifact.storage_key
    if row is None or row.byte_offset is None or row.byte_length is None or key is None:
        raise NotFound("Request not found.")
    raw = json.loads(storage.read_range(key, row.byte_offset, row.byte_length))
    meta = raw.pop("_hartriage", {})
    return {"number": number, "entry": raw, "meta": meta}


def _summary(analysis: Analysis) -> Summary:
    if analysis.status != "done" or not analysis.summary:
        raise AppError("The analysis has not finished yet.", code="not_ready", status=409)
    return Summary(**analysis.summary)


@router.get("/{analysis_id}/export")
def export(
    analysis_id: uuid.UUID,
    principal: PrincipalDep,
    db: DbDep,
    format: Literal["md", "txt", "json", "html"] = "md",
) -> Response:
    analysis = get_owned(db, principal, analysis_id)
    summary = _summary(analysis)
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="analysis.exported",
        target_type="analysis",
        target_id=analysis.id,
        format=format,
    )
    db.commit()
    if format == "json":
        rows = db.scalars(
            select(FindingRow)
            .where(FindingRow.analysis_id == analysis.id)
            .order_by(FindingRow.position)
        ).all()
        payload = {
            "summary": analysis.summary,
            "stats": analysis.stats,
            "redaction": analysis.artifact.redaction_summary,
            "engine_version": analysis.engine_version,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "title": f.title,
                    "cause": f.cause,
                    "next_step": f.next_step,
                    "entries": f.entries,
                    "evidence": f.evidence,
                    "kb": f.kb,
                }
                for f in rows
            ],
        }
        return Response(
            json.dumps(payload, indent=2, ensure_ascii=False), media_type="application/json"
        )
    if format == "txt":
        return PlainTextResponse(to_text(summary))
    if format == "html":
        return Response(to_html(summary), media_type="text/html; charset=utf-8")
    return PlainTextResponse(to_markdown(summary), media_type="text/markdown; charset=utf-8")


@router.get("/{analysis_id}/redacted.har")
def download_redacted(
    analysis_id: uuid.UUID, principal: AgentDep, db: DbDep, storage: StorageDep
) -> StreamingResponse:
    analysis = get_owned(db, principal, analysis_id)
    key = analysis.artifact.storage_key
    if key is None:
        raise NotFound("The file has expired and was deleted.")
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="analysis.downloaded",
        target_type="analysis",
        target_id=analysis.id,
    )
    db.commit()

    def chunks() -> Iterator[bytes]:
        with closing(storage.reader(key)) as body:
            while chunk := body.read(256 * 1024):
                yield chunk

    name = (analysis.artifact.original_filename or "file.har").rsplit(".", 1)[0] + ".redacted.har"
    return StreamingResponse(
        chunks(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/{analysis_id}/rerun", status_code=202)
def rerun(analysis_id: uuid.UUID, principal: AgentDep, db: DbDep) -> dict[str, str]:
    analysis = get_owned(db, principal, analysis_id)
    if analysis.artifact.storage_key is None:
        raise NotFound("The file has expired and was deleted.")
    if analysis.status in ("queued", "running"):
        raise AppError("The analysis is already running.", code="already_running", status=409)
    analysis.status = "queued"
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="analysis.rerun",
        target_type="analysis",
        target_id=analysis.id,
    )
    db.commit()
    enqueue_analysis(analysis.id)
    return {"analysis_id": str(analysis.id), "status": "queued"}


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(
    analysis_id: uuid.UUID,
    principal: AgentDep,
    db: DbDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> Response:
    """Agents delete their own uploads; admins delete any file, including ticket files.
    The redacted copy is purged from storage at once and the deletion is audited."""
    analysis = get_owned(db, principal, analysis_id)
    purge(db, storage, analysis.artifact, reason="deleted", actor=principal.user_id)
    db.commit()
    return Response(status_code=204)


class BulkDelete(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


@router.post("/bulk-delete")
def bulk_delete(
    body: BulkDelete, principal: AdminDep, db: DbDep, storage: StorageDep
) -> dict[str, int]:
    """Admins: delete several files at once. Ids that aren't visible are skipped."""
    deleted = 0
    for analysis_id in dict.fromkeys(body.ids):
        analysis = db.get(Analysis, analysis_id)
        if (
            analysis is None
            or not visible_to(principal, analysis)
            or analysis.artifact.deleted_at is not None
        ):
            continue
        purge(db, storage, analysis.artifact, reason="deleted", actor=principal.user_id)
        deleted += 1
    db.commit()
    return {"deleted": deleted}
