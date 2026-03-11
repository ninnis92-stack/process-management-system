"""add status buckets and bucket_status

Revision ID: 0013_add_status_buckets
Revises: 0012_add_form_templates
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_add_status_buckets"
down_revision = "0012_add_form_templates"
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    if 'status_bucket' not in tables:
        op.create_table(
            "status_bucket",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("department_id", sa.Integer(), nullable=True),
            sa.Column("department_name", sa.String(length=150), nullable=True),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if 'bucket_status' not in tables:
        op.create_table(
            "bucket_status",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "bucket_id", sa.Integer(), sa.ForeignKey("status_bucket.id"), nullable=False
            ),
            sa.Column("status_code", sa.String(length=80), nullable=False),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade():
    op.drop_table("bucket_status")
    op.drop_table("status_bucket")
