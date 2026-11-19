"""Settings, read from environment variables prefixed with HARTRIAGE_."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_ONLY = "development-only-not-a-secret"
# HS256 wants at least 32 bytes of key, even in development.
_DEV_JWT = _DEV_ONLY + "-local-jwt-signing-key-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HARTRIAGE_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+psycopg://hartriage:hartriage@localhost:5436/hartriage"
    database_pool_size: int = 10
    redis_url: str = "redis://localhost:6380/0"

    # Dashboard sessions. Production refuses to start without real values.
    jwt_secret: str = _DEV_JWT
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 14
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:8280"]
    allow_registration: bool = True
    login_attempts_per_minute: int = 10
    invitation_ttl_days: int = 7

    # Helpdesk credentials and webhook secrets are encrypted with this key (base64, 32 bytes).
    encryption_key: str = ""

    # Where users open the app; used in webhook URLs and KB links.
    public_url: str = "http://localhost:8280"
    api_public_url: str = "http://localhost:8200"
    kb_url_template: str = "https://github.com/priyadharshanexe/hartriage/blob/main/kb/{slug}.md"

    # Object storage: S3 in production, RustFS (S3-compatible) locally, memory in tests.
    storage_backend: Literal["s3", "memory"] = "s3"
    s3_endpoint_url: str | None = "http://localhost:9200"
    s3_bucket: str = "hartriage"
    s3_region: str = "us-east-1"
    s3_access_key: str | None = "hartriage"
    s3_secret_key: str | None = "hartriage-dev-secret"  # noqa: S105 - the local RustFS default
    s3_sse: str = ""  # "AES256" or "aws:kms" on AWS
    s3_lifecycle: bool = True

    # Limits
    max_upload_bytes: int = 100 * 1024 * 1024
    max_decompressed_bytes: int = 400 * 1024 * 1024
    max_entries: int = 50_000
    retention_days: int = 30

    # Celery
    celery_eager: bool = False  # run tasks inline (tests and demos without a worker)

    # Helpdesk integration
    trigger_tag: str = "har_analyze"
    done_tag: str = "har_analyzed"
    # Freshdesk automations do not fire when only a tag changes, so tagged tickets are
    # also found by polling the search API. 0 turns polling off.
    freshdesk_poll_seconds: int = 60
    helpdesk_timeout_seconds: float = 30.0
    helpdesk_base_url_override: str | None = None  # points both clients at a fake server

    slow_ms: float = 3000
    demo_mode: bool = Field(
        default=False, description="Public demo: analyse in memory, store nothing."
    )

    @model_validator(mode="after")
    def _production_needs_real_secrets(self) -> Settings:
        if self.environment == "production":
            if self.jwt_secret in (_DEV_ONLY, _DEV_JWT) or len(self.jwt_secret) < 32:
                raise ValueError("HARTRIAGE_JWT_SECRET must be set to 32+ random characters")
            if not self.encryption_key:
                raise ValueError("HARTRIAGE_ENCRYPTION_KEY must be set (base64 of 32 random bytes)")
        return self

    @property
    def encryption_key_bytes(self) -> bytes:
        if self.encryption_key:
            key = base64.b64decode(self.encryption_key)
            if len(key) != 32:
                raise ValueError("HARTRIAGE_ENCRYPTION_KEY must decode to 32 bytes")
            return key
        # Development and tests only: a fixed key derived in code, never a literal secret.
        return hashlib.sha256(_DEV_ONLY.encode()).digest()

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
