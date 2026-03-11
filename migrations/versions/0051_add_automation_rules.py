"""add automation rules table

Revision ID: 0051_add_automation_rules
Revises: 0050_add_email_original_sender_and_watchers
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0051_add_automation_rules"
down_revision = "0050_add_email_original_sender_and_watchers"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=True, index=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("triggers_json", sa.JSON(), nullable=True),
        sa.Column("conditions_json", sa.JSON(), nullable=True),
        sa.Column("actions_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index(op.f('ix_automation_rule_is_active'), 'automation_rule', ['is_active'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_automation_rule_is_active'), table_name='automation_rule')
    op.drop_table('automation_rule')
