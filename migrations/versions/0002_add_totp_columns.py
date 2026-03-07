"""add totp columns to user table

Revision ID: 0002_add_totp_columns
Revises: 0001_add_is_admin
Create Date: 2026-03-04 00:01:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_add_totp_columns"
down_revision = "0001_add_is_admin"
branch_labels = None
depends_on = None


def upgrade():
    try:
        op.add_column("user", sa.Column("totp_secret", sa.String(64), nullable=True))
        op.add_column(
            "user",
            sa.Column(
                "totp_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    except Exception:
        conn = op.get_bind()
        try:
            conn.execute(sa.text("ALTER TABLE user ADD COLUMN totp_secret VARCHAR(64)"))
        except Exception:
            pass
        try:
            conn.execute(
                sa.text("ALTER TABLE user ADD COLUMN totp_enabled INTEGER DEFAULT 0")
            )
        except Exception:
            pass


def downgrade():
    try:
        op.drop_column("user", "totp_enabled")
        op.drop_column("user", "totp_secret")
    except Exception:
        pass
