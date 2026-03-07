"""add enable_external_forms to feature_flags

Revision ID: 0028_add_feature_flags_enable_external_forms
Revises: 0027_merge_heads_0026
Create Date: 2026-03-07 01:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0028_add_feature_flags_enable_external_forms"
down_revision = "0027_merge_heads_0026"
branch_labels = None
depends_on = None


def upgrade():
    # Use idempotent Postgres DDL to add the missing column if it's absent.
    op.execute(
        "ALTER TABLE feature_flags ADD COLUMN IF NOT EXISTS enable_external_forms boolean NOT NULL DEFAULT false;"
    )
    # Note: this uses raw DDL for portability and to avoid failures when
    # Alembic's model metadata may be out-of-sync with the DB. Applying
    # the raw ALTER is safe (it is `IF NOT EXISTS`) and idempotent.
    # Ensure the server_default is present for SQLAlchemy metadata alignment.
    try:
        op.alter_column(
            "feature_flags",
            "enable_external_forms",
            server_default=sa.text("false"),
            existing_type=sa.Boolean(),
        )
    except Exception:
        # alter_column may fail on some DB versions; it's safe to ignore here
        # because the raw ALTER above created the column with a default.
        pass


def downgrade():
    # Remove the column if it exists (safe for rollbacks on staging).
    op.execute("ALTER TABLE feature_flags DROP COLUMN IF EXISTS enable_external_forms;")
