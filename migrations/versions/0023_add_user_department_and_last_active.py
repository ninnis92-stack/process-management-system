"""add user department table and last_active_dept column

Revision ID: 0023_add_user_department_and_last_active
Revises: 0022_add_sso_admin_sync_flag
Create Date: 2026-03-06 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "0023_add_user_department_and_last_active"
down_revision = "0022_add_sso_admin_sync_flag"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Add last_active_dept column to user
    col = sa.Column("last_active_dept", sa.String(length=2), nullable=True)
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch_op:
            batch_op.add_column(col)
    else:
        op.add_column("user", col)

    # Create user_department table
    op.create_table(
        "user_department",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("department", sa.String(length=2), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "department", name="uq_user_department"),
    )


def downgrade():
    conn = op.get_bind()

    # Drop user_department table
    op.drop_table("user_department")

    # Drop last_active_dept column from user
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_column("last_active_dept")
    else:
        op.drop_column("user", "last_active_dept")
