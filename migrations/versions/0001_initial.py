"""initial empty revision

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identi***REMOVED***ers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Empty initial migration. Use `flask db stamp head` locally if your DB
    # already contains the current schema to avoid applying DDL twice.
    pass


def downgrade():
    pass
