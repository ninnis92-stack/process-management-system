"""add field verification table

Revision ID: 0010_add_field_verification
Revises: 0009_add_workflow
Create Date: 2026-03-06 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_add_field_verification"
down_revision = "0009_add_workflow"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("field_verification"):
        op.create_table(
            "field_verification",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "field_id", sa.Integer(), sa.ForeignKey("form_field.id"), nullable=False
            ),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("external_key", sa.String(length=200), nullable=True),
            sa.Column("params", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table("field_verification")
