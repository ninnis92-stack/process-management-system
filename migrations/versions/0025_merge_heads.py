"""merge multiple heads into single head

Revision ID: 0025_merge_heads
Revises: 0001_initial, 0008_add_statusoption_columns, 0010_add_field_verification, 0024_add_status_bucket_workflow
Create Date: 2026-03-07 00:30:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0025_merge_heads'
down_revision = (
    '0001_initial',
    '0008_add_statusoption_columns',
    '0010_add_field_verification',
    '0024_add_status_bucket_workflow',
)
branch_labels = None
depends_on = None


def upgrade():
    # merge-only migration; no DB operations — consolidates multiple heads
    pass


def downgrade():
    pass
