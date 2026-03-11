
"""Generic Alembic script template placeholder.

This file exists as a minimal template for generated revisions.
"""

revision = 'f381e1200d60'
down_revision = '527ad440a4f1'
branch_labels = None
depends_on = None

def upgrade():
    from alembic import op
    import sqlalchemy as sa
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing = [c['name'] for c in insp.get_columns('request')]
    if 'original_sender' not in existing:
        op.add_column('request', sa.Column('original_sender', sa.String(length=255), nullable=True))


def downgrade():
    from alembic import op
    op.drop_column('request', 'original_sender')
