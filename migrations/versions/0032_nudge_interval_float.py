"""convert nudge interval columns to float

Revision ID: 0032_nudge_interval_float
Revises: 0031_merge_guest_form_head
Create Date: 2026-03-07 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0032_nudge_interval_float"
down_revision = "0031_merge_guest_form_head"
branch_labels = None
depends_on = None


def upgrade():
    # change nudge interval and min delay to FLOAT so fractional hours are allowed
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite doesn't support ALTER COLUMN, so use workaround: recreate table
        op.execute("PRAGMA foreign_keys=off")
        op.execute("BEGIN TRANSACTION")
        op.execute(
            "CREATE TABLE special_email_config_new AS SELECT * FROM special_email_config"
        )
        op.execute("DROP TABLE special_email_config")
        op.create_table(
            "special_email_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("help_email", sa.String(length=255), nullable=True),
            sa.Column("request_form_email", sa.String(length=255), nullable=True),
            sa.Column("request_form_first_message", sa.Text(), nullable=True),
            sa.Column(
                "help_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True
            ),
            sa.Column(
                "request_form_user_id",
                sa.Integer(),
                sa.ForeignKey("user.id"),
                nullable=True,
            ),
            sa.Column(
                "email_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "ticketing_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "inventory_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "nudge_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("nudge_interval_hours", sa.Float(), nullable=True),
            sa.Column("nudge_min_delay_hours", sa.Float(), nullable=True),
        )
        op.execute(
            "INSERT INTO special_email_config SELECT * FROM special_email_config_new"
        )
        op.execute("DROP TABLE special_email_config_new")
        op.execute("PRAGMA foreign_keys=on")
        op.execute("COMMIT")
    else:
        op.alter_column(
            "special_email_config",
            "nudge_interval_hours",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            nullable=True,
        )
        op.alter_column(
            "special_email_config",
            "nudge_min_delay_hours",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            nullable=True,
        )


def downgrade():
    # revert back to integer (possible data truncation)
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA foreign_keys=off")
        op.execute("BEGIN TRANSACTION")
        op.execute(
            "CREATE TABLE special_email_config_new AS SELECT * FROM special_email_config"
        )
        op.execute("DROP TABLE special_email_config")
        op.create_table(
            "special_email_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("help_email", sa.String(length=255), nullable=True),
            sa.Column("request_form_email", sa.String(length=255), nullable=True),
            sa.Column("request_form_first_message", sa.Text(), nullable=True),
            sa.Column(
                "help_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True
            ),
            sa.Column(
                "request_form_user_id",
                sa.Integer(),
                sa.ForeignKey("user.id"),
                nullable=True,
            ),
            sa.Column(
                "email_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "ticketing_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "inventory_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "nudge_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("nudge_interval_hours", sa.Integer(), nullable=True),
            sa.Column("nudge_min_delay_hours", sa.Integer(), nullable=True),
        )
        op.execute(
            "INSERT INTO special_email_config SELECT * FROM special_email_config_new"
        )
        op.execute("DROP TABLE special_email_config_new")
        op.execute("PRAGMA foreign_keys=on")
        op.execute("COMMIT")
    else:
        op.alter_column(
            "special_email_config",
            "nudge_interval_hours",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            nullable=True,
        )
        op.alter_column(
            "special_email_config",
            "nudge_min_delay_hours",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            nullable=True,
        )
