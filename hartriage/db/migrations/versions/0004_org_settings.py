"""Per-organisation limits: retention, file size, storage quota, daily uploads.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_settings",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_file_mb", sa.Integer(), nullable=True),
        sa.Column("storage_quota_mb", sa.Integer(), nullable=True),
        sa.Column("daily_uploads_per_member", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # A user's uploads are listed and counted by uploader.
    op.create_index(
        "ix_analyses_org_creator_created", "analyses", ["org_id", "created_by", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_org_creator_created", table_name="analyses")
    op.drop_table("org_settings")
