"""Health, readiness, metrics, the knowledge base and the audit log."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Any

import redis
from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text

from hartriage.api.deps import AdminDep, DbDep, SettingsDep, StorageDep
from hartriage.core.errors import NotFound
from hartriage.db.models import AuditLog, User
from hartriage.rules import RULE_CLASSES

health = APIRouter(tags=["health"])
router = APIRouter(tags=["kb", "audit"])


@health.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@health.head("/healthz", include_in_schema=False)
def healthz_head() -> Response:
    return Response(status_code=200)


@health.get("/readyz")
def readyz(db: DbDep, settings: SettingsDep, storage: StorageDep) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"
    try:
        redis.Redis.from_url(settings.redis_url, socket_timeout=1).ping()
        checks["redis"] = "ok"
    except redis.RedisError:
        checks["redis"] = "down"
    checks["storage"] = "ok" if storage.ping() else "down"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks}, 200 if ok else 503
    )


@health.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _kb_dir() -> Path:
    packaged = resources.files("hartriage") / "_kb"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "kb"  # running from a checkout


_SLUG = re.compile(r"^[A-Za-z0-9-]{1,60}$")


@router.get("/kb")
def kb_index() -> dict[str, Any]:
    return {
        "items": [
            {"slug": f"{c.id}-{c.slug}", "rule_id": c.id, "title": c.title, "summary": c.summary}
            for c in RULE_CLASSES
        ]
        + [
            {
                "slug": "recording-a-har",
                "rule_id": None,
                "title": "How to record a useful HAR file",
                "summary": "Steps for Chrome, Edge, Firefox and Safari.",
            }
        ]
    }


@router.get("/kb/{slug}", response_class=PlainTextResponse)
def kb_article(slug: str) -> PlainTextResponse:
    if not _SLUG.match(slug):
        raise NotFound("Article not found.")
    path = _kb_dir() / f"{slug}.md"
    if not path.is_file():
        raise NotFound("Article not found.")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8"
    )


@router.get("/audit")
def audit_log(
    principal: AdminDep, db: DbDep, limit: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    rows = db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.org_id == principal.org_id)
        .order_by(AuditLog.at.desc())
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                "at": a.at.isoformat(),
                "actor": email,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "details": a.details,
            }
            for a, email in rows
        ]
    }
