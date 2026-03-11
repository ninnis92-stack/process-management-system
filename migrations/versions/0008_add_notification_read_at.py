"""add read_at to notifications

Revision ID: 0008_add_notification_read_at
Revises: 0006_add_special_email_config
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_add_notification_read_at"
down_revision = "0006_add_special_email_config"
branch_labels = None
depends_on = None

def upgrade():
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('notification')]
    if 'read_at' not in columns:
        op.add_column("notification", sa.Column("read_at", sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column("notification", "read_at")
