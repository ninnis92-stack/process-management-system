"""add feature flag overrides to special_email_config

Revision ID: 0010_add_special_email_flags
Revises: 0009_add_request_is_debug
Create Date: 2026-03-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0010_add_special_email_flags'
down_revision = '0009_add_request_is_debug'
branch_labels = None
depends_on = None


def upgrade():
    # Add runtime feature flags to the singleton special_email_config table
    op.add_column('special_email_config', sa.Column('email_override', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('special_email_config', sa.Column('ticketing_override', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('special_email_config', sa.Column('inventory_override', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade():
    op.drop_column('special_email_config', 'inventory_override')
    op.drop_column('special_email_config', 'ticketing_override')
    op.drop_column('special_email_config', 'email_override')
