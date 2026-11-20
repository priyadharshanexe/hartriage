"""The FastAPI application. Run with: uvicorn --factory hartriage.main:create_app"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hartriage import __version__
from hartriage.api import analyses, auth, connections, members, misc, org, uploads, webhooks
from hartriage.core import errors
from hartriage.core.config import get_settings
from hartriage.core.logging import configure, request_id_middleware
from hartriage.storage.s3 import get_storage

log = structlog.get_logger()


def create_app() -> FastAPI:
    settings = get_settings()
    configure(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            get_storage(settings).ensure_ready(settings.retention_days)
        except Exception as exc:
            log.warning("storage_not_ready", error=str(exc))
        yield

    app = FastAPI(
        title="HAR Triage API",
        version=__version__,
        description=(
            "Redacts HAR files before they are stored, finds the failing request and writes a "
            "ticket-ready summary. Sign in with POST /v1/auth/login, then send the access token as "
            "`Authorization: Bearer <token>`."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.middleware("http")(request_id_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
        expose_headers=["X-Request-Id", "Location"],
    )
    errors.install(app)
    app.include_router(misc.health)
    for module in (auth, members, uploads, analyses, connections, webhooks, misc, org):
        app.include_router(module.router, prefix="/v1")
    return app
