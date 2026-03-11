"""Add external form integration columns to FormTemplate (safe checks)

Revision ID: zz_add_external_form_template_fields
Revises:
Create Date: 2026-03-07 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "zz_add_external_form_template_fields"
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
    # Only add columns if they don't already exist; this makes the migration
    # safer to apply against DBs that may already have these fields applied
    # via an out-of-band release script.
    if not _has_column(conn, "form_template", "external_enabled"):
        op.add_column(
            "form_template",
            sa.Column(
                "external_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if not _has_column(conn, "form_template", "external_provider"):
        op.add_column(
            "form_template",
            sa.Column("external_provider", sa.String(length=100), nullable=True),
        )
    if not _has_column(conn, "form_template", "external_form_url"):
        op.add_column(
            "form_template",
            sa.Column("external_form_url", sa.String(length=1000), nullable=True),
        )
    if not _has_column(conn, "form_template", "external_form_id"):
        op.add_column(
            "form_template",
            sa.Column("external_form_id", sa.String(length=255), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, "form_template", "external_form_id"):
        op.drop_column("form_template", "external_form_id")
    if _has_column(conn, "form_template", "external_form_url"):
        op.drop_column("form_template", "external_form_url")
    if _has_column(conn, "form_template", "external_provider"):
        op.drop_column("form_template", "external_provider")
    if _has_column(conn, "form_template", "external_enabled"):
        op.drop_column("form_template", "external_enabled")
