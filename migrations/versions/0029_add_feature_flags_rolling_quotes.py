"""add rolling_quotes_enabled to feature_flags

Revision ID: 0029_add_feature_flags_rolling_quotes
Revises: 0028_add_feature_flags_enable_external_forms
Create Date: 2026-03-07 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "0029_add_feature_flags_rolling_quotes"
down_revision = "0028_add_feature_flags_enable_external_forms"
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
    if _has_column(conn, "feature_flags", "rolling_quotes_enabled"):
        return
    col = sa.Column(
        "rolling_quotes_enabled",
        sa.Boolean(),
        nullable=False,
        server_default=sa.text("1" if conn.dialect.name == "sqlite" else "true"),
    )
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("feature_flags") as batch_op:
            batch_op.add_column(col)
    else:
        op.add_column("feature_flags", col)


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, "feature_flags", "rolling_quotes_enabled"):
        if conn.dialect.name == "sqlite":
            with op.batch_alter_table("feature_flags") as batch_op:
                batch_op.drop_column("rolling_quotes_enabled")
        else:
            op.drop_column("feature_flags", "rolling_quotes_enabled")
