"""add process_group and process_step tables

Revision ID: 0006_add_process_groups
Revises: 0005_add_vibe_index
Create Date: 2026-03-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0006_add_process_groups'
down_revision = '0005_add_vibe_index'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'process_group',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'process_step',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('process_group_id', sa.Integer(), nullable=False),
        sa.Column('step_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('department', sa.String(length=1), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['process_group_id'], ['process_group.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('process_step')
    op.drop_table('process_group')
