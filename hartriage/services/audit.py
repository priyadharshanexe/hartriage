"""Who viewed, exported, deleted or configured what, and when."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from hartriage.db.models import AuditLog


def record(
    db: Session,
    *,
    org_id: uuid.UUID | None,
    actor: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str | None = None,
    **details: Any,
) -> None:
    db.add(
        AuditLog(
            org_id=org_id,
            actor_user_id=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details,
        )
    )
