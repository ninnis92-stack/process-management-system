"""add email_routing table

Revision ID: 0008_add_email_routing
Revises: 0006_add_special_email_config
Create Date: 2026-03-05 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_add_email_routing"
down_revision = "0006_add_special_email_config"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_routing",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=False, index=True),
        sa.Column("department_code", sa.String(length=2), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("email_routing")
