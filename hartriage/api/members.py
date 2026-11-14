"""Team management: invitations by link, roles, removal. Admins only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select

from hartriage.api.deps import AdminDep, DbDep, SettingsDep
from hartriage.core.errors import AppError, NotFound
from hartriage.core.security import new_token, sha256_hex
from hartriage.db.models import Invitation, Membership, User
from hartriage.services import audit

router = APIRouter(tags=["members"])
Role = Literal["admin", "agent", "viewer"]


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = "agent"


class RoleIn(BaseModel):
    role: Role


def _admins(db: DbDep, org_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.role == "admin")
        )
        or 0
    )


@router.get("/members")
def list_members(principal: AdminDep, db: DbDep) -> dict[str, Any]:
    rows = db.scalars(select(Membership).where(Membership.org_id == principal.org_id)).all()
    invites = db.scalars(
        select(Invitation).where(
            Invitation.org_id == principal.org_id,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
    ).all()
    return {
        "members": [
            {
                "user_id": str(m.user_id),
                "email": m.user.email,
                "name": m.user.name,
                "role": m.role,
                "joined_at": m.created_at.isoformat(),
                "you": m.user_id == principal.user_id,
            }
            for m in rows
        ],
        "invitations": [
            {
                "id": str(i.id),
                "email": i.email,
                "role": i.role,
                "expires_at": i.expires_at.isoformat(),
            }
            for i in invites
        ],
    }


@router.post("/invitations", status_code=201)
def invite(body: InviteIn, principal: AdminDep, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    email = body.email.lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing and db.get(Membership, (existing.id, principal.org_id)):
        raise AppError("This person is already a member.", code="already_member", status=409)
    token = new_token()
    row = Invitation(
        org_id=principal.org_id,
        email=email,
        role=body.role,
        token_hash=sha256_hex(token),
        created_by=principal.user_id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(row)
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="member.invited",
        target_type="invitation",
        target_id=None,
        email=email,
        role=body.role,
    )
    db.commit()
    # Shown once. Only its hash is stored.
    return {
        "id": str(row.id),
        "email": email,
        "role": body.role,
        "invite_url": f"{settings.public_url}/invite#{token}",
        "expires_at": row.expires_at.isoformat(),
    }


@router.delete("/invitations/{invitation_id}", status_code=204)
def cancel_invite(invitation_id: uuid.UUID, principal: AdminDep, db: DbDep) -> Response:
    row = db.get(Invitation, invitation_id)
    if row is None or row.org_id != principal.org_id:
        raise NotFound("Invitation not found.")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.patch("/members/{user_id}")
def change_role(user_id: uuid.UUID, body: RoleIn, principal: AdminDep, db: DbDep) -> dict[str, str]:
    member = db.get(Membership, (user_id, principal.org_id))
    if member is None:
        raise NotFound("Member not found.")
    if member.role == "admin" and body.role != "admin" and _admins(db, principal.org_id) == 1:
        raise AppError("An organisation needs at least one admin.", code="last_admin", status=409)
    old, member.role = member.role, body.role
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="member.role_changed",
        target_type="user",
        target_id=user_id,
        old=old,
        new=body.role,
    )
    db.commit()
    return {"user_id": str(user_id), "role": body.role}


@router.delete("/members/{user_id}", status_code=204)
def remove(user_id: uuid.UUID, principal: AdminDep, db: DbDep) -> Response:
    member = db.get(Membership, (user_id, principal.org_id))
    if member is None:
        raise NotFound("Member not found.")
    if member.role == "admin" and _admins(db, principal.org_id) == 1:
        raise AppError("An organisation needs at least one admin.", code="last_admin", status=409)
    db.delete(member)
    audit.record(
        db,
        org_id=principal.org_id,
        actor=principal.user_id,
        action="member.removed",
        target_type="user",
        target_id=user_id,
    )
    db.commit()
    return Response(status_code=204)
