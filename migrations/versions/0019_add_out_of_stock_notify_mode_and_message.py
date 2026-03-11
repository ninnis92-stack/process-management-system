"""add out-of-stock notify mode and message to special_email_config

Revision ID: 0019_add_out_of_stock_notify_mode_and_message
Revises: 0018_add_out_of_stock_notify_toggle
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0019_add_out_of_stock_notify_mode_and_message"
down_revision = "0018_add_out_of_stock_notify_toggle"
branch_labels = None
depends_on = None


def upgrade():
    # Skip adding columns if they already exist
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col['name'] for col in insp.get_columns('special_email_config')]
    if "request_form_inventory_out_of_stock_notify_mode" not in columns:
        op.add_column(
            "special_email_config",
            sa.Column(
                "request_form_inventory_out_of_stock_notify_mode",
                sa.String(length=20),
                nullable=False,
                server_default="email",
            ),
        )
    if "request_form_inventory_out_of_stock_message" not in columns:
        op.add_column(
            "special_email_config",
            sa.Column(
                "request_form_inventory_out_of_stock_message", sa.Text(), nullable=True
            ),
        )


def downgrade():
    op.drop_column(
        "special_email_config", "request_form_inventory_out_of_stock_message"
    )
    op.drop_column(
        "special_email_config", "request_form_inventory_out_of_stock_notify_mode"
    )
