"""add metrics tracking tables and department-head metrics permission

Revision ID: 0033_add_metrics_tracking_and_dept_head_role
Revises: 0032_nudge_interval_float
Create Date: 2026-03-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "0033_add_metrics_tracking_and_dept_head_role"
down_revision = "0032_nudge_interval_float"
branch_labels = None
depends_on = None


def _has_column(conn, table_name, column_name):
    insp = inspect(conn)
    try:
        cols = [c["name"] for c in insp.get_columns(table_name)]
        return column_name in cols
    except Exception:
        return False


def _has_table(conn, table_name):
    insp = inspect(conn)
    try:
        return table_name in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    conn = op.get_bind()

    if _has_table(conn, "department_editor") and not _has_column(conn, "department_editor", "can_view_metrics"):
        op.add_column(
            "department_editor",
            sa.Column("can_view_metrics", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )

    if not _has_table(conn, "metrics_config"):
        op.create_table(
            "metrics_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("track_request_created", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("track_assignments", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("track_status_changes", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("user_metrics_limit", sa.Integer(), nullable=False, server_default="15"),
            sa.Column("target_completion_hours", sa.Integer(), nullable=False, server_default="48"),
            sa.Column("slow_event_threshold_hours", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if not _has_table(conn, "process_metric_event"):
        op.create_table(
            "process_metric_event",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("request_id", sa.Integer(), sa.ForeignKey("request.id"), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("actor_department", sa.String(length=2), nullable=True),
            sa.Column("owner_department", sa.String(length=2), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("from_status", sa.String(length=40), nullable=True),
            sa.Column("to_status", sa.String(length=40), nullable=True),
            sa.Column("assigned_to_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("since_last_event_seconds", sa.Integer(), nullable=True),
            sa.Column("request_age_seconds", sa.Integer(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_process_metric_event_request_id", "process_metric_event", ["request_id"])
        op.create_index("ix_process_metric_event_actor_user_id", "process_metric_event", ["actor_user_id"])
        op.create_index("ix_process_metric_event_owner_department", "process_metric_event", ["owner_department"])
        op.create_index("ix_process_metric_event_event_type", "process_metric_event", ["event_type"])
        op.create_index("ix_process_metric_event_created_at", "process_metric_event", ["created_at"])


def downgrade():
    conn = op.get_bind()

    if _has_table(conn, "process_metric_event"):
        op.drop_index("ix_process_metric_event_created_at", table_name="process_metric_event")
        op.drop_index("ix_process_metric_event_event_type", table_name="process_metric_event")
        op.drop_index("ix_process_metric_event_owner_department", table_name="process_metric_event")
        op.drop_index("ix_process_metric_event_actor_user_id", table_name="process_metric_event")
        op.drop_index("ix_process_metric_event_request_id", table_name="process_metric_event")
        op.drop_table("process_metric_event")

    if _has_table(conn, "metrics_config"):
        op.drop_table("metrics_config")

    if _has_table(conn, "department_editor") and _has_column(conn, "department_editor", "can_view_metrics"):
        op.drop_column("department_editor", "can_view_metrics")
