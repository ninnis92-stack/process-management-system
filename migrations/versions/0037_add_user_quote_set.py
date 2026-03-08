"""add quote_set preference to user

Revision ID: 0037_add_user_quote_set
Revises: 0036_add_site_config_banner_quotes_fields
Create Date: 2026-03-08 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0037_add_user_quote_set"
down_revision = "0036_add_site_config_banner_quotes_fields"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "user" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("user")}
        if "quote_set" not in cols:
            op.add_column("user", sa.Column("quote_set", sa.String(length=80), nullable=True))


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "user" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("user")}
        if "quote_set" in cols:
            op.drop_column("user", "quote_set")