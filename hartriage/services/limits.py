"""An organisation's limits (set by its admins, capped by the server) and its usage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hartriage.core.config import Settings
from hartriage.db.models import Analysis, Artifact, Membership, OrgSettings, User

RETENTION_CHOICES = (7, 30, 90)
MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    retention_days: int
    max_bytes: int
    quota_bytes: int | None
    daily_uploads: int | None


def limits_for(db: Session, settings: Settings, org_id: uuid.UUID) -> Limits:
    row = db.get(OrgSettings, org_id)
    server_max = settings.max_upload_bytes
    if row is None:
        return Limits(settings.retention_days, server_max, None, None)
    return Limits(
        retention_days=row.retention_days,
        max_bytes=min(server_max, row.max_file_mb * MB) if row.max_file_mb else server_max,
        quota_bytes=row.storage_quota_mb * MB if row.storage_quota_mb else None,
        daily_uploads=row.daily_uploads_per_member,
    )


def storage_used(db: Session, org_id: uuid.UUID) -> int:
    """Bytes of redacted files still stored (expired and deleted files are gone)."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Artifact.size_bytes), 0)).where(
                Artifact.org_id == org_id, Artifact.deleted_at.is_(None)
            )
        )
        or 0
    )


def uploads_today(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    return int(
        db.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(
                Analysis.org_id == org_id,
                Analysis.created_by == user_id,
                Analysis.created_at >= since,
            )
        )
        or 0
    )


def usage_by_member(db: Session, org_id: uuid.UUID) -> list[dict[str, object]]:
    rows = db.execute(
        select(
            User.id,
            User.name,
            User.email,
            func.coalesce(func.sum(Artifact.size_bytes), 0),
            func.count(Artifact.id),
        )
        .select_from(Membership)
        .join(User, User.id == Membership.user_id)
        .outerjoin(
            Analysis,
            (Analysis.created_by == User.id) & (Analysis.org_id == org_id),
        )
        .outerjoin(Artifact, (Artifact.id == Analysis.artifact_id) & Artifact.deleted_at.is_(None))
        .where(Membership.org_id == org_id)
        .group_by(User.id, User.name, User.email)
        .order_by(func.coalesce(func.sum(Artifact.size_bytes), 0).desc())
    ).all()
    tickets = int(
        db.scalar(
            select(func.coalesce(func.sum(Artifact.size_bytes), 0)).where(
                Artifact.org_id == org_id,
                Artifact.deleted_at.is_(None),
                Artifact.source == "ticket",
            )
        )
        or 0
    )
    members = [
        {"user_id": str(uid), "name": name, "email": email, "bytes": int(b), "files": int(n)}
        for uid, name, email, b, n in rows
    ]
    return [
        *members,
        {
            "user_id": None,
            "name": "Helpdesk tickets",
            "email": None,
            "bytes": tickets,
            "files": None,
        },
    ]
