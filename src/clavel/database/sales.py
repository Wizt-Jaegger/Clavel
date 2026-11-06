"""Canonical sales and linked returns; source identifiers must be opaque.

Source systems namespace order and return IDs. Line IDs are scoped to their
source order/return. Currency is inherited from the sale order, never converted.
Quantities support six fractional places; unit amounts support four. Unbounded
NUMERIC plus checks rejects excess precision instead of silently rounding it.
Missing unit cost/customer links remain NULL, distinct from known zero cost.

The migration additionally serializes return changes against their sale line
and prevents cumulative returns exceeding the sold quantity. This metadata
alone does not install those triggers; apply the Alembic migration.
"""

import sqlalchemy as sa

from clavel.database.customers import metadata


sales_orders = sa.Table(
    "sales_orders", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("source_system", sa.Text, nullable=False),
    sa.Column("source_order_id", sa.Text, nullable=False),
    sa.Column("customer_id", sa.BigInteger, sa.ForeignKey("customers.id")),
    sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("currency", sa.Text, nullable=False),
    sa.UniqueConstraint("source_system", "source_order_id", name="sales_order_source_unique"),
    sa.UniqueConstraint("id", "source_system", name="sales_order_id_source_unique"),
    sa.CheckConstraint(
        "source_system <> '' AND source_system = btrim(source_system)",
        name="sales_order_source_valid",
    ),
    sa.CheckConstraint(
        "source_order_id <> '' AND source_order_id = btrim(source_order_id)",
        name="sales_order_reference_valid",
    ),
    sa.CheckConstraint("isfinite(sold_at)", name="sales_order_time_finite"),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="sales_order_currency_valid"),
)

sales_lines = sa.Table(
    "sales_lines", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("order_id", sa.BigInteger, nullable=False),
    sa.Column("source_system", sa.Text, nullable=False),
    sa.Column("source_line_id", sa.Text, nullable=False),
    sa.Column("sku_id", sa.BigInteger, sa.ForeignKey("skus.id"), nullable=False),
    sa.Column("quantity", sa.Numeric, nullable=False),
    sa.Column("unit_price", sa.Numeric, nullable=False),
    sa.Column("unit_cost", sa.Numeric),
    sa.ForeignKeyConstraint(
        ["order_id", "source_system"], ["sales_orders.id", "sales_orders.source_system"],
        name="sales_line_order_fk",
    ),
    sa.UniqueConstraint("order_id", "source_line_id", name="sales_line_source_unique"),
    sa.UniqueConstraint("id", "source_system", name="sales_line_id_source_unique"),
    sa.CheckConstraint(
        "source_line_id <> '' AND source_line_id = btrim(source_line_id)",
        name="sales_line_reference_valid",
    ),
    sa.CheckConstraint(
        "quantity > 0 AND quantity < 1000000000000 AND quantity = trunc(quantity, 6)",
        name="sales_line_quantity_valid",
    ),
    sa.CheckConstraint(
        "unit_price >= 0 AND unit_price < 1000000000000000 "
        "AND unit_price = trunc(unit_price, 4)", name="sales_line_price_valid",
    ),
    sa.CheckConstraint(
        "unit_cost IS NULL OR (unit_cost >= 0 AND unit_cost < 1000000000000000 "
        "AND unit_cost = trunc(unit_cost, 4))", name="sales_line_cost_valid",
    ),
)

sales_returns = sa.Table(
    "sales_returns", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("source_system", sa.Text, nullable=False),
    sa.Column("source_return_id", sa.Text, nullable=False),
    sa.Column("source_line_id", sa.Text, nullable=False),
    sa.Column("sale_line_id", sa.BigInteger, nullable=False),
    sa.Column("quantity", sa.Numeric, nullable=False),
    sa.Column("returned_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["sale_line_id", "source_system"], ["sales_lines.id", "sales_lines.source_system"],
        name="sales_return_line_fk",
    ),
    sa.UniqueConstraint(
        "source_system", "source_return_id", "source_line_id",
        name="sales_return_source_unique",
    ),
    sa.CheckConstraint(
        "source_return_id <> '' AND source_return_id = btrim(source_return_id)",
        name="sales_return_reference_valid",
    ),
    sa.CheckConstraint(
        "source_line_id <> '' AND source_line_id = btrim(source_line_id)",
        name="sales_return_line_reference_valid",
    ),
    sa.CheckConstraint(
        "quantity > 0 AND quantity < 1000000000000 AND quantity = trunc(quantity, 6)",
        name="sales_return_quantity_valid",
    ),
    sa.CheckConstraint("isfinite(returned_at)", name="sales_return_time_finite"),
    sa.Index("sales_return_sale_line_idx", "sale_line_id"),
)
