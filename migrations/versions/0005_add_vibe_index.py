"""add vibe_index to user

Revision ID: 0005_add_vibe_index
Revises: 0004_add_auditlog_event_ts
Create Date: 2026-03-04 20:50:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_add_vibe_index"
down_revision = "0004_add_auditlog_event_ts"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('user')]
    if 'vibe_index' not in columns:
        op.add_column(
            "user",
            sa.Column(
                "vibe_index", sa.Integer(), nullable=True, server_default=sa.text("0")
            ),
        )


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_column("vibe_index")
    else:
        op.drop_column("user", "vibe_index")
