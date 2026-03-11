"""add layout columns to guest_form and form_template

Revision ID: 0045_add_template_layout_columns
Revises: 0044_add_user_quote_interval
Create Date: 2026-03-08 23:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0045_add_template_layout_columns"
down_revision = "0044_add_user_quote_interval"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # guest_form table layout
    if "guest_form" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("guest_form")}
        if "layout" not in cols:
            op.add_column(
                "guest_form",
                sa.Column(
                    "layout",
                    sa.String(length=20),
                    nullable=False,
                    server_default="standard",
                ),
            )
            op.alter_column("guest_form", "layout", server_default=None)

    # form_template table layout
    if "form_template" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("form_template")}
        if "layout" not in cols:
            op.add_column(
                "form_template",
                sa.Column(
                    "layout",
                    sa.String(length=20),
                    nullable=False,
                    server_default="standard",
                ),
            )
            op.alter_column("form_template", "layout", server_default=None)


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "guest_form" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("guest_form")}
        if "layout" in cols:
            op.drop_column("guest_form", "layout")
    if "form_template" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("form_template")}
        if "layout" in cols:
            op.drop_column("form_template", "layout")
