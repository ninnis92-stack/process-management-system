"""add quote permissions config to site_config

Revision ID: 0038_add_site_config_quote_permissions
Revises: 0037_add_user_quote_set
Create Date: 2026-03-08 01:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0038_add_site_config_quote_permissions"
down_revision = "0037_add_user_quote_set"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "site_config" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("site_config")}
        if "quote_permissions" not in cols:
            op.add_column(
                "site_config", sa.Column("quote_permissions", sa.Text(), nullable=True)
            )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "site_config" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("site_config")}
        if "quote_permissions" in cols:
            op.drop_column("site_config", "quote_permissions")
