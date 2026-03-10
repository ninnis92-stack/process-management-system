"""add department handoff default fields

Revision ID: 0047_add_department_handoff_defaults
Revises: 0046_add_user_department_handoff_package
Create Date: 2026-03-10 00:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0047_add_department_handoff_defaults"
down_revision = "0046_add_user_department_handoff_package"
branch_labels = None
depends_on = None


DEPARTMENT_COLUMNS = [
    sa.Column("handoff_template_doc_url", sa.String(length=500), nullable=True),
    sa.Column("handoff_template_checklist_json", sa.Text(), nullable=True),
]


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("department") as batch_op:
            for column in DEPARTMENT_COLUMNS:
                batch_op.add_column(column)
    else:
        for column in DEPARTMENT_COLUMNS:
            op.add_column("department", column)


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("department") as batch_op:
            batch_op.drop_column("handoff_template_checklist_json")
            batch_op.drop_column("handoff_template_doc_url")
    else:
        op.drop_column("department", "handoff_template_checklist_json")
        op.drop_column("department", "handoff_template_doc_url")