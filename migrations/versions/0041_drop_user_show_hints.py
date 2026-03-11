"""drop user.show_hints (undo earlier toggle work)

Revision ID: 0041_drop_user_show_hints
Revises: 0040_add_user_show_hints
Create Date: 2026-03-08 12:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0041_drop_user_show_hints"
down_revision = "0040_add_user_show_hints"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("user")]
    if "show_hints" in cols:
        op.drop_column("user", "show_hints")


def downgrade():
    # put the column back in case someone rolls back the migration chain
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("user")]
    if "show_hints" not in cols:
        op.add_column(
            "user",
            sa.Column(
                "show_hints", sa.Boolean(), nullable=False, server_default=sa.text("1")
            ),
        )
        op.alter_column("user", "show_hints", server_default=None)
