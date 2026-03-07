"""add request_form_department to special_email_config

Revision ID: 0016_add_request_form_department
Revises: 0015_add_reject_request_config
Create Date: 2026-03-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016_add_request_form_department"
down_revision = "0015_add_reject_request_config"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "special_email_config",
        sa.Column(
            "request_form_department",
            sa.String(length=2),
            nullable=False,
            server_default="A",
        ),
    )


def downgrade():
    op.drop_column("special_email_config", "request_form_department")
