"""add branding fields to site_config

Revision ID: 0020_add_site_branding_fields
Revises: 0019_add_out_of_stock_notify_mode_and_message
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0020_add_site_branding_fields"
down_revision = "0019_add_out_of_stock_notify_mode_and_message"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "site_config", sa.Column("brand_name", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "site_config", sa.Column("logo_filename", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "site_config",
        sa.Column(
            "theme_preset",
            sa.String(length=40),
            nullable=False,
            server_default="default",
        ),
    )


def downgrade():
    op.drop_column("site_config", "theme_preset")
    op.drop_column("site_config", "logo_filename")
    op.drop_column("site_config", "brand_name")
