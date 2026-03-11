"""add auto reject toggle for special email config

Revision ID: 0021_add_auto_reject_oos_toggle
Revises: 0020_add_site_branding_fields
Create Date: 2026-03-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0021_add_auto_reject_oos_toggle"
down_revision = "0020_add_site_branding_fields"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col['name'] for col in insp.get_columns('special_email_config')]
    if "request_form_auto_reject_oos_enabled" not in columns:
        col = sa.Column(
            "request_form_auto_reject_oos_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        )
        if conn.dialect.name == "sqlite":
            with op.batch_alter_table("special_email_config") as batch_op:
                batch_op.add_column(col)
        else:
            op.add_column("special_email_config", col)


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("special_email_config") as batch_op:
            batch_op.drop_column("request_form_auto_reject_oos_enabled")
    else:
        op.drop_column("special_email_config", "request_form_auto_reject_oos_enabled")
