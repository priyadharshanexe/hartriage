"""Delete stored objects that no artifact row owns, and abandoned multipart uploads.

Intake deletes its objects itself whenever it fails or its transaction rolls back.
This catches what that can't: a process killed between writing an object and
committing its row, or a delete that failed because storage was down.

Safe against uploads in flight: an object without a row is only deleted when it is
older than `min_age` (hours; an upload takes minutes at most), and the row is
looked up for every object, so one committed in the meantime keeps its objects.
Objects of a purged artifact (its row says deleted) are removed at any age.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from hartriage.core.metrics import ORPHANS
from hartriage.db.models import Artifact
from hartriage.storage.s3 import Storage

log = structlog.get_logger()
KEY = re.compile(r"^orgs/(?P<org>[0-9a-f-]{36})/artifacts/(?P<artifact>[0-9a-f-]{36})/")


def reconcile(
    db: Session, storage: Storage, *, min_age: timedelta = timedelta(hours=6)
) -> dict[str, int]:
    cutoff = datetime.now(UTC) - min_age
    counts = {"orphans": 0, "purged": 0, "uploads": 0, "kept": 0}
    for obj in list(storage.list("orgs/")):
        match = KEY.match(obj.key)
        if match is None:
            continue
        row = db.execute(
            select(Artifact.org_id, Artifact.deleted_at).where(
                Artifact.id == uuid.UUID(match["artifact"])
            )
        ).first()
        if row is not None and str(row.org_id) != match["org"]:
            log.warning("object_under_wrong_org", key=obj.key)
            continue
        if row is not None and row.deleted_at is None:
            counts["kept"] += 1
            continue
        reason = "purged" if row is not None else "orphan"
        if reason == "orphan" and obj.modified > cutoff:
            counts["kept"] += 1  # may be an upload whose row is about to commit
            continue
        try:
            storage.delete(obj.key)
        except Exception as exc:
            log.warning("reconcile_delete_failed", key=obj.key, error=type(exc).__name__)
            continue
        ORPHANS.labels(f"reconciled_{reason}").inc()
        counts["orphans" if reason == "orphan" else "purged"] += 1
    for upload in list(storage.open_uploads("orgs/")):
        if upload.started > cutoff:
            continue
        try:
            storage.abort_upload(upload)
        except Exception as exc:
            log.warning("reconcile_abort_failed", key=upload.key, error=type(exc).__name__)
            continue
        ORPHANS.labels("reconciled_upload").inc()
        counts["uploads"] += 1
    log.info("storage_reconciled", **counts)
    return counts
