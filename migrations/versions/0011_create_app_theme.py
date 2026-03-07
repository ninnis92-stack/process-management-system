"""create app_theme table

Revision ID: 0011_create_app_theme
Revises: 0010_add_special_email_flags
Create Date: 2026-03-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011_create_app_theme"
down_revision = "0010_add_special_email_flags"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_theme",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("css", sa.Text(), nullable=True),
        sa.Column("logo_filename", sa.String(length=255), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("app_theme")
