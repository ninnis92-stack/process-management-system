"""add reject_request_config table

Revision ID: 0015_add_reject_request_config
Revises: 0014_add_form_submission
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_add_reject_request_config"
down_revision = "0014_add_form_submission"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    if 'reject_request_config' not in tables:
        op.create_table(
            "reject_request_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "button_label",
                sa.String(length=120),
                nullable=False,
                server_default="Reject Request",
            ),
            sa.Column("rejection_message", sa.Text(), nullable=True),
            sa.Column(
                "dept_a_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "dept_b_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "dept_c_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table("reject_request_config")
