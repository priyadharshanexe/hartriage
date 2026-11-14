"""Retention: expired files are deleted from storage and their analyses from the database.

The artifact row stays as a tombstone (no filename, no storage key) so the audit
log still points at something; everything that described the file's contents is
gone. The bucket's lifecycle rule is a backstop if this job ever stops running.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hartriage.db.models import Analysis, Artifact
from hartriage.services import audit
from hartriage.services.intake import index_key
from hartriage.storage.s3 import Storage

log = structlog.get_logger()


def sweep(db: Session, storage: Storage, *, now: datetime | None = None, batch: int = 100) -> int:
    now = now or datetime.now(UTC)
    deleted = 0
    while True:
        rows = db.scalars(
            select(Artifact)
            .where(Artifact.deleted_at.is_(None), Artifact.expires_at <= now)
            .order_by(Artifact.expires_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
        ).all()
        if not rows:
            break
        for artifact in rows:
            purge(db, storage, artifact, reason="expired")
            deleted += 1
        db.commit()
    if deleted:
        log.info("retention_sweep", deleted=deleted)
    return deleted


def purge(
    db: Session,
    storage: Storage,
    artifact: Artifact,
    *,
    reason: str,
    actor: uuid.UUID | None = None,
) -> None:
    if artifact.storage_key:
        storage.delete(artifact.storage_key)
        storage.delete(index_key(artifact.storage_key))
    db.execute(
        delete(Analysis).where(Analysis.artifact_id == artifact.id)
    )  # findings, entries cascade
    artifact.storage_key = None
    artifact.original_filename = None
    artifact.redaction_summary = {}
    artifact.deleted_at = datetime.now(UTC)
    audit.record(
        db,
        org_id=artifact.org_id,
        actor=actor,
        action=f"artifact.{reason}",
        target_type="artifact",
        target_id=artifact.id,
    )
