"""add form_submission table

Revision ID: 0014_add_form_submission
Revises: 0013_add_status_buckets
Create Date: 2026-03-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0014_add_form_submission"
down_revision = "0013_add_status_buckets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_submission",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("form_template.id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("form_submission")
