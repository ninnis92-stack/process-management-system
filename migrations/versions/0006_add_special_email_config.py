"""add special email config

Revision ID: 0006_add_special_email_config
Revises: 0005_add_vibe_index
Create Date: 2026-03-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0006_add_special_email_config'
down_revision = '0005_add_vibe_index'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'special_email_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('help_email', sa.String(length=255), nullable=True),
        sa.Column('request_form_email', sa.String(length=255), nullable=True),
        sa.Column('request_form_first_message', sa.Text(), nullable=True),
        sa.Column('help_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('request_form_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
    )


def downgrade():
    op.drop_table('special_email_config')
