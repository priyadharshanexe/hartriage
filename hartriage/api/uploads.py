"""Uploads. The request body is streamed through redaction as it arrives:

    browser ──chunks──▶ event loop ──queue──▶ worker thread: parse → redact → S3 multipart

The raw bytes exist only in those in-flight chunks. Nothing unredacted is ever
written to disk, a temp file or object storage. Analysis then runs in Celery.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Callable
from typing import Any

import anyio
import structlog
from anyio.from_thread import run as run_from_thread
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from hartriage.api.deps import AgentDep, DbDep, SettingsDep, StorageDep
from hartriage.core.errors import TooLarge, TooManyRequests
from hartriage.core.metrics import UPLOADS
from hartriage.services import audit
from hartriage.services.intake import intake
from hartriage.services.limits import MB, limits_for, storage_used, uploads_today
from hartriage.worker import dispatch
from hartriage.worker.dispatch import enqueue_analysis

router = APIRouter(tags=["uploads"])
log = structlog.get_logger()


class _BodyReader(io.RawIOBase):
    """A blocking file object over an async request stream, for the worker thread."""

    def __init__(self, next_chunk: Callable[[], bytes]) -> None:
        self._next = next_chunk
        self._buffer = b""
        self._eof = False

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        while not self._eof and (size < 0 or len(self._buffer) < size):
            chunk = self._next()
            if not chunk:
                self._eof = True
                break
            self._buffer += chunk
            if size < 0:
                continue
        if size < 0:
            data, self._buffer = self._buffer, b""
        else:
            data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


@router.post("/uploads", status_code=202)
async def upload(
    request: Request,
    principal: AgentDep,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    filename: str = "upload.har",
) -> JSONResponse:
    # The organisation's own limits, set by its admins (Settings), capped by the server.
    limits = limits_for(db, settings, principal.org_id)
    declared = request.headers.get("content-length")
    size = int(declared) if declared and declared.isdigit() else 0
    if size > limits.max_bytes:
        UPLOADS.labels("too_large").inc()
        raise TooLarge(f"The file is too large: the limit is {limits.max_bytes // MB} MB.")
    if (
        limits.daily_uploads is not None
        and uploads_today(db, principal.org_id, principal.user_id) >= limits.daily_uploads
    ):
        UPLOADS.labels("daily_limit").inc()
        raise TooManyRequests(
            "You have reached your organisation's limit of "
            f"{limits.daily_uploads} upload{'' if limits.daily_uploads == 1 else 's'} a day. "
            "Ask an admin to raise it, or try again tomorrow.",
            code="daily_upload_limit",
        )
    if (
        limits.quota_bytes is not None
        and storage_used(db, principal.org_id) + size > limits.quota_bytes
    ):
        UPLOADS.labels("quota").inc()
        raise TooLarge(
            f"Your organisation's storage quota ({limits.quota_bytes // MB} MB) is full. "
            "Delete files you no longer need, or ask an admin to raise the quota.",
            code="storage_quota_exceeded",
        )

    stream: AsyncIterator[bytes] = request.stream().__aiter__()

    async def next_chunk() -> bytes:
        try:
            while True:
                chunk = await stream.__anext__()
                if chunk:
                    return chunk
        except StopAsyncIteration:
            return b""

    def pull() -> bytes:
        return run_from_thread(next_chunk)

    def work() -> Any:
        analysis = intake(
            db,
            storage,
            settings,
            _BodyReader(pull),  # type: ignore[arg-type]
            org_id=principal.org_id,
            source_kind="upload",
            filename=filename,
            created_by=principal.user_id,
            max_bytes=limits.max_bytes,
            retention_days=limits.retention_days,
        )
        audit.record(
            db,
            org_id=principal.org_id,
            actor=principal.user_id,
            action="analysis.uploaded",
            target_type="analysis",
            target_id=analysis.id,
        )
        db.commit()
        return analysis

    try:
        analysis = await anyio.to_thread.run_sync(work)
    except ClientDisconnect:
        # The browser went away mid-upload (tab closed, network lost). Nothing was
        # stored: the multipart upload was aborted. Not an error on our side.
        UPLOADS.labels("aborted").inc()
        log.info("upload_aborted", filename=filename)
        return JSONResponse(
            {"error": {"code": "client_closed", "message": "Upload cancelled."}}, 499
        )
    except Exception:
        UPLOADS.labels("rejected").inc()
        raise
    UPLOADS.labels("accepted").inc()
    await anyio.to_thread.run_sync(dispatch.try_enqueue, enqueue_analysis, analysis.id)
    return JSONResponse(
        {
            "analysis_id": str(analysis.id),
            "status": "queued",
            "redaction": analysis.artifact.redaction_summary if analysis.artifact else None,
        },
        status_code=202,
        headers={"Location": f"/v1/analyses/{analysis.id}"},
    )
