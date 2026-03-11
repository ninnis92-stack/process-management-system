"""add workflow_id to status_bucket

Revision ID: 0024_add_status_bucket_workflow
Revises: 0023_add_user_department_and_last_active
Create Date: 2026-03-07 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0024_add_status_bucket_workflow"
down_revision = "0023_add_user_department_and_last_active"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    col = sa.Column("workflow_id", sa.Integer(), nullable=True)
    if conn.dialect.name == "sqlite":
        # use batch_alter_table for SQLite
        with op.batch_alter_table("status_bucket") as batch_op:
            batch_op.add_column(col)
    else:
        op.add_column("status_bucket", col)
        # add FK constraint if DB supports it
        try:
            op.create_foreign_key(
                "fk_status_bucket_workflow",
                "status_bucket",
                "workflow",
                ["workflow_id"],
                ["id"],
            )
        except Exception:
            pass


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("status_bucket") as batch_op:
            batch_op.drop_column("workflow_id")
    else:
        try:
            op.drop_constraint(
                "fk_status_bucket_workflow", "status_bucket", type_="foreignkey"
            )
        except Exception:
            pass
        op.drop_column("status_bucket", "workflow_id")
