"""Ticket tasks: analyse the HAR files on a tagged ticket, then post one private note.

Exactly one note per (ticket, analysis), even when:

* the helpdesk sends the same webhook twice → `webhook_receipts` is unique per delivery;
* the same attachment is seen again → `artifacts` is unique per (case, attachment);
* the note task runs twice at once → the `posted_notes` row is locked while posting;
* a worker dies after posting but before recording it → a retry first searches the
  ticket for the note's marker and records the existing note instead of posting again.
"""

from __future__ import annotations

import uuid
from contextlib import closing, suppress
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from hartriage.core.config import get_settings
from hartriage.core.metrics import NOTES
from hartriage.db.models import (
    Analysis,
    Artifact,
    Case,
    HelpdeskConnection,
    PostedNote,
    WebhookReceipt,
)
from hartriage.db.session import session_scope
from hartriage.helpdesk import registry
from hartriage.helpdesk.base import HelpdeskError, RateLimited
from hartriage.services import audit
from hartriage.services.analysis import run_analysis
from hartriage.services.intake import intake
from hartriage.storage.s3 import get_storage
from hartriage.summary.builder import Summary, to_html
from hartriage.worker.celery_app import app
from hartriage.worker.dispatch import enqueue_note, enqueue_ticket

log = structlog.get_logger()
ATTACHMENT_LIMITS = {"zendesk": 50 * 1024 * 1024, "freshdesk": 20 * 1024 * 1024}


def note_marker(analysis_id: uuid.UUID | str) -> str:
    return f"HAR Triage analysis {analysis_id}"


@app.task(name="hartriage.ingest_ticket", bind=True, max_retries=8)
def ingest_ticket(self: Task, receipt_id: str) -> None:
    settings = get_settings()
    storage = get_storage(settings)
    with session_scope() as db:
        receipt = db.get(WebhookReceipt, uuid.UUID(receipt_id))
        if receipt is None or receipt.ticket_id is None:
            return
        conn = db.get(HelpdeskConnection, receipt.connection_id)
        if conn is None:
            return
        client = registry.client(settings, conn)
        try:
            ticket = client.get_ticket(receipt.ticket_id)
        except RateLimited as exc:
            raise self.retry(countdown=exc.retry_after) from exc
        except HelpdeskError as exc:
            receipt.outcome = "ticket_unreadable"
            conn.last_webhook_status = f"error: {exc}"[:40]
            log.warning("ticket_unreadable", connection=str(conn.id), error=str(exc))
            return
        if settings.trigger_tag not in ticket.tags:
            # The API is the source of truth, not the webhook payload.
            receipt.outcome = "tag_not_present"
            return
        case = db.scalar(
            select(Case).where(Case.connection_id == conn.id, Case.external_ticket_id == ticket.id)
        )
        if case is None:
            case = Case(
                org_id=conn.org_id,
                connection_id=conn.id,
                external_ticket_id=ticket.id,
                title=ticket.subject[:300],
            )
            db.add(case)
            db.flush()
        # Never analyse our own output: the redacted copies attached to our notes.
        own_notes = {
            str(c)
            for c in db.scalars(
                select(PostedNote.platform_comment_id).where(PostedNote.case_id == case.id)
            )
            if c
        }
        hars = [
            a
            for a in ticket.attachments
            if a.is_har
            and a.comment_id not in own_notes
            and not a.filename.lower().endswith((".redacted.har", ".redacted.har.gz"))
        ]
        new = 0
        queued: list[uuid.UUID] = []
        for attachment in hars:
            seen = db.scalar(
                select(Artifact).where(
                    Artifact.case_id == case.id, Artifact.external_attachment_id == attachment.id
                )
            )
            if seen is not None:
                continue
            try:
                with client.open_attachment(attachment, settings.max_upload_bytes) as stream:
                    analysis = intake(
                        db,
                        storage,
                        settings,
                        stream,
                        org_id=conn.org_id,
                        source_kind="ticket",
                        filename=attachment.filename,
                        case_id=case.id,
                        external_attachment_id=attachment.id,
                    )
                db.commit()
            except RateLimited as exc:
                db.rollback()
                raise self.retry(countdown=exc.retry_after) from exc
            except IntegrityError:
                db.rollback()  # another worker took this attachment
                continue
            except Exception as exc:
                db.rollback()
                log.warning("attachment_failed", attachment=attachment.id, error=str(exc)[:200])
                continue
            new += 1
            audit.record(
                db,
                org_id=conn.org_id,
                actor=None,
                action="analysis.from_ticket",
                target_type="analysis",
                target_id=analysis.id,
                ticket=ticket.id,
            )
            db.commit()
            queued.append(analysis.id)
        # Every new file is recorded (status queued) before any is analysed, so the
        # first note can tell that more are coming and leaves the tag for the last.
        for analysis_id in queued:
            run_analysis(db, storage, settings, analysis_id)
            enqueue_note(analysis_id)
        receipt.outcome = (
            "analysed" if new else ("no_har_attachment" if not hars else "already_analysed")
        )
        if not new:
            # Nothing to post (no HAR file, or every one was analysed before): still
            # take the trigger tag off, so the agent sees the request was handled.
            # When there are new analyses, the note task swaps the tag after posting.
            with suppress(HelpdeskError):
                client.swap_tags(ticket, settings.trigger_tag, settings.done_tag)
        client.close()


