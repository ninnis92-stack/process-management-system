"""autogenerate add special_email_config

Revision ID: 0007_autogen_add_special_email_config
Revises: 0006_add_special_email_config
Create Date: 2026-03-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0007_autogen_add_special_email_config'
down_revision = '0006_add_special_email_config'
branch_labels = None
depends_on = None


def upgrade():
    # NOTE: This autogenerate-style revision mirrors the handcrafted 0006
    # migration. Keep one of the two in your release pipeline to avoid
    # attempting to create the same table twice.
    op.create_table(
        'special_email_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('help_email', sa.String(length=255), nullable=True),
        sa.Column('request_form_email', sa.String(length=255), nullable=True),
        sa.Column('request_form_first_message', sa.Text(), nullable=True),
        sa.Column('help_user_id', sa.Integer(), nullable=True),
        sa.Column('request_form_user_id', sa.Integer(), nullable=True),
    )
    # Add foreign key constraints separately for clarity/compatibility
    try:
        op.create_foreign_key(
            'fk_special_email_config_help_user', 'special_email_config', 'user', ['help_user_id'], ['id']
        )
        op.create_foreign_key(
            'fk_special_email_config_request_form_user', 'special_email_config', 'user', ['request_form_user_id'], ['id']
        )
    except Exception:
        # Some DBs/environments may add FKs automatically or require different syntax.
        pass


def downgrade():
    try:
        op.drop_constraint('fk_special_email_config_help_user', 'special_email_config', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('fk_special_email_config_request_form_user', 'special_email_config', type_='foreignkey')
    except Exception:
        pass
    op.drop_table('special_email_config')
