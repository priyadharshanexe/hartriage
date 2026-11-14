"""Shared FastAPI dependencies: settings, database session, storage, the signed-in user."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from hartriage.core.config import Settings, get_settings
from hartriage.core.errors import Forbidden, Unauthorized
from hartriage.core.security import decode_access_token
from hartriage.db.models import Membership, User
from hartriage.db.session import get_db
from hartriage.storage.s3 import Storage, get_storage

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def storage_dep(settings: SettingsDep) -> Storage:
    return get_storage(settings)


StorageDep = Annotated[Storage, Depends(storage_dep)]

ROLE_RANK = {"viewer": 0, "agent": 1, "admin": 2}


@dataclass(frozen=True)
class Principal:
    user: User
    org_id: uuid.UUID
    role: str

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


# Declared as a security scheme so the API docs (/docs) offer an "Authorize" button.
bearer = HTTPBearer(auto_error=False, description="The access_token from POST /v1/auth/login")


def current_principal(
    db: DbDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> Principal:
    token = credentials.credentials if credentials else ""
    if not token:
        raise Unauthorized("Sign in to continue.")
    try:
        claims = decode_access_token(settings, token)
        user_id, org_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["org"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Your session has expired. Sign in again.") from exc
    # The role is read on every request, so a removed or demoted member loses access at once.
    membership = db.get(Membership, (user_id, org_id))
    if membership is None:
        raise Unauthorized("You are no longer a member of this organisation.")
    return Principal(user=membership.user, org_id=org_id, role=membership.role)


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require(role: str) -> Callable[[Principal], Principal]:
    def check(principal: PrincipalDep) -> Principal:
        if ROLE_RANK[principal.role] < ROLE_RANK[role]:
            raise Forbidden(f"This needs the {role} role.")
        return principal

    return check


AgentDep = Annotated[Principal, Depends(require("agent"))]
AdminDep = Annotated[Principal, Depends(require("admin"))]
