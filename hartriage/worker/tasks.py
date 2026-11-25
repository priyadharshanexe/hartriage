"""Background tasks: analyse a stored file, process a helpdesk ticket, post its note,
and the hourly retention sweep."""

from __future__ import annotations

import time
import uuid

import structlog

from hartriage.core.config import get_settings
from hartriage.core.metrics import ANALYSES, ANALYSIS_SECONDS, FINDINGS, SECRETS
from hartriage.db.models import Analysis, FindingRow
from hartriage.db.session import session_scope
from hartriage.services import analysis as analysis_service
from hartriage.services import reconcile, requeue, retention
from hartriage.storage.s3 import get_storage
from hartriage.worker.celery_app import app

log = structlog.get_logger()


@app.task(name="hartriage.analyse", bind=True, max_retries=3, default_retry_delay=10)
def analyse(self: object, analysis_id: str) -> None:
    settings = get_settings()
    started = time.perf_counter()
    with session_scope() as db:
        result = analysis_service.run_analysis(
            db, get_storage(settings), settings, uuid.UUID(analysis_id)
        )
        ANALYSES.labels(result.status).inc()
        if result.status == "done":
            for (rule_id,) in db.query(FindingRow.rule_id).filter(
                FindingRow.analysis_id == result.id
            ):
                FINDINGS.labels(rule_id).inc()
            SECRETS.inc(int(result.artifact.redaction_summary.get("total_secrets", 0)))
    ANALYSIS_SECONDS.observe(time.perf_counter() - started)
    after_analysis(analysis_id)


def after_analysis(analysis_id: str) -> None:
    """If the file came from a ticket, post the note (a separate task, retried on its own)."""
    with session_scope() as db:
        analysis = db.get(Analysis, uuid.UUID(analysis_id))
        if analysis is None or analysis.status != "done" or analysis.artifact.case_id is None:
            return
    from hartriage.worker.dispatch import enqueue_note

    enqueue_note(analysis_id)


@app.task(name="hartriage.retention_sweep")
def retention_sweep() -> int:
    settings = get_settings()
    with session_scope() as db:
        return retention.sweep(db, get_storage(settings))


@app.task(name="hartriage.reconcile_storage")
def reconcile_storage() -> dict[str, int]:
    settings = get_settings()
    with session_scope() as db:
        return reconcile.reconcile(db, get_storage(settings))


@app.task(name="hartriage.requeue_stale")
def requeue_stale() -> int:
    """Send again analyses and notes whose task was lost (see services/requeue.py)."""
    from hartriage.worker.dispatch import enqueue_analysis, enqueue_note

    with session_scope() as db:
        analyses = requeue.stale_analyses(db)
        notes = requeue.notes_never_sent(db)
    for analysis_id in analyses:
        log.info("requeued", task="analyse", analysis_id=str(analysis_id))
        enqueue_analysis(analysis_id)
    for analysis_id in notes:
        log.info("requeued", task="post_note", analysis_id=str(analysis_id))
        enqueue_note(analysis_id)
    return len(analyses) + len(notes)


# Helpdesk tasks are defined next to the clients they drive.
from hartriage.helpdesk import tasks as _helpdesk_tasks  # noqa: E402,F401
