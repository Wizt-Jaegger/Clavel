"""Catalog with typed hardware attributes and explicit unknown values."""

from alembic import op
import sqlalchemy as sa


revision = "0002_catalog_schema"
down_revision = "0001_migration_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.CheckConstraint("code <> '' AND code = btrim(code)", name="category_code_valid"),
        sa.CheckConstraint("btrim(name) <> ''", name="category_name_valid"),
    )
    op.create_table(
        "skus",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("sku", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("category_id", sa.BigInteger, sa.ForeignKey("categories.id")),
        sa.CheckConstraint("sku <> '' AND sku = btrim(sku)", name="sku_code_valid"),
        sa.CheckConstraint("btrim(name) <> ''", name="sku_name_valid"),
    )
    op.create_table(
        "hardware_attributes",
        sa.Column("sku_id", sa.BigInteger, sa.ForeignKey("skus.id"), primary_key=True),
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("value_kind", sa.Text, nullable=False),
        sa.Column("text_value", sa.Text),
        sa.Column("number_value", sa.Numeric),
        sa.Column("boolean_value", sa.Boolean),
        sa.Column("unit", sa.Text),
        sa.CheckConstraint("name <> '' AND name = btrim(name)", name="attribute_name_valid"),
        sa.CheckConstraint(
            "(value_kind = 'unknown' AND text_value IS NULL AND number_value IS NULL "
            "AND boolean_value IS NULL) OR "
            "(value_kind = 'text' AND text_value IS NOT NULL AND btrim(text_value) <> '' "
            "AND number_value IS NULL AND boolean_value IS NULL) OR "
            "(value_kind = 'number' AND number_value IS NOT NULL "
            "AND text_value IS NULL AND boolean_value IS NULL) OR "
            "(value_kind = 'boolean' AND boolean_value IS NOT NULL "
            "AND text_value IS NULL AND number_value IS NULL)",
            name="attribute_typed_value",
        ),
        sa.CheckConstraint(
            "number_value IS NULL OR number_value NOT IN "
            "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="attribute_number_finite",
        ),
        sa.CheckConstraint(
            "unit IS NULL OR (value_kind IN ('number', 'unknown') "
            "AND unit <> '' AND unit = btrim(unit))",
            name="attribute_unit_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("hardware_attributes")
    op.drop_table("skus")
    op.drop_table("categories")
