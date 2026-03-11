"""empty message

Revision ID: 0009_add_workflow
Revises: 0008_add_email_routing
Create Date: 2026-03-06 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_add_workflow"
down_revision = "0008_add_email_routing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("department_code", sa.String(length=2), nullable=True),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("workflow")
