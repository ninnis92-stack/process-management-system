"""add user.quotes_enabled

Revision ID: 0039_add_user_quotes_enabled
Revises: 0038_add_site_config_quote_permissions
Create Date: 2026-03-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0039_add_user_quotes_enabled'
down_revision = '0038_add_site_config_quote_permissions'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('user')]
    if 'quotes_enabled' not in cols:
        op.add_column(
            'user',
            sa.Column('quotes_enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        )
        # remove server default after backfilling
        op.alter_column('user', 'quotes_enabled', server_default=None)


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('user')]
    if 'quotes_enabled' in cols:
        op.drop_column('user', 'quotes_enabled')
