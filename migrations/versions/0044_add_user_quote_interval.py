"""add user.quote_interval

Revision ID: 0044_add_user_quote_interval
Revises: 0043_add_guest_form_access_policy
Create Date: 2026-03-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '0044_add_user_quote_interval'
down_revision = '0043_add_guest_form_access_policy'
branch_labels = None
depends_on = None


def upgrade():
    # add a nullable integer column for the quote rotation interval
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    cols = [c['name'] for c in insp.get_columns('user')]
    if 'quote_interval' not in cols:
        op.add_column('user', sa.Column('quote_interval', sa.Integer(), nullable=True))
        # backfill existing rows with a sensible default (15 seconds)
        op.execute(
            "UPDATE \"user\" SET quote_interval = 15 WHERE quote_interval IS NULL"
        )


def downgrade():
    bind = op.get_bind()
    insp = Inspector.from_engine(bind)
    cols = [c['name'] for c in insp.get_columns('user')]
    if 'quote_interval' in cols:
        op.drop_column('user', 'quote_interval')
