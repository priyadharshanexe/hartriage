"""Dashboard sessions: a short-lived access token in memory, a rotating refresh
token in an httpOnly cookie scoped to /v1/auth."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from hartriage.api.deps import DbDep, PrincipalDep, SettingsDep
from hartriage.core.config import Settings
from hartriage.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized
from hartriage.core.ratelimit import limit
from hartriage.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    new_token,
    sha256_hex,
    verify_password,
)
from hartriage.db.models import Invitation, Membership, Organization, RefreshToken, User
from hartriage.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "hartriage_refresh"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    name: str = Field(default="", max_length=200)
    organization: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)
    org_id: uuid.UUID | None = None


class SwitchIn(BaseModel):
    org_id: uuid.UUID


class AcceptIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(min_length=10, max_length=200)
    name: str = Field(default="", max_length=200)


def _session(
    db: DbDep, settings: Settings, response: Response, user: User, org_id: uuid.UUID
) -> dict[str, Any]:
    refresh = new_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            org_id=org_id,
            token_hash=sha256_hex(refresh),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    response.set_cookie(
        COOKIE,
        refresh,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/v1/auth",
    )
    db.commit()
    return _me(db, settings, user, org_id, create_access_token(settings, user.id, org_id))


def _me(
    db: DbDep, settings: Settings, user: User, org_id: uuid.UUID, token: str | None = None
) -> dict[str, Any]:
    memberships = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    current = next((m for m, _ in memberships if m.org_id == org_id), None)
    data: dict[str, Any] = {
        "user": {"id": str(user.id), "email": user.email, "name": user.name},
        "org_id": str(org_id),
        "role": current.role if current else None,
        "orgs": [{"id": str(o.id), "name": o.name, "role": m.role} for m, o in memberships],
    }
    if token:
        data["access_token"] = token
        data["expires_in"] = settings.access_token_ttl_seconds
    return data


@router.post("/register", status_code=201)
def register(
    body: RegisterIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    if not settings.allow_registration:
        raise Forbidden("Sign-up is closed on this server. Ask an admin for an invitation.")
    limit(settings, f"register:{request.client.host if request.client else '-'}", 10, 3600)
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("An account with this email already exists. Sign in instead.")
    user = User(email=email, password_hash=hash_password(body.password), name=body.name.strip())
    org = Organization(name=body.organization.strip())
    db.add_all([user, org])
    db.flush()
    db.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    audit.record(
        db,
        org_id=org.id,
        actor=user.id,
        action="org.created",
        target_type="organization",
        target_id=org.id,
    )
    return _session(db, settings, response, user, org.id)


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    email = body.email.lower()
    limit(settings, f"login:{email}", settings.login_attempts_per_minute, 60)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.password_hash:
        verify_password(DUMMY_HASH, body.password)  # same cost either way: no account probing
        raise Unauthorized("Wrong email or password.")
    if not verify_password(user.password_hash, body.password):
        raise Unauthorized("Wrong email or password.")
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    if not memberships:
        raise Forbidden("Your account is not a member of any organisation.")
    org_id = (
        body.org_id
        if body.org_id and any(m.org_id == body.org_id for m in memberships)
        else memberships[0].org_id
    )
    user.last_login_at = datetime.now(UTC)
    return _session(db, settings, response, user, org_id)


@router.post("/refresh")
def refresh(
    request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    token = request.cookies.get(COOKIE)
    if not token:
        raise Unauthorized("Sign in to continue.")
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(token)).with_for_update()
    )
    now = datetime.now(UTC)
    if row is None or row.expires_at <= now:
        raise Unauthorized("Your session has ended. Sign in again.")
    if row.revoked_at is not None:
        # A rotated token used twice means it was copied: end every session of this user.
        for other in db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None)
            )
        ):
            other.revoked_at = now
        db.commit()
        raise Unauthorized("Your session has ended. Sign in again.")
    if db.get(Membership, (row.user_id, row.org_id)) is None:
        raise Unauthorized("You are no longer a member of this organisation.")
    row.revoked_at = now
    user = db.get(User, row.user_id)
    assert user is not None  # noqa: S101 - cascades delete tokens with users
    return _session(db, settings, response, user, row.org_id)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DbDep) -> Response:
    token = request.cookies.get(COOKIE)
    if token:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(token)))
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            db.commit()
    response.delete_cookie(COOKIE, path="/v1/auth")
    response.status_code = 204
    return response


@router.get("/me")
def me(principal: PrincipalDep, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    return _me(db, settings, principal.user, principal.org_id)


@router.post("/switch")
def switch(
    body: SwitchIn, principal: PrincipalDep, response: Response, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    if db.get(Membership, (principal.user_id, body.org_id)) is None:
        raise NotFound("Organisation not found.")
    return _session(db, settings, response, principal.user, body.org_id)


@router.post("/accept-invite")
def accept_invite(
    body: AcceptIn, response: Response, db: DbDep, settings: SettingsDep
) -> dict[str, Any]:
    invite = db.scalar(
        select(Invitation).where(Invitation.token_hash == sha256_hex(body.token)).with_for_update()
    )
    now = datetime.now(UTC)
    if invite is None or invite.accepted_at is not None or invite.expires_at <= now:
        raise AppError(
            "This invitation link is invalid or has expired. Ask for a new one.",
            code="invitation_invalid",
            status=410,
        )
    user = db.scalar(select(User).where(User.email == invite.email))
    if user is None:
        user = User(
            email=invite.email, password_hash=hash_password(body.password), name=body.name.strip()
        )
        db.add(user)
        db.flush()
    elif not user.password_hash or not verify_password(user.password_hash, body.password):
        raise Unauthorized("An account with this email exists: enter its current password to join.")
    if db.get(Membership, (user.id, invite.org_id)) is None:
        db.add(Membership(user_id=user.id, org_id=invite.org_id, role=invite.role))
    invite.accepted_at = now
    audit.record(
        db,
        org_id=invite.org_id,
        actor=user.id,
        action="member.joined",
        target_type="user",
        target_id=user.id,
        role=invite.role,
    )
    return _session(db, settings, response, user, invite.org_id)
