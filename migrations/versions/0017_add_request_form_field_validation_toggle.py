"""add request_form_field_validation_enabled to special_email_config

Revision ID: 0017_add_request_form_field_validation_toggle
Revises: 0016_add_request_form_department
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_add_request_form_field_validation_toggle"
down_revision = "0016_add_request_form_department"
branch_labels = None
depends_on = None


def upgrade():
    # Skip adding column if it already exists
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col['name'] for col in insp.get_columns('special_email_config')]
    if "request_form_field_validation_enabled" not in columns:
        op.add_column(
            "special_email_config",
            sa.Column(
                "request_form_field_validation_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade():
    op.drop_column("special_email_config", "request_form_field_validation_enabled")
