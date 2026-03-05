"""make auditlog.request_id nullable

Revision ID: 0003_auditlog_request_nullable
Revises: 0002_add_totp_columns
Create Date: 2026-03-04 18:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0003_auditlog_request_nullable'
down_revision = '0002_add_totp_columns'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == 'sqlite':
        with op.batch_alter_table('audit_log') as batch_op:
            batch_op.alter_column('request_id', existing_type=sa.Integer(), nullable=True)
    else:
        op.alter_column('audit_log', 'request_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name == 'sqlite':
        with op.batch_alter_table('audit_log') as batch_op:
            batch_op.alter_column('request_id', existing_type=sa.Integer(), nullable=False)
    else:
        op.alter_column('audit_log', 'request_id', existing_type=sa.Integer(), nullable=False)
