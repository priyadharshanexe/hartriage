"""Allow Zendesk connections that authenticate with an OAuth client.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OLD = "auth_type IN ('api_token','oauth','api_key')"
NEW = "auth_type IN ('api_token','oauth','oauth_client','api_key')"


def upgrade() -> None:
    op.drop_constraint("auth_type_valid", "helpdesk_connections", type_="check")
    op.create_check_constraint("auth_type_valid", "helpdesk_connections", NEW)


def downgrade() -> None:
    op.execute("DELETE FROM helpdesk_connections WHERE auth_type = 'oauth_client'")
    op.drop_constraint("auth_type_valid", "helpdesk_connections", type_="check")
    op.create_check_constraint("auth_type_valid", "helpdesk_connections", OLD)
