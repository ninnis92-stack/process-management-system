"""Add dark_mode to user (safe/idempotent)

Revision ID: 0026_add_user_dark_mode
Revises: zz_add_external_form_template_fields
Create Date: 2026-03-07 00:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "0026_add_user_dark_mode"
down_revision = "zz_add_external_form_template_fields"
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
    if not _has_column(conn, "user", "dark_mode"):
        # Add boolean column with default False; use batch_alter_table for SQLite
        if conn.dialect.name == "sqlite":
            with op.batch_alter_table("user") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "dark_mode",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
        else:
            op.add_column(
                "user",
                sa.Column(
                    "dark_mode",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                ),
            )


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, "user", "dark_mode"):
        if conn.dialect.name == "sqlite":
            with op.batch_alter_table("user") as batch_op:
                batch_op.drop_column("dark_mode")
        else:
            op.drop_column("user", "dark_mode")
