"""add email original sender and watcher fields

Revision ID: 0050_add_email_original_sender_and_watchers
Revises: 0049_add_user_vibe_button_enabled
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0050_add_email_original_sender_and_watchers"
down_revision = "0049_add_user_vibe_button_enabled"
branch_labels = None
depends_on = None


def upgrade():
    # special_email_config additions
    op.add_column(
        "special_email_config",
        sa.Column(
            "request_form_add_original_sender",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )
    op.add_column(
        "special_email_config",
        sa.Column(
            "request_form_default_watchers",
            sa.JSON(),
            nullable=True,
        ),
    )

    # request table additions
    op.add_column(
        "request",
        sa.Column(
            "original_sender",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "request",
        sa.Column(
            "watcher_emails",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade():
    # drop columns in reverse order
    op.drop_column("request", "watcher_emails")
    op.drop_column("request", "original_sender")
    op.drop_column("special_email_config", "request_form_default_watchers")
    op.drop_column("special_email_config", "request_form_add_original_sender")
