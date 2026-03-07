"""add guest_form table

Revision ID: 0008_add_guest_form
Revises: 0007_autogen_add_special_email_config
Create Date: 2026-03-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0008_add_guest_form'
down_revision = '0007_autogen_add_special_email_config'
branch_labels = None
defaults = None


def upgrade():
    op.create_table(
        'guest_form',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('slug', sa.String(length=128), nullable=False, unique=True),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('require_sso', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('owner_department', sa.String(length=2), nullable=False, server_default='B'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('guest_form')
