"""add process flow groups and steps

Revision ID: 0006_add_process_flow_groups
Revises: 0005_add_vibe_index
Create Date: 2026-03-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0006_add_process_flow_groups"
down_revision = "0005_add_vibe_index"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    op.create_table(
        "process_flow_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_flow_group_name", "process_flow_group", ["name"], unique=True)

    op.create_table(
        "process_flow_step",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("flow_group_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("actor_department", sa.String(length=1), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=False),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("from_department", sa.String(length=1), nullable=True),
        sa.Column("to_department", sa.String(length=1), nullable=True),
        sa.Column("requires_submission", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["flow_group_id"], ["process_flow_group.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_flow_step_flow_group_id", "process_flow_step", ["flow_group_id"], unique=False)

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("request") as batch_op:
            batch_op.add_column(sa.Column("flow_group_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key("fk_request_flow_group", "process_flow_group", ["flow_group_id"], ["id"])
    else:
        op.add_column("request", sa.Column("flow_group_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_request_flow_group", "request", "process_flow_group", ["flow_group_id"], ["id"])


def downgrade():
    conn = op.get_bind()

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("request") as batch_op:
            batch_op.drop_constraint("fk_request_flow_group", type_="foreignkey")
            batch_op.drop_column("flow_group_id")
    else:
        op.drop_constraint("fk_request_flow_group", "request", type_="foreignkey")
        op.drop_column("request", "flow_group_id")

    op.drop_index("ix_process_flow_step_flow_group_id", table_name="process_flow_step")
    op.drop_table("process_flow_step")

    op.drop_index("ix_process_flow_group_name", table_name="process_flow_group")
    op.drop_table("process_flow_group")
