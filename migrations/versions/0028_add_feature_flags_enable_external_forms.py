"""add enable_external_forms to feature_flags

Revision ID: 0028_add_feature_flags_enable_external_forms
Revises: 0027_merge_heads_0026
Create Date: 2026-03-07 01:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "0028_add_feature_flags_enable_external_forms"
down_revision = "0027_merge_heads_0026"
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
    if not _has_column(conn, "feature_flags", "enable_external_forms"):
        col = sa.Column(
            "enable_external_forms",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0" if conn.dialect.name == "sqlite" else "false"),
        )
        if conn.dialect.name == "sqlite":
            with op.batch_alter_table("feature_flags") as batch_op:
                batch_op.add_column(col)
        else:
            op.add_column("feature_flags", col)
    try:
        op.alter_column(
            "feature_flags",
            "enable_external_forms",
            server_default=sa.text("0" if conn.dialect.name == "sqlite" else "false"),
            existing_type=sa.Boolean(),
        )
    except Exception:
        pass


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, "feature_flags", "enable_external_forms"):
        if conn.dialect.name == "sqlite":
            with op.batch_alter_table("feature_flags") as batch_op:
                batch_op.drop_column("enable_external_forms")
        else:
            op.drop_column("feature_flags", "enable_external_forms")
