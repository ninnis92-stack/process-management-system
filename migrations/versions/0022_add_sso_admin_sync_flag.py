"""add sso admin sync flag

Revision ID: 0022_add_sso_admin_sync_flag
Revises: 0021_add_auto_reject_oos_toggle
Create Date: 2026-03-06 00:00:01.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "0022_add_sso_admin_sync_flag"
down_revision = "0021_add_auto_reject_oos_toggle"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    col = sa.Column(
        "sso_admin_sync_enabled",
        sa.Boolean(),
        nullable=False,
        server_default=sa.text("1"),
    )
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("feature_flags") as batch_op:
            batch_op.add_column(col)
    else:
        op.add_column("feature_flags", col)


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("feature_flags") as batch_op:
            batch_op.drop_column("sso_admin_sync_enabled")
    else:
        op.drop_column("feature_flags", "sso_admin_sync_enabled")
