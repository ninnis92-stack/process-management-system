"""add integration_config table

Revision ID: 0007_add_integration_config
Revises: 0006_add_statusoption_and_depteditor
Create Date: 2026-03-05 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0007_add_integration_config'
down_revision = '0006_add_statusoption_and_depteditor'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'integration_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('department', sa.String(2), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('config', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint('uq_dept_kind', 'integration_config', ['department', 'kind'])


def downgrade():
    op.drop_constraint('uq_dept_kind', 'integration_config', type_='unique')
    op.drop_table('integration_config')
