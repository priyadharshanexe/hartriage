"""Enqueue tasks. Kept apart from tasks.py so the API can import it cheaply."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from celery.exceptions import Retry

log = structlog.get_logger()


def _delay(task: Any, *args: str) -> None:
    try:
        task.delay(*args)
    except Retry as exc:
        # Only when tasks run inline (tests, demos without a worker): Celery raises the
        # retry instead of scheduling it, so run it here, as a worker would later.
        for _ in range(int(getattr(task, "max_retries", 3) or 3)):
            if exc.sig is None:
                return
            try:
                exc.sig.apply()
                return
            except Retry as again:
                exc = again


def enqueue_analysis(analysis_id: uuid.UUID | str) -> None:
    from hartriage.worker.tasks import analyse

    _delay(analyse, str(analysis_id))


def try_enqueue(send: Any, analysis_id: uuid.UUID | str) -> bool:
    """Send a task after its row is committed. If the broker is unreachable the row
    stays "queued" and the requeue sweep sends it later: the request itself succeeded,
    so the caller must not report a failure for it."""
    try:
        send(analysis_id)
    except Exception as exc:
        from kombu.exceptions import OperationalError

        if not isinstance(exc, OperationalError | ConnectionError | OSError):
            raise
        log.warning("enqueue_failed", analysis_id=str(analysis_id), error=type(exc).__name__)
        return False
    return True


def enqueue_note(analysis_id: uuid.UUID | str) -> None:
    from hartriage.helpdesk.tasks import post_note

    _delay(post_note, str(analysis_id))


def enqueue_ticket(receipt_id: uuid.UUID | str) -> None:
    from hartriage.helpdesk.tasks import ingest_ticket

    _delay(ingest_ticket, str(receipt_id))
