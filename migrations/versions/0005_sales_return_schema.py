"""Source-scoped sales, exact amounts and quantity-bounded linked returns."""

from alembic import op
import sqlalchemy as sa


revision = "0005_sales_return_schema"
down_revision = "0004_customer_session_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_orders",
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
    op.create_table(
        "sales_lines",
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
    op.create_table(
        "sales_returns",
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
    )
    op.create_index("sales_return_sale_line_idx", "sales_returns", ["sale_line_id"])
    op.execute("""
        CREATE FUNCTION sales_return_quantity_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            line_id bigint;
            sold_quantity numeric;
            returned_quantity numeric;
        BEGIN
            IF TG_OP = 'UPDATE' AND
               (NEW.sale_line_id, NEW.source_system) IS DISTINCT FROM
               (OLD.sale_line_id, OLD.source_system) THEN
                RAISE EXCEPTION 'return sale linkage is immutable'
                    USING ERRCODE = '23514', CONSTRAINT = 'sales_return_link_immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                line_id := OLD.sale_line_id;
            ELSE
                line_id := NEW.sale_line_id;
            END IF;

            -- Write the parent row, rather than just taking a read lock. This
            -- serializes writers and forces a retry on stale RR/serializable
            -- snapshots instead of allowing concurrent excess returns.
            -- A non-key column keeps this compatible with FK key-share locks.
            UPDATE sales_lines SET unit_price = unit_price WHERE id = line_id
                RETURNING quantity INTO sold_quantity;
            SELECT COALESCE(sum(quantity), 0) INTO returned_quantity
                FROM sales_returns WHERE sale_line_id = line_id;
            IF returned_quantity > sold_quantity THEN
                RAISE EXCEPTION 'returned quantity exceeds sold quantity'
                    USING ERRCODE = '23514', CONSTRAINT = 'sales_return_within_sale';
            END IF;
            RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER sales_return_quantity_guard
        AFTER INSERT OR UPDATE OR DELETE ON sales_returns
        FOR EACH ROW EXECUTE FUNCTION sales_return_quantity_guard()
    """)
    op.execute("""
        CREATE FUNCTION sales_line_quantity_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE returned_quantity numeric;
        BEGIN
            SELECT COALESCE(sum(quantity), 0) INTO returned_quantity
                FROM sales_returns WHERE sale_line_id = OLD.id;
            IF NEW.quantity < returned_quantity THEN
                RAISE EXCEPTION 'sold quantity is below already returned quantity'
                    USING ERRCODE = '23514', CONSTRAINT = 'sales_return_within_sale';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER sales_line_quantity_guard
        BEFORE UPDATE OF quantity ON sales_lines
        FOR EACH ROW EXECUTE FUNCTION sales_line_quantity_guard()
    """)


def downgrade() -> None:
    op.drop_table("sales_returns")
    op.execute("DROP TRIGGER sales_line_quantity_guard ON sales_lines")
    op.execute("DROP FUNCTION sales_return_quantity_guard()")
    op.execute("DROP FUNCTION sales_line_quantity_guard()")
    op.drop_table("sales_lines")
    op.drop_table("sales_orders")
