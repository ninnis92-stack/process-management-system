"""add missing workflow and status option flags

Revision ID: 0030_add_missing_workflow_and_status_flags
Revises: 0029_add_feature_flags_rolling_quotes
Create Date: 2026-03-07 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "0030_add_missing_workflow_and_status_flags"
down_revision = "0029_add_feature_flags_rolling_quotes"
branch_labels = None
depends_on = None


def _has_column(conn, table_name, column_name):
    insp = inspect(conn)
    try:
        cols = [c["name"] for c in insp.get_columns(table_name)]
        return column_name in cols
    except Exception:
        return False


def _add_column_if_missing(table_name, column):
    conn = op.get_bind()
    if _has_column(conn, table_name, column.name):
        return
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)
    else:
        op.add_column(table_name, column)


def _drop_column_if_present(table_name, column_name):
    conn = op.get_bind()
    if not _has_column(conn, table_name, column_name):
        return
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column(column_name)
    else:
        op.drop_column(table_name, column_name)


def upgrade():
    _add_column_if_missing(
        "workflow",
        sa.Column(
            "implementation_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    _add_column_if_missing(
        "status_option",
        sa.Column(
            "executive_approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    _add_column_if_missing(
        "status_option",
        sa.Column(
            "sales_list_number_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade():
    _drop_column_if_present("status_option", "sales_list_number_required")
    _drop_column_if_present("status_option", "executive_approval_required")
    _drop_column_if_present("workflow", "implementation_pending")
