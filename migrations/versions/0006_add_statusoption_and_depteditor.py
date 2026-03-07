"""add StatusOption and DepartmentEditor tables, add sales_list_reference

Revision ID: 0006_add_statusoption_and_depteditor
Revises: 0005_add_vibe_index
Create Date: 2026-03-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0006_add_statusoption_and_depteditor"
down_revision = "0005_add_vibe_index"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Create status_option table
    op.create_table(
        "status_option",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("target_department", sa.String(2), nullable=True),
        sa.Column(
            "notify_on_transfer_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "notify_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    # Create department_editor table
    op.create_table(
        "department_editor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("department", sa.String(2), nullable=False),
        sa.Column(
            "can_edit", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
    )

    # Add unique constraint for user_id + department
    op.create_unique_constraint(
        "uq_user_dept_editor", "department_editor", ["user_id", "department"]
    )

    # Add sales_list_reference column to request table
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("request") as batch_op:
            batch_op.add_column(
                sa.Column("sales_list_reference", sa.String(200), nullable=True)
            )
    else:
        op.add_column(
            "request", sa.Column("sales_list_reference", sa.String(200), nullable=True)
        )


def downgrade():
    conn = op.get_bind()
    # remove sales_list_reference
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("request") as batch_op:
            batch_op.drop_column("sales_list_reference")
    else:
        op.drop_column("request", "sales_list_reference")

    # drop department_editor then status_option
    op.drop_constraint("uq_user_dept_editor", "department_editor", type_="unique")
    op.drop_table("department_editor")
    op.drop_table("status_option")
