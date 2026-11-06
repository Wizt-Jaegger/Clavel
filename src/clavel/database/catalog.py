"""Catalog metadata. Missing categories/attributes and explicit unknowns stay unknown.

SKU/category codes are case-sensitive and have no surrounding spaces.
Attributes use one typed value, or no value when unknown. Units are descriptive;
this schema makes no compatibility, stock, or eligibility claims.
"""

import sqlalchemy as sa


metadata = sa.MetaData()

categories = sa.Table(
    "categories", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("code", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.CheckConstraint("code <> '' AND code = btrim(code)", name="category_code_valid"),
    sa.CheckConstraint("btrim(name) <> ''", name="category_name_valid"),
)

skus = sa.Table(
    "skus", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("sku", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("category_id", sa.BigInteger, sa.ForeignKey("categories.id")),
    sa.CheckConstraint("sku <> '' AND sku = btrim(sku)", name="sku_code_valid"),
    sa.CheckConstraint("btrim(name) <> ''", name="sku_name_valid"),
)

hardware_attributes = sa.Table(
    "hardware_attributes", metadata,
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
