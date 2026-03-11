"""add guest form access policy fields

Revision ID: 0043_add_guest_form_access_policy
Revises: 0042_add_attachment_ocr_text
Create Date: 2026-03-08 23:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0043_add_guest_form_access_policy"
down_revision = "0042_add_attachment_ocr_text"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "guest_form" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("guest_form")}
    if "access_policy" not in cols:
        op.add_column(
            "guest_form",
            sa.Column(
                "access_policy",
                sa.String(length=40),
                nullable=True,
                server_default="public",
            ),
        )
        try:
            conn.execute(
                sa.text(
                    "UPDATE guest_form SET access_policy='sso_linked' WHERE require_sso = true"
                )
            )
        except Exception:
            conn.execute(
                sa.text(
                    "UPDATE guest_form SET access_policy='sso_linked' WHERE require_sso = 1"
                )
            )
        op.alter_column("guest_form", "access_policy", server_default=None)
    if "allowed_email_domains" not in cols:
        op.add_column(
            "guest_form", sa.Column("allowed_email_domains", sa.Text(), nullable=True)
        )
    if "credential_requirements_json" not in cols:
        op.add_column(
            "guest_form",
            sa.Column("credential_requirements_json", sa.Text(), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "guest_form" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("guest_form")}
    if "credential_requirements_json" in cols:
        op.drop_column("guest_form", "credential_requirements_json")
    if "allowed_email_domains" in cols:
        op.drop_column("guest_form", "allowed_email_domains")
    if "access_policy" in cols:
        op.drop_column("guest_form", "access_policy")
