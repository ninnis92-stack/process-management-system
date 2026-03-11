"""add event_ts to audit_log

Revision ID: 0004_add_auditlog_event_ts
Revises: 0003_auditlog_request_nullable
Create Date: 2026-03-04 18:50:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_add_auditlog_event_ts"
down_revision = "0003_auditlog_request_nullable"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('audit_log')]
    if 'event_ts' not in columns:
        op.add_column(
            "audit_log",
            sa.Column(
                "event_ts",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("audit_log") as batch_op:
            batch_op.drop_column("event_ts")
    else:
        op.drop_column("audit_log", "event_ts")
