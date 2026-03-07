"""merge 0025 and 0026 heads into a single head

Revision ID: 0027_merge_heads_0026
Revises: 0025_merge_heads, 0026_add_user_dark_mode
Create Date: 2026-03-07 01:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0027_merge_heads_0026"
down_revision = ("0025_merge_heads", "0026_add_user_dark_mode")
branch_labels = None
depends_on = None


def upgrade():
    # merge-only migration; no DB operations — consolidates multiple heads
    pass


def downgrade():
    pass
