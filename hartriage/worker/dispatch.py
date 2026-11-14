"""Enqueue tasks. Kept apart from tasks.py so the API can import it cheaply."""

from __future__ import annotations

import uuid
from typing import Any

from celery.exceptions import Retry


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


def enqueue_note(analysis_id: uuid.UUID | str) -> None:
    from hartriage.helpdesk.tasks import post_note

    _delay(post_note, str(analysis_id))


def enqueue_ticket(receipt_id: uuid.UUID | str) -> None:
    from hartriage.helpdesk.tasks import ingest_ticket

    _delay(ingest_ticket, str(receipt_id))
