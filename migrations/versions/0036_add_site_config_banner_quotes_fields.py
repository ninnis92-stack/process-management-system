"""add banner and rolling quote columns to site_config

Revision ID: 0036_add_site_config_banner_quotes_fields
Revises: 0035_add_sso_department_override
Create Date: 2026-03-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0036_add_site_config_banner_quotes_fields"
down_revision = "0035_add_sso_department_override"
branch_labels = None
depends_on = None


def upgrade():
    # these columns were added to the model after the previous migrations but
    # some databases (in particular existing production) may not yet have
    # them.  add them if they don't exist so a simple `flask db upgrade`
    # will bring the schema up to date.
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "site_config" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("site_config")}
        if "navbar_banner" not in cols:
            op.add_column(
                "site_config",
                sa.Column("navbar_banner", sa.String(length=500), nullable=True),
            )
        if "show_banner" not in cols:
            op.add_column(
                "site_config",
                sa.Column(
                    "show_banner",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                ),
            )
        if "rolling_quotes" not in cols:
            op.add_column(
                "site_config", sa.Column("rolling_quotes", sa.Text(), nullable=True)
            )
        if "rolling_quote_sets" not in cols:
            op.add_column(
                "site_config", sa.Column("rolling_quote_sets", sa.Text(), nullable=True)
            )
        if "active_quote_set" not in cols:
            op.add_column(
                "site_config",
                sa.Column(
                    "active_quote_set",
                    sa.String(length=80),
                    nullable=True,
                    server_default="default",
                ),
            )
        if "updated_at" not in cols:
            # the updated_at column is populated by the model; using server_default
            # avoids problems with existing rows.
            op.add_column(
                "site_config",
                sa.Column(
                    "updated_at",
                    sa.DateTime(),
                    nullable=True,
                    server_default=sa.func.now(),
                ),
            )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "site_config" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("site_config")}
        if "updated_at" in cols:
            op.drop_column("site_config", "updated_at")
        if "active_quote_set" in cols:
            op.drop_column("site_config", "active_quote_set")
        if "rolling_quote_sets" in cols:
            op.drop_column("site_config", "rolling_quote_sets")
        if "rolling_quotes" in cols:
            op.drop_column("site_config", "rolling_quotes")
        if "show_banner" in cols:
            op.drop_column("site_config", "show_banner")
        if "navbar_banner" in cols:
            op.drop_column("site_config", "navbar_banner")
