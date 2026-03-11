"""add user.show_hints

Revision ID: 0040_add_user_show_hints
Revises: 0039_add_user_quotes_enabled
Create Date: 2026-03-08 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0040_add_user_show_hints"
down_revision = "0039_add_user_quotes_enabled"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("user")]
    if "show_hints" not in cols:
        op.add_column(
            "user",
            sa.Column(
                "show_hints",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("TRUE"),
            ),
        )
        # remove server default after backfilling
        op.alter_column("user", "show_hints", server_default=None)


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("user")]
    if "show_hints" in cols:
        op.drop_column("user", "show_hints")
