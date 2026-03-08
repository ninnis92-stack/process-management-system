"""add temporary tenant compatibility foundation

Revision ID: 0034_tenant_compatibility_foundation
Revises: 0033_add_metrics_tracking_and_dept_head_role
Create Date: 2026-03-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision = "0034_tenant_compatibility_foundation"
down_revision = "0033_add_metrics_tracking_and_dept_head_role"
branch_labels = None
depends_on = None


TENANT_SCOPED_TABLES = [
    "audit_log",
    "department",
    "department_editor",
    "department_form_assignment",
    "email_routing",
    "feature_flags",
    "form_template",
    "guest_form",
    "integration_config",
    "integration_event",
    "job_record",
    "metrics_config",
    "notification",
    "notification_retention",
    "process_metric_event",
    "reject_request_config",
    "request",
    "site_config",
    "special_email_config",
    "status_bucket",
    "status_option",
    "user",
    "user_department",
    "webhook_subscription",
    "workflow",
]


def _insp(conn):
    return inspect(conn)


def _has_table(conn, table_name):
    try:
        return table_name in _insp(conn).get_table_names()
    except Exception:
        return False


def _has_column(conn, table_name, column_name):
    try:
        return column_name in {c["name"] for c in _insp(conn).get_columns(table_name)}
    except Exception:
        return False


def _has_index(conn, table_name, index_name):
    try:
        return index_name in {i["name"] for i in _insp(conn).get_indexes(table_name)}
    except Exception:
        return False


def _quote(name):
    return '"%s"' % name.replace('"', '""')


def _ensure_tenant_id_column(conn, table_name):
    if not _has_table(conn, table_name) or _has_column(conn, table_name, "tenant_id"):
        return

    op.add_column(table_name, sa.Column("tenant_id", sa.Integer(), nullable=True))

    index_name = f"ix_{table_name}_tenant_id"
    if not _has_index(conn, table_name, index_name):
        op.create_index(index_name, table_name, ["tenant_id"], unique=False)


def _seed_default_plan_and_tenant(conn):
    growth_plan_id = conn.execute(
        text("SELECT id FROM subscription_plan WHERE code = :code"),
        {"code": "growth"},
    ).scalar()
    if growth_plan_id is None:
        conn.execute(
            text(
                """
                INSERT INTO subscription_plan (
                    code,
                    name,
                    description,
                    max_users,
                    max_requests_per_month,
                    max_departments,
                    active
                )
                VALUES (
                    :code,
                    :name,
                    :description,
                    :max_users,
                    :max_requests_per_month,
                    :max_departments,
                    :active
                )
                """
            ),
            {
                "code": "growth",
                "name": "Growth",
                "description": "Temporary default plan for tenant compatibility rollout.",
                "max_users": 50,
                "max_requests_per_month": 5000,
                "max_departments": 12,
                "active": True,
            },
        )
        growth_plan_id = conn.execute(
            text("SELECT id FROM subscription_plan WHERE code = :code"),
            {"code": "growth"},
        ).scalar()

    tenant_id = conn.execute(
        text("SELECT id FROM tenant WHERE slug = :slug"),
        {"slug": "default"},
    ).scalar()
    if tenant_id is None:
        conn.execute(
            text(
                """
                INSERT INTO tenant (slug, name, plan_id, is_active)
                VALUES (:slug, :name, :plan_id, :is_active)
                """
            ),
            {
                "slug": "default",
                "name": "Default Workspace",
                "plan_id": growth_plan_id,
                "is_active": True,
            },
        )
        tenant_id = conn.execute(
            text("SELECT id FROM tenant WHERE slug = :slug"),
            {"slug": "default"},
        ).scalar()

    return tenant_id


def _backfill_tenant_ids(conn, tenant_id):
    for table_name in TENANT_SCOPED_TABLES:
        if not _has_table(conn, table_name) or not _has_column(conn, table_name, "tenant_id"):
            continue
        conn.execute(
            text(
                f"UPDATE {_quote(table_name)} SET tenant_id = :tenant_id WHERE tenant_id IS NULL"
            ),
            {"tenant_id": tenant_id},
        )


def _backfill_user_memberships(conn, tenant_id):
    if not _has_table(conn, "user"):
        return

    users = conn.execute(text('SELECT id, COALESCE(is_admin, false) AS is_admin FROM "user"')).fetchall()
    for user_id, is_admin in users:
        exists = conn.execute(
            text(
                """
                SELECT id
                FROM tenant_membership
                WHERE tenant_id = :tenant_id AND user_id = :user_id
                """
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        ).scalar()
        if exists is not None:
            continue

        conn.execute(
            text(
                """
                INSERT INTO tenant_membership (
                    tenant_id,
                    user_id,
                    role,
                    is_default,
                    is_active
                )
                VALUES (
                    :tenant_id,
                    :user_id,
                    :role,
                    :is_default,
                    :is_active
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": "tenant_admin" if is_admin else "member",
                "is_default": True,
                "is_active": True,
            },
        )


def upgrade():
    conn = op.get_bind()

    if not _has_table(conn, "subscription_plan"):
        op.create_table(
            "subscription_plan",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("max_users", sa.Integer(), nullable=False, server_default="25"),
            sa.Column(
                "max_requests_per_month",
                sa.Integer(),
                nullable=False,
                server_default="2000",
            ),
            sa.Column("max_departments", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("feature_flags_json", sa.JSON(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_subscription_plan_code", "subscription_plan", ["code"], unique=True)

    if not _has_table(conn, "tenant"):
        op.create_table(
            "tenant",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_tenant_slug", "tenant", ["slug"], unique=True)

    if not _has_table(conn, "tenant_membership"):
        op.create_table(
            "tenant_membership",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=40), nullable=False, server_default="member"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user_membership"),
        )
        op.create_index("ix_tenant_membership_tenant_id", "tenant_membership", ["tenant_id"], unique=False)
        op.create_index("ix_tenant_membership_user_id", "tenant_membership", ["user_id"], unique=False)

    for table_name in TENANT_SCOPED_TABLES:
        _ensure_tenant_id_column(conn, table_name)

    tenant_id = _seed_default_plan_and_tenant(conn)
    _backfill_tenant_ids(conn, tenant_id)
    _backfill_user_memberships(conn, tenant_id)


def downgrade():
    # Intentional no-op: this is a temporary compatibility migration that
    # backfills shared tenant ownership into existing data. Rolling it back
    # safely would be destructive and environment-specific.
    pass
