"""add rolling_quotes_enabled to feature_flags

Revision ID: 0029_add_feature_flags_rolling_quotes
Revises: 0028_add_feature_flags_enable_external_forms
Create Date: 2026-03-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0029_add_feature_flags_rolling_quotes"
down_revision = "0028_add_feature_flags_enable_external_forms"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent DDL: add column if it doesn't exist
    op.execute(
        "ALTER TABLE feature_flags ADD COLUMN IF NOT EXISTS rolling_quotes_enabled boolean NOT NULL DEFAULT true;"
    )


def downgrade():
    op.execute("ALTER TABLE feature_flags DROP COLUMN IF EXISTS rolling_quotes_enabled;")
