"""Add verification_prefill_enabled to form_template (safe checks)

Revision ID: zz_add_form_template_prefill_toggle
Revises:
Create Date: 2026-03-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "zz_add_form_template_prefill_toggle"
down_revision = None
branch_labels = None
depends_on = None


def _has_column(conn, table_name, column_name):
    insp = inspect(conn)
    try:
        cols = [c["name"] for c in insp.get_columns(table_name)]
        return column_name in cols
    except Exception:
        return False


def upgrade():
    conn = op.get_bind()
    if not _has_column(conn, "form_template", "verification_prefill_enabled"):
        op.add_column(
            "form_template",
            sa.Column(
                "verification_prefill_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, "form_template", "verification_prefill_enabled"):
        op.drop_column("form_template", "verification_prefill_enabled")