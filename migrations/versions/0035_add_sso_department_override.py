"""add sso department override controls

Revision ID: 0035_add_sso_department_override
Revises: 0034_tenant_compatibility_foundation
Create Date: 2026-03-07 00:00:01.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0035_add_sso_department_override"
down_revision = "0034_tenant_compatibility_foundation"
branch_labels = None
depends_on = None


def _has_column(conn, table_name, column_name):
    try:
        return column_name in {c["name"] for c in inspect(conn).get_columns(table_name)}
    except Exception:
        return False


def upgrade():
    conn = op.get_bind()

    if not _has_column(conn, "user", "department_override"):
        op.add_column(
            "user",
            sa.Column(
                "department_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _has_column(conn, "feature_flags", "sso_department_sync_enabled"):
        op.add_column(
            "feature_flags",
            sa.Column(
                "sso_department_sync_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade():
    conn = op.get_bind()

    if _has_column(conn, "feature_flags", "sso_department_sync_enabled"):
        op.drop_column("feature_flags", "sso_department_sync_enabled")

    if _has_column(conn, "user", "department_override"):
        op.drop_column("user", "department_override")
