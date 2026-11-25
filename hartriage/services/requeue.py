"""Send again the work whose task never arrived or never finished.

The database row is written (and committed) before its task is sent, so it is the
record of what should happen; the broker message is only the nudge. If the nudge is
lost (Redis down at the moment of sending, a worker killed and its message gone,
Postgres down when the task tried to record its outcome), this sweep finds the row
and sends the task again. Every task is safe to run twice, so a duplicate costs
time, not correctness.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from hartriage.db.models import Analysis, Artifact, PostedNote

log = structlog.get_logger()

QUEUED_GRACE = timedelta(minutes=5)  # a task normally starts within seconds
RUNNING_GRACE = timedelta(hours=2)  # longer than the broker's visibility timeout (1 h)
NOTE_GRACE = timedelta(minutes=10)
GIVE_UP = timedelta(days=1)  # don't retry forever something that keeps failing


def stale_analyses(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    now = now or datetime.now(UTC)
    rows = db.scalars(
        select(Analysis.id).where(
            Analysis.created_at > now - GIVE_UP,
            or_(
                and_(Analysis.status == "queued", Analysis.created_at < now - QUEUED_GRACE),
                and_(Analysis.status == "running", Analysis.started_at < now - RUNNING_GRACE),
            ),
        )
    )
    return list(rows)


def notes_never_sent(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    """Ticket analyses that finished, but whose note was never posted (or never started)."""
    now = now or datetime.now(UTC)
    posted = exists().where(
        PostedNote.analysis_id == Analysis.id,
        PostedNote.status.in_(("posted", "failed")),
    )
    rows = db.scalars(
        select(Analysis.id)
        .join(Artifact, Artifact.id == Analysis.artifact_id)
        .where(
            Artifact.case_id.is_not(None),
            Artifact.deleted_at.is_(None),
            Analysis.status == "done",
            Analysis.finished_at < now - NOTE_GRACE,
            Analysis.finished_at > now - GIVE_UP,
            ~posted,
        )
    )
    return list(rows)
