"""Database tables. Every row that holds customer data carries `org_id`, and every
query in the API filters on it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    password_hash: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('admin','agent','viewer')", name="role_valid"),)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created()
    user: Mapped[User] = relationship(lazy="joined")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint("role IN ('admin','agent','viewer')", name="role_valid"),)
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class HelpdeskConnection(Base):
    __tablename__ = "helpdesk_connections"
    __table_args__ = (
        CheckConstraint("platform IN ('zendesk','freshdesk')", name="platform_valid"),
        CheckConstraint(
            "auth_type IN ('api_token','oauth','oauth_client','api_key')", name="auth_type_valid"
        ),
    )
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(20))
    subdomain: Mapped[str] = mapped_column(String(200))
    auth_type: Mapped[str] = mapped_column(String(20))
    credentials_encrypted: Mapped[str] = mapped_column(Text)
    webhook_secret_encrypted: Mapped[str] = mapped_column(Text)
    replace_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_webhook_status: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_ticket_id", name="uq_case_ticket"),
    )
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("helpdesk_connections.id", ondelete="CASCADE")
    )
    external_ticket_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = _created()


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("kind IN ('har','log')", name="kind_valid"),
        CheckConstraint("source IN ('upload','cli','ticket')", name="source_valid"),
        UniqueConstraint("case_id", "external_attachment_id", name="uq_artifact_attachment"),
        # The retention job only ever scans rows whose files still exist.
        Index(
            "ix_artifacts_live_expiry", "expires_at", postgresql_where=text("deleted_at IS NULL")
        ),
    )
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10), default="har")
    source: Mapped[str] = mapped_column(String(10))
    original_filename: Mapped[str | None] = mapped_column(String(300))
    external_attachment_id: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)  # of the redacted file
    original_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256_of_redacted: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(300))
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    redaction_summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','done','failed')", name="status_valid"),
        Index("ix_analyses_org_created", "org_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(10), default="queued")
    engine_version: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    summary_md: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact: Mapped[Artifact] = relationship(lazy="joined")


class FindingRow(Base):
    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint("severity IN ('critical','high','medium','info')", name="severity_valid"),
    )
    id: Mapped[uuid.UUID] = _id()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[str] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(10))
    entry_index: Mapped[int | None] = mapped_column(Integer)  # the request number findings point at
    title: Mapped[str] = mapped_column(Text)
    cause: Mapped[str] = mapped_column(Text)
    next_step: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(10))
    kb: Mapped[str] = mapped_column(String(60))
    entries: Mapped[list[Any]] = mapped_column(default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)


class EntryIndex(Base):
    """The waterfall's index of requests. Headers and bodies stay in the redacted
    file in object storage; byte_offset/byte_length locate each request there."""

    __tablename__ = "entries"
    __table_args__ = (Index("ix_entries_failed", "analysis_id", "failed"),)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_ms: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(16))
    url: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(String(255))
    status: Mapped[int] = mapped_column(Integer)
    error: Mapped[str] = mapped_column(String(200), default="")
    mime: Mapped[str] = mapped_column(String(100), default="")
    resource_type: Mapped[str] = mapped_column(String(40), default="")
    time_ms: Mapped[float] = mapped_column(Float)
    timings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    request_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    response_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    failed: Mapped[bool] = mapped_column(Boolean)
    byte_offset: Mapped[int | None] = mapped_column(BigInteger)
    byte_length: Mapped[int | None] = mapped_column(Integer)


class PostedNote(Base):
    __tablename__ = "posted_notes"
    __table_args__ = (
        UniqueConstraint("case_id", "analysis_id", name="uq_note_once"),
        CheckConstraint("status IN ('pending','posted','failed')", name="status_valid"),
    )
    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    platform_comment_id: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipts"
    __table_args__ = (UniqueConstraint("connection_id", "delivery_key", name="uq_webhook_once"),)
    id: Mapped[uuid.UUID] = _id()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("helpdesk_connections.id", ondelete="CASCADE")
    )
    delivery_key: Mapped[str] = mapped_column(String(200))
    ticket_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(40), default="accepted")
    received_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_org_at", "org_id", "at"),)
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    at: Mapped[datetime] = _created()
