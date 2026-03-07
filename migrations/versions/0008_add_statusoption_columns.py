"""add screenshot/email/originator columns to status_option

Revision ID: 0008_add_statusoption_columns
Revises: 0007_add_integration_config
Create Date: 2026-03-07 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0008_add_statusoption_columns"
down_revision = "0007_add_integration_config"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Add boolean columns with safe defaults
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("status_option") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "screenshot_required",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
            batch_op.add_column(
                sa.Column(
                    "email_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
            batch_op.add_column(
                sa.Column(
                    "notify_to_originator_only",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
    else:
        op.add_column(
            "status_option",
            sa.Column(
                "screenshot_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        op.add_column(
            "status_option",
            sa.Column(
                "email_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        op.add_column(
            "status_option",
            sa.Column(
                "notify_to_originator_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("status_option") as batch_op:
            batch_op.drop_column("notify_to_originator_only")
            batch_op.drop_column("email_enabled")
            batch_op.drop_column("screenshot_required")
    else:
        op.drop_column("status_option", "notify_to_originator_only")
        op.drop_column("status_option", "email_enabled")
        op.drop_column("status_option", "screenshot_required")
