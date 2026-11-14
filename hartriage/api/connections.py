"""Helpdesk connections (admins only): credentials are checked, then stored encrypted."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from hartriage.api.deps import AdminDep, DbDep, SettingsDep, StorageDep
from hartriage.core.config import Settings
from hartriage.core.errors import AppError, NotFound
from hartriage.core.security import new_token
from hartriage.db.models import Artifact, Case, HelpdeskConnection
from hartriage.helpdesk import registry
from hartriage.helpdesk.base import SUBDOMAIN, AuthFailed, HelpdeskError
from hartriage.helpdesk.freshdesk import SECRET_HEADER
from hartriage.services import audit
from hartriage.services.retention import purge

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectionIn(BaseModel):
    platform: Literal["zendesk", "freshdesk"]
    subdomain: str = Field(
        max_length=63, description="acme for acme.zendesk.com / acme.freshdesk.com"
    )
    email: str | None = Field(None, max_length=320)
    api_token: str | None = Field(None, max_length=200)
    oauth_token: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=200)
    signing_secret: str | None = Field(
        None, max_length=200, description="Zendesk webhook signing secret"
    )
    replace_attachments: bool = False
    verify: bool = True

    @field_validator("subdomain")
    @classmethod
    def _subdomain(cls, value: str) -> str:
        value = value.strip().lower()
        for suffix in (".zendesk.com", ".freshdesk.com"):
            value = value.removesuffix(suffix)
        value = value.removeprefix("https://")
        if not SUBDOMAIN.match(value):
            raise ValueError("enter just the subdomain, for example acme for acme.zendesk.com")
        return value


class ConnectionPatch(BaseModel):
    replace_attachments: bool | None = None
    signing_secret: str | None = Field(None, max_length=200)


def _credentials(body: ConnectionIn) -> tuple[str, dict[str, str]]:
    if body.platform == "zendesk":
        if body.oauth_token:
            return "oauth", {"oauth_token": body.oauth_token}
        if body.email and body.api_token:
            return "api_token", {"email": body.email, "api_token": body.api_token}
        raise AppError(
            "Zendesk needs an OAuth token, or an agent email plus an API token.",
            code="missing_credentials",
            status=422,
        )
    if body.api_key:
        return "api_key", {"api_key": body.api_key}
    raise AppError("Freshdesk needs an API key.", code="missing_credentials", status=422)


def webhook_url(settings: Settings, conn: HelpdeskConnection) -> str:
    return f"{settings.api_public_url.rstrip('/')}/v1/webhooks/{conn.platform}/{conn.id}"


def setup_steps(settings: Settings, conn: HelpdeskConnection) -> list[str]:
    url = webhook_url(settings, conn)
    if conn.platform == "zendesk":
        return [
            f"Admin Center → Apps and integrations → Webhooks → Create webhook: endpoint {url},"
            " method POST, format JSON, authentication none.",
            "Open the webhook, reveal its signing secret and paste it into this connection.",
            f"Objects and rules → Triggers → Create trigger: conditions 'Ticket > Tags contains at least one"
            f" of: {settings.trigger_tag}'; action 'Notify webhook' with this webhook and the JSON body"
            ' {"ticket_id": "{{ticket.id}}"}.',
            f"Tag a ticket that has a .har attachment with {settings.trigger_tag}. A private note appears"
            f" within a minute, and the tag becomes {settings.done_tag}.",
        ]
    return [
        "Admin → Workflows → Automations → Ticket updates → New rule:"
        f" event 'Tag is added: {settings.trigger_tag}'.",
        f"Action 'Trigger webhook': POST {url}, encoding JSON, content"
        ' {"ticket_id": {{ticket.id}}}.',
        f"Under custom headers add {SECRET_HEADER}: the secret shown once when this connection was created"
        " (rotate it here if lost).",
        f"Tag a ticket that has a .har attachment with {settings.trigger_tag}. A private note appears"
        f" within a minute, and the tag becomes {settings.done_tag}.",
    ]


def serialize(settings: Settings, conn: HelpdeskConnection) -> dict[str, Any]:
    return {
        "id": str(conn.id),
        "platform": conn.platform,
        "subdomain": conn.subdomain,
        "auth_type": conn.auth_type,
        "replace_attachments": conn.replace_attachments,
        "webhook_url": webhook_url(settings, conn),
        "setup_steps": setup_steps(settings, conn),
        "last_webhook_at": conn.last_webhook_at.isoformat() if conn.last_webhook_at else None,
        "last_webhook_status": conn.last_webhook_status,
        "created_at": conn.created_at.isoformat(),
        "secret_header": SECRET_HEADER if conn.platform == "freshdesk" else None,
    }


def _owned(db: DbDep, principal: AdminDep, connection_id: uuid.UUID) -> HelpdeskConnection:
    conn = db.get(HelpdeskConnection, connection_id)
    if conn is None or conn.org_id != principal.org_id:
        raise NotFound("Connection not found.")
    return conn


@router.get("")
def list_connections(principal: AdminDep, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    rows = db.scalars(
        select(HelpdeskConnection)
        .where(HelpdeskConnection.org_id == principal.org_id)
        .order_by(HelpdeskConnection.created_at)
    ).all()
    return {"items": [serialize(settings, c) for c in rows]}


@router.post("", status_code=201)
def create(
    body: ConnectionIn, principal: AdminDep, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    auth_type, creds = _credentials(body)
    account = None
    if body.verify:
        client = registry.client_for(settings, body.platform, body.subdomain, creds)
        try:
            account = client.verify()
        except AuthFailed as exc:
            raise AppError(
                f"{body.platform.title()} refused these credentials.",
                code="credentials_rejected",
                status=422,
            ) from exc
        except HelpdeskError as exc:
            raise AppError(
                f"Could not reach {body.subdomain}: {exc}.", code="helpdesk_unreachable", status=502
            ) from exc
        finally:
            client.close()
    if body.platform == "zendesk" and not body.signing_secret:
        raise AppError(
            "Paste the Zendesk webhook's signing secret.", code="missing_signing_secret", status=422
        )
    secret = body.signing_secret if body.platform == "zendesk" else new_token(24)
    assert secret is not None  # noqa: S101 - checked above
    conn = HelpdeskConnection(
        id=uuid.uuid4(),
        org_id=principal.org_id,
        platform=body.platform,
        subdomain=body.subdomain,
        auth_type=auth_type,
        replace_attachments=body.replace_attachments,
        created_by=principal.user_id,
        credentials_encrypted="",
        webhook_secret_encrypted="",
    )
    cipher = registry.cipher(settings)
    conn.credentials_encrypted = cipher.encrypt(json.dumps(creds), str(conn.id))
    conn.webhook_secret_encrypted = cipher.encrypt(secret, f"webhook:{conn.id}")
    db.add(conn)
    db.flush()
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="connection.created",
        target_type="connection",
        target_id=conn.id,
        platform=body.platform,
    )
    db.commit()
    data = serialize(settings, conn)
    data["account"] = account
    if body.platform == "freshdesk":
        data["webhook_secret"] = secret  # shown once
    return data


@router.patch("/{connection_id}")
def update(
    connection_id: uuid.UUID,
    body: ConnectionPatch,
    principal: AdminDep,
    db: DbDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    conn = _owned(db, principal, connection_id)
    if body.replace_attachments is not None:
        conn.replace_attachments = body.replace_attachments
    if body.signing_secret:
        if conn.platform != "zendesk":
            raise AppError("Only Zendesk connections take a signing secret.", code="not_supported")
        conn.webhook_secret_encrypted = registry.cipher(settings).encrypt(
            body.signing_secret, f"webhook:{conn.id}"
        )
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="connection.updated",
        target_type="connection",
        target_id=conn.id,
    )
    db.commit()
    return serialize(settings, conn)


@router.post("/{connection_id}/rotate-secret")
def rotate_secret(
    connection_id: uuid.UUID, principal: AdminDep, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    conn = _owned(db, principal, connection_id)
    if conn.platform != "freshdesk":
        raise AppError(
            "Rotate a Zendesk secret in Zendesk, then paste it here.", code="not_supported"
        )
    secret = new_token(24)
    conn.webhook_secret_encrypted = registry.cipher(settings).encrypt(secret, f"webhook:{conn.id}")
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="connection.secret_rotated",
        target_type="connection",
        target_id=conn.id,
    )
    db.commit()
    return {**serialize(settings, conn), "webhook_secret": secret}


@router.post("/{connection_id}/test")
def test(
    connection_id: uuid.UUID, principal: AdminDep, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    conn = _owned(db, principal, connection_id)
    client = registry.client(settings, conn)
    try:
        return {"ok": True, "account": client.verify()}
    except HelpdeskError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        client.close()


@router.delete("/{connection_id}", status_code=204)
def remove(
    connection_id: uuid.UUID, principal: AdminDep, db: DbDep, storage: StorageDep
) -> Response:
    conn = _owned(db, principal, connection_id)
    # Delete the stored files first: the rows would cascade, the objects would not.
    for artifact in db.scalars(
        select(Artifact)
        .join(Case, Case.id == Artifact.case_id)
        .where(Case.connection_id == conn.id, Artifact.deleted_at.is_(None))
    ):
        purge(db, storage, artifact, reason="deleted", actor=principal.user_id)
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="connection.deleted",
        target_type="connection",
        target_id=conn.id,
    )
    db.delete(conn)
    db.commit()
    return Response(status_code=204)
