"""add is_admin column to user table

Revision ID: 0001_add_is_admin
Revises: None
Create Date: 2026-03-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_add_is_admin'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add `is_admin` column. Use INTEGER default for SQLite compatibility.
    try:
        op.add_column('user', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    except Exception:
        # Best-effort: direct EXECUTE for sqlite if add_column fails in older Alembic
        conn = op.get_bind()
        conn.execute(sa.text("ALTER TABLE user ADD COLUMN is_admin INTEGER DEFAULT 0"))


def downgrade():
    try:
        op.drop_column('user', 'is_admin')
    except Exception:
        # SQLite doesn't support DROP COLUMN before 3.35; skip if not supported.
        pass
