"""Add section_name and requirement_rules to form_field (safe checks)

Revision ID: zz_add_form_field_sections_and_requirements
Revises:
Create Date: 2026-03-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "zz_add_form_field_sections_and_requirements"
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
    if not _has_column(conn, "form_field", "section_name"):
        op.add_column(
            "form_field",
            sa.Column("section_name", sa.String(length=200), nullable=True),
        )
    if not _has_column(conn, "form_field", "requirement_rules"):
        op.add_column(
            "form_field",
            sa.Column("requirement_rules", sa.JSON(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, "form_field", "requirement_rules"):
        op.drop_column("form_field", "requirement_rules")
    if _has_column(conn, "form_field", "section_name"):
        op.drop_column("form_field", "section_name")