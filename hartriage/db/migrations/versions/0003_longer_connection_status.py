"""Room for a helpdesk connection's whole status message.

40 characters cut errors mid-word ("freshdesk could not be reach").

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "helpdesk_connections", "last_webhook_status", type_=sa.String(300), existing_nullable=True
    )


def downgrade() -> None:
    op.execute(
        "UPDATE helpdesk_connections SET last_webhook_status = left(last_webhook_status, 40)"
    )
    op.alter_column(
        "helpdesk_connections", "last_webhook_status", type_=sa.String(40), existing_nullable=True
    )