def notes_outstanding(db: Any, case_id: uuid.UUID) -> int:
    """Analyses of this ticket's HAR files that will still get a note: queued, running,
    or done without a posted note. Failed analyses never get one, so they don't count."""
    posted = (
        select(PostedNote.id)
        .where(PostedNote.analysis_id == Analysis.id, PostedNote.status == "posted")
        .exists()
    )
    return int(
        db.scalar(
            select(func.count())
            .select_from(Analysis)
            .join(Artifact, Analysis.artifact_id == Artifact.id)
            .where(
                Artifact.case_id == case_id,
                or_(
                    Analysis.status.in_(("queued", "running")),
                    and_(Analysis.status == "done", ~posted),
                ),
            )
        )
        or 0
    )


@app.task(name="hartriage.post_note", bind=True, max_retries=8)
def post_note(self: Task, analysis_id: str) -> None:
    settings = get_settings()
    storage = get_storage(settings)
    with session_scope() as db:
        analysis = db.get(Analysis, uuid.UUID(analysis_id))
        if analysis is None or analysis.status != "done" or analysis.artifact.case_id is None:
            return
        case = db.get(Case, analysis.artifact.case_id)
        conn = (
            db.get(HelpdeskConnection, case.connection_id) if case and case.connection_id else None
        )
        if case is None or conn is None or not case.external_ticket_id:
            return
        note = db.scalar(
            select(PostedNote).where(
                PostedNote.case_id == case.id, PostedNote.analysis_id == analysis.id
            )
        )
        if note is None:
            try:
                with db.begin_nested():
                    note = PostedNote(case_id=case.id, analysis_id=analysis.id)
                    db.add(note)
                db.commit()
            except IntegrityError:
                db.rollback()
        # Hold the row lock until the note is recorded: a second task waits here.
        note = db.scalar(
            select(PostedNote)
            .where(PostedNote.case_id == case.id, PostedNote.analysis_id == analysis.id)
            .with_for_update()
        )
        assert note is not None  # noqa: S101 - created above
        if note.status == "posted":
            return
        marker = note_marker(analysis.id)
        client = registry.client(settings, conn)
        try:
            ticket = client.get_ticket(case.external_ticket_id)
            existing = client.find_note(ticket.id, marker) if note.attempts else None
            if existing is None:
                note.attempts += 1
                summary = Summary(**(analysis.summary or {}))
                html = to_html(
                    summary,
                    title=f"HAR Triage: {analysis.artifact.original_filename}",
                    marker=marker,
                )
                cleaned = None
                key = analysis.artifact.storage_key
                if (
                    conn.replace_attachments
                    and key
                    and analysis.artifact.size_bytes <= ATTACHMENT_LIMITS[conn.platform]
                ):
                    with closing(storage.reader(key)) as body:
                        name = (analysis.artifact.original_filename or "file.har").rsplit(".", 1)[0]
                        cleaned = (f"{name}.redacted.har", body.read())
                existing = client.post_private_note(ticket, html, cleaned)
                if cleaned is not None:
                    original = next(
                        (
                            a
                            for a in ticket.attachments
                            if a.id == analysis.artifact.external_attachment_id
                        ),
                        None,
                    )
                    if original is not None:
                        client.remove_attachment(ticket, original)
                        audit.record(
                            db,
                            org_id=conn.org_id,
                            actor=None,
                            action="attachment.replaced",
                            target_type="ticket",
                            target_id=ticket.id,
                        )
            note.status, note.platform_comment_id, note.posted_at = (
                "posted",
                existing,
                datetime.now(UTC),
            )
            note.last_error = None
            db.commit()
            NOTES.labels(conn.platform, "posted").inc()
            # Only say "analysed" once it is true for every HAR on the ticket: with
            # several files, the earlier notes leave the tag for the last one. Each
            # task commits its own note before checking, so the last to finish sees
            # all of them posted (two finishing together both swap, which is harmless).
            if not notes_outstanding(db, case.id):
                try:
                    client.swap_tags(ticket, settings.trigger_tag, settings.done_tag)
                except HelpdeskError as exc:
                    log.warning("tag_swap_failed", error=str(exc))
        except RateLimited as exc:
            note.last_error = str(exc)
            db.commit()
            NOTES.labels(conn.platform, "rate_limited").inc()
            raise self.retry(countdown=exc.retry_after) from exc
        except HelpdeskError as exc:
            note.last_error = str(exc)[:500]
            if self.request.retries >= self.max_retries:
                note.status = "failed"
            db.commit()
            NOTES.labels(conn.platform, "error").inc()
            raise self.retry(countdown=min(600, 15 * 2**self.request.retries)) from exc
        finally:
            client.close()


