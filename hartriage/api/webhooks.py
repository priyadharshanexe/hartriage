"""Inbound helpdesk webhooks: verify, record the delivery once, hand off to the worker.

The payload is trusted for one thing only, the ticket id, and only after the
signature (Zendesk) or the per-connection secret (Freshdesk) checks out. The
worker then re-reads the ticket from the helpdesk API.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from hartriage.api.deps import DbDep, SettingsDep
from hartriage.core.errors import AppError, NotFound, Unauthorized
from hartriage.core.metrics import WEBHOOKS
from hartriage.db.models import HelpdeskConnection, WebhookReceipt
from hartriage.helpdesk import freshdesk, registry, zendesk
from hartriage.worker.dispatch import enqueue_ticket

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
MAX_BODY = 64 * 1024
_TICKET = re.compile(r"^\d{1,20}$")


def _ticket_id(body: bytes) -> str:
    try:
        data = json.loads(body or b"{}")
    except ValueError as exc:
        raise AppError(
            'The body must be JSON like {"ticket_id": 123}.', code="invalid_payload"
        ) from exc
    value = str(data.get("ticket_id", "")).strip() if isinstance(data, dict) else ""
    if not _TICKET.match(value):
        raise AppError("ticket_id must be the numeric ticket id.", code="invalid_payload")
    return value


async def _receive(
    platform: str, connection_id: uuid.UUID, request: Request, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            raise AppError("Webhook body too large.", code="too_large", status=413)
    headers = {k.lower(): v for k, v in request.headers.items()}
    return await anyio.to_thread.run_sync(
        _process, platform, connection_id, headers, body, db, settings
    )


def _process(
    platform: str,
    connection_id: uuid.UUID,
    headers: dict[str, str],
    body: bytes,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    conn = db.get(HelpdeskConnection, connection_id)
    if conn is None or conn.platform != platform:
        WEBHOOKS.labels(platform, "unknown_connection").inc()
        raise NotFound("Unknown connection.")
    secret = registry.webhook_secret(settings, conn)
    now = datetime.now(UTC)
    if platform == "zendesk":
        valid = zendesk.verify_signature(secret, headers, body)
        key = zendesk.delivery_key(headers, body)
    else:
        valid = freshdesk.verify_secret(secret, headers)
        key = freshdesk.delivery_key(body)
    conn.last_webhook_at = now
    if not valid:
        conn.last_webhook_status = (
            "rejected: no signing secret yet" if not secret else "rejected: bad signature"
        )
        db.commit()
        WEBHOOKS.labels(platform, "bad_signature").inc()
        raise Unauthorized("Signature check failed.")
    ticket_id = _ticket_id(body)
    receipt = WebhookReceipt(connection_id=conn.id, delivery_key=key, ticket_id=ticket_id)
    try:
        with db.begin_nested():
            db.add(receipt)
        conn.last_webhook_status = f"accepted: ticket {ticket_id}"
        db.commit()
    except IntegrityError:
        db.rollback()
        conn.last_webhook_at, conn.last_webhook_status = now, f"duplicate: ticket {ticket_id}"
        db.commit()
        WEBHOOKS.labels(platform, "duplicate").inc()
        return JSONResponse({"status": "duplicate"}, status_code=200)
    WEBHOOKS.labels(platform, "accepted").inc()
    enqueue_ticket(receipt.id)
    return JSONResponse({"status": "accepted", "ticket_id": ticket_id}, status_code=202)


@router.post("/zendesk/{connection_id}", status_code=202)
async def zendesk_webhook(
    connection_id: uuid.UUID, request: Request, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return await _receive("zendesk", connection_id, request, db, settings)


@router.post("/freshdesk/{connection_id}", status_code=202)
async def freshdesk_webhook(
    connection_id: uuid.UUID, request: Request, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return await _receive("freshdesk", connection_id, request, db, settings)
