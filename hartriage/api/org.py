"""Organisation limits (admins set them; everyone can read them) and storage usage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from hartriage.api.deps import AdminDep, DbDep, PrincipalDep, SettingsDep
from hartriage.core.errors import AppError
from hartriage.db.models import OrgSettings
from hartriage.services import audit
from hartriage.services.limits import (
    MB,
    RETENTION_CHOICES,
    limits_for,
    storage_used,
    uploads_today,
    usage_by_member,
)

router = APIRouter(prefix="/org", tags=["organisation"])


class SettingsIn(BaseModel):
    retention_days: int = Field(30)
    max_file_mb: int | None = Field(None, ge=1)
    storage_quota_mb: int | None = Field(None, ge=1)
    daily_uploads_per_member: int | None = Field(None, ge=1, le=10_000)

    @field_validator("retention_days")
    @classmethod
    def _retention(cls, value: int) -> int:
        if value not in RETENTION_CHOICES:
            raise ValueError(f"choose one of {', '.join(map(str, RETENTION_CHOICES))} days")
        return value


def _view(db: Any, settings: Any, principal: Any) -> dict[str, Any]:
    limits = limits_for(db, settings, principal.org_id)
    row = db.get(OrgSettings, principal.org_id)
    return {
        "retention_days": limits.retention_days,
        "retention_choices": list(RETENTION_CHOICES),
        "max_file_mb": row.max_file_mb if row else None,
        "server_max_file_mb": settings.max_upload_bytes // MB,
        "effective_max_file_mb": limits.max_bytes // MB,
        "storage_quota_mb": row.storage_quota_mb if row else None,
        "daily_uploads_per_member": limits.daily_uploads,
        "storage_used_bytes": storage_used(db, principal.org_id),
        "uploads_today": uploads_today(db, principal.org_id, principal.user_id),
    }


@router.get("/settings")
def get_settings_view(principal: PrincipalDep, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    return _view(db, settings, principal)


@router.put("/settings")
def put_settings(
    body: SettingsIn, principal: AdminDep, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    server_mb = settings.max_upload_bytes // MB
    if body.max_file_mb and body.max_file_mb > server_mb:
        raise AppError(
            f"The server accepts files up to {server_mb} MB.", code="above_server_limit", status=422
        )
    row = db.get(OrgSettings, principal.org_id) or OrgSettings(org_id=principal.org_id)
    row.retention_days = body.retention_days
    row.max_file_mb = body.max_file_mb
    row.storage_quota_mb = body.storage_quota_mb
    row.daily_uploads_per_member = body.daily_uploads_per_member
    db.add(row)
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="org.settings_changed",
        target_type="organization",
        target_id=principal.org_id,
        **body.model_dump(),
    )
    db.commit()
    return _view(db, settings, principal)


@router.get("/usage")
def usage(principal: AdminDep, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    limits = limits_for(db, settings, principal.org_id)
    return {
        "storage_used_bytes": storage_used(db, principal.org_id),
        "storage_quota_bytes": limits.quota_bytes,
        "members": usage_by_member(db, principal.org_id),
    }
