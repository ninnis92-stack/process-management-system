"""add guest page feature flags

Revision ID: 0048_add_guest_page_feature_flags
Revises: 0047_add_department_handoff_defaults
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0048_add_guest_page_feature_flags"
down_revision = "0047_add_department_handoff_defaults"
branch_labels = None
depends_on = None


def _has_column(conn, table_name, column_name):
    insp = inspect(conn)
    try:
        cols = [c["name"] for c in insp.get_columns(table_name)]
        return column_name in cols
    except Exception:
        return False


def _add_boolean(conn, name):
    col = sa.Column(
        name,
        sa.Boolean(),
        nullable=False,
        server_default=sa.text("1" if conn.dialect.name == "sqlite" else "true"),
    )
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("feature_flags") as batch_op:
            batch_op.add_column(col)
    else:
        op.add_column("feature_flags", col)


def upgrade():
    conn = op.get_bind()
    if not _has_column(conn, "feature_flags", "guest_dashboard_enabled"):
        _add_boolean(conn, "guest_dashboard_enabled")
    if not _has_column(conn, "feature_flags", "guest_submission_enabled"):
        _add_boolean(conn, "guest_submission_enabled")


def downgrade():
    conn = op.get_bind()
    for name in ("guest_submission_enabled", "guest_dashboard_enabled"):
        if _has_column(conn, "feature_flags", name):
            if conn.dialect.name == "sqlite":
                with op.batch_alter_table("feature_flags") as batch_op:
                    batch_op.drop_column(name)
            else:
                op.drop_column("feature_flags", name)