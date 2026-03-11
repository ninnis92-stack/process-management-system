"""add automation rules table

Revision ID: 0051_add_automation_rules
Revises: 0050_add_email_original_sender_and_watchers
Create Date: 2026-03-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0051_add_automation_rules"
down_revision = "0050_add_email_original_sender_and_watchers"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0051_add_automation_rules"
down_revision = "0050_add_email_original_sender_and_watchers"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "automation_rule" not in inspector.get_table_names():
        op.create_table(
            "automation_rule",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenant.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("triggers_json", sa.JSON(), nullable=True),
            sa.Column("conditions_json", sa.JSON(), nullable=True),
            sa.Column("actions_json", sa.JSON(), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
            ),
        )