@app.task(name="hartriage.poll_tagged_tickets")
def poll_tagged_tickets() -> int:
    """Find tagged tickets on helpdesks whose automations can't fire on a tag change
    (Freshdesk), and ingest each one exactly as if its webhook had arrived.

    A ticket is recorded once per version (id + updated_at), so a ticket that stays
    tagged is not re-queued every minute, while a re-tagged ticket is picked up again.
    """
    settings = get_settings()
    if settings.freshdesk_poll_seconds <= 0:
        return 0
    queued: list[uuid.UUID] = []
    with session_scope() as db:
        connections = db.scalars(
            select(HelpdeskConnection).where(HelpdeskConnection.platform == "freshdesk")
        ).all()
        for conn in connections:
            client = registry.client(settings, conn)
            try:
                tagged = client.tagged_tickets(settings.trigger_tag)
            except HelpdeskError as exc:
                log.warning("poll_failed", connection=str(conn.id), error=str(exc))
                conn.last_webhook_status = f"poll error: {exc}"[:40]
                db.commit()
                continue
            finally:
                client.close()
            for ticket_id, updated_at in tagged:
                receipt = WebhookReceipt(
                    connection_id=conn.id,
                    delivery_key=f"poll:{ticket_id}:{updated_at}"[:200],
                    ticket_id=ticket_id,
                )
                try:
                    with db.begin_nested():
                        db.add(receipt)
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    continue
                conn.last_webhook_at = datetime.now(UTC)
                conn.last_webhook_status = f"polled: ticket {ticket_id}"
                db.commit()
                queued.append(receipt.id)
    for receipt_id in queued:
        enqueue_ticket(receipt_id)
    return len(queued)
