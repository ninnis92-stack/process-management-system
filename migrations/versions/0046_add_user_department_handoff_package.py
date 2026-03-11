"""add user department handoff package fields

Revision ID: 0046_add_user_department_handoff_package
Revises: 0045_add_template_layout_columns
Create Date: 2026-03-10 00:20:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0046_add_user_department_handoff_package"
down_revision = "0045_add_template_layout_columns"
branch_labels = None
depends_on = None


USER_DEPARTMENT_COLUMNS = [
    sa.Column("handoff_doc_url", sa.String(length=500), nullable=True),
    sa.Column("handoff_checklist_json", sa.Text(), nullable=True),
]


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user_department") as batch_op:
            for column in USER_DEPARTMENT_COLUMNS:
                batch_op.add_column(column)
    else:
        for column in USER_DEPARTMENT_COLUMNS:
            op.add_column("user_department", column)


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user_department") as batch_op:
            batch_op.drop_column("handoff_checklist_json")
            batch_op.drop_column("handoff_doc_url")
    else:
        op.drop_column("user_department", "handoff_checklist_json")
        op.drop_column("user_department", "handoff_doc_url")
