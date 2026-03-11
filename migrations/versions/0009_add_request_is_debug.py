"""add is_debug to requests

Revision ID: 0009_add_request_is_debug
Revises: 0008_add_notification_read_at
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_add_request_is_debug"
down_revision = "0008_add_notification_read_at"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "request",
        sa.Column("is_debug", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("request", "is_debug")
