"""add request_form_inventory_out_of_stock_notify_enabled to special_email_config

Revision ID: 0018_add_out_of_stock_notify_toggle
Revises: 0017_add_request_form_field_validation_toggle
Create Date: 2026-03-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0018_add_out_of_stock_notify_toggle"
down_revision = "0017_add_request_form_field_validation_toggle"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "special_email_config",
        sa.Column(
            "request_form_inventory_out_of_stock_notify_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column(
        "special_email_config", "request_form_inventory_out_of_stock_notify_enabled"
    )
