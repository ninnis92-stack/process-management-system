"""add form template and related tables

Revision ID: 0012_add_form_templates
Revises: 0011_create_app_theme
Create Date: 2026-03-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_add_form_templates"
down_revision = "0011_create_app_theme"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_template",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "form_field",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("form_template.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("field_type", sa.String(length=40), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hint", sa.String(length=300), nullable=True),
        sa.Column("verification", sa.JSON(), nullable=True),
    )

    op.create_table(
        "form_field_option",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "field_id", sa.Integer(), sa.ForeignKey("form_field.id"), nullable=False
        ),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "department_form_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("form_template.id"),
            nullable=False,
        ),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("department_name", sa.String(length=150), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "verification_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "field_id", sa.Integer(), sa.ForeignKey("form_field.id"), nullable=False
        ),
        sa.Column("rule_type", sa.String(length=80), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("verification_rule")
    op.drop_table("department_form_assignment")
    op.drop_table("form_field_option")
    op.drop_table("form_field")
    op.drop_table("form_template")
