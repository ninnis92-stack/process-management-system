"""add user notification coverage fields

Revision ID: 0007_user_notification_coverage
Revises: 0006_admin_user_workflow_features
Create Date: 2026-03-09 23:55:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_user_notification_coverage"
down_revision = "0006_admin_user_workflow_features"
branch_labels = None
depends_on = None


USER_COLUMNS = [
    sa.Column("notification_departments_json", sa.Text(), nullable=True),
    sa.Column("backup_approver_user_id", sa.Integer(), nullable=True),
]


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch_op:
            for column in USER_COLUMNS:
                batch_op.add_column(column)
        with op.batch_alter_table("user") as batch_op:
            batch_op.create_foreign_key(
                "fk_user_backup_approver_user_id_user",
                "user",
                ["backup_approver_user_id"],
                ["id"],
            )
            batch_op.create_index(
                "ix_user_backup_approver_user_id",
                ["backup_approver_user_id"],
                unique=False,
            )
    else:
        for column in USER_COLUMNS:
            op.add_column("user", column)
        op.create_foreign_key(
            "fk_user_backup_approver_user_id_user",
            "user",
            "user",
            ["backup_approver_user_id"],
            ["id"],
        )
        op.create_index(
            "ix_user_backup_approver_user_id",
            "user",
            ["backup_approver_user_id"],
            unique=False,
        )


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_index("ix_user_backup_approver_user_id")
            batch_op.drop_constraint(
                "fk_user_backup_approver_user_id_user", type_="foreignkey"
            )
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_column("backup_approver_user_id")
            batch_op.drop_column("notification_departments_json")
    else:
        op.drop_index("ix_user_backup_approver_user_id", table_name="user")
        op.drop_constraint(
            "fk_user_backup_approver_user_id_user", "user", type_="foreignkey"
        )
        op.drop_column("user", "backup_approver_user_id")
        op.drop_column("user", "notification_departments_json")
