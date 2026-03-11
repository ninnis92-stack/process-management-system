"""add attachment ocr_text field

Revision ID: 0042_add_attachment_ocr_text
Revises: 0041_drop_user_show_hints
Create Date: 2026-03-08 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0042_add_attachment_ocr_text"
down_revision = "0041_drop_user_show_hints"
branch_labels = None
depends_on = None


def upgrade():
    import sqlalchemy as sa
    from alembic import op
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c["name"] for c in insp.get_columns("attachment")]
    if "ocr_text" not in cols:
        op.add_column("attachment", sa.Column("ocr_text", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("attachment", "ocr_text")
