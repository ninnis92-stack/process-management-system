"""ensure original_sender exists on request table

Revision ID: 0052_add_original_sender_if_missing
Revises: f381e1200d60
Create Date: 2026-03-11 04:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0052_add_original_sender_if_missing'
down_revision = 'f381e1200d60'
branch_labels = None
depends_on = None


def upgrade():
    # Postgres supports IF NOT EXISTS syntax; for other databases use inspector.
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == 'postgresql':
        op.execute("ALTER TABLE request ADD COLUMN IF NOT EXISTS original_sender VARCHAR(255)")
    else:
        insp = sa.inspect(conn)
        cols = [c['name'] for c in insp.get_columns('request')]
        if 'original_sender' not in cols:
            op.add_column('request', sa.Column('original_sender', sa.String(length=255), nullable=True))


def downgrade():
    # no-op: we don't drop the column on downgrade to avoid loss
    pass
