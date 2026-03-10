"""add admin user workflow features

Revision ID: 0006_admin_user_workflow_features
Revises: 0005_add_vibe_index
Create Date: 2026-03-09 22:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0006_admin_user_workflow_features"
down_revision = "0005_add_vibe_index"
branch_labels = None
depends_on = None


USER_COLUMNS = [
    sa.Column("preferred_start_page", sa.String(length=40), nullable=True, server_default=sa.text("'dashboard'")),
    sa.Column("preferred_start_department", sa.String(length=2), nullable=True),
    sa.Column("watched_departments_json", sa.Text(), nullable=True),
    sa.Column("workflow_role_profile", sa.String(length=40), nullable=True, server_default=sa.text("'member'")),
]


USER_DEPARTMENT_COLUMNS = [
    sa.Column("assignment_kind", sa.String(length=20), nullable=False, server_default=sa.text("'shared'")),
    sa.Column("note", sa.String(length=255), nullable=True),
    sa.Column("expires_at", sa.DateTime(), nullable=True),
]


DEPARTMENT_EDITOR_COLUMNS = [
    sa.Column("managed_by_profile", sa.Boolean(), nullable=False, server_default=sa.false()),
]



def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch_op:
            for column in USER_COLUMNS:
                batch_op.add_column(column)
        with op.batch_alter_table("user_department") as batch_op:
            for column in USER_DEPARTMENT_COLUMNS:
                batch_op.add_column(column)
        with op.batch_alter_table("department_editor") as batch_op:
            for column in DEPARTMENT_EDITOR_COLUMNS:
                batch_op.add_column(column)
    else:
        for column in USER_COLUMNS:
            op.add_column("user", column)
        for column in USER_DEPARTMENT_COLUMNS:
            op.add_column("user_department", column)
        for column in DEPARTMENT_EDITOR_COLUMNS:
            op.add_column("department_editor", column)



def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("department_editor") as batch_op:
            batch_op.drop_column("managed_by_profile")
        with op.batch_alter_table("user_department") as batch_op:
            batch_op.drop_column("expires_at")
            batch_op.drop_column("note")
            batch_op.drop_column("assignment_kind")
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_column("workflow_role_profile")
            batch_op.drop_column("watched_departments_json")
            batch_op.drop_column("preferred_start_department")
            batch_op.drop_column("preferred_start_page")
    else:
        op.drop_column("department_editor", "managed_by_profile")
        op.drop_column("user_department", "expires_at")
        op.drop_column("user_department", "note")
        op.drop_column("user_department", "assignment_kind")
        op.drop_column("user", "workflow_role_profile")
        op.drop_column("user", "watched_departments_json")
        op.drop_column("user", "preferred_start_department")
        op.drop_column("user", "preferred_start_page")
