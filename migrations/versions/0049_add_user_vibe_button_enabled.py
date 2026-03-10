"""add user.vibe_button_enabled

Revision ID: 0049_add_user_vibe_button_enabled
Revises: 0048_add_guest_page_feature_flags
Create Date: 2026-03-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0049_add_user_vibe_button_enabled'
down_revision = '0048_add_guest_page_feature_flags'
branch_labels = None
depends_on = None


def _has_column(conn, table_name, column_name):
    insp = sa.inspect(conn)
    return column_name in [c['name'] for c in insp.get_columns(table_name)]


def upgrade():
    conn = op.get_bind()
    # safe idempotent addition
    if not _has_column(conn, 'user', 'vibe_button_enabled'):
        op.add_column('user', sa.Column('vibe_button_enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')))
        # remove server default to match others
        op.alter_column('user', 'vibe_button_enabled', server_default=None)


def downgrade():
    conn = op.get_bind()
    if _has_column(conn, 'user', 'vibe_button_enabled'):
        op.drop_column('user', 'vibe_button_enabled')
