"""Disposable PostgreSQL, synthetic sales only; no live provider evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import psycopg
from psycopg import sql
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from clavel.database.sales import metadata, sales_lines, sales_orders, sales_returns
from tests.integration.test_migrations import HEAD, revisions, run_alembic, tables


WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
PREVIOUS = "0004_customer_session_schema"


def insert(connection, table, **record):
    return connection.execute(sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) RETURNING id",
    ).format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, record)),
        sql.SQL(", ").join(sql.Placeholder() for _ in record),
    ), tuple(record.values())).fetchone()[0]


def order(connection, **overrides):
    return insert(connection, "sales_orders", **{
        "source_system": "synthetic-pos", "source_order_id": "synthetic-order-01",
        "sold_at": WHEN, "currency": "MXN", **overrides,
    })


def line(connection, order_id, sku_id, **overrides):
    return insert(connection, "sales_lines", **{
        "order_id": order_id, "source_system": "synthetic-pos",
        "source_line_id": "synthetic-sale-line-01", "sku_id": sku_id,
        "quantity": Decimal("10"), "unit_price": Decimal("12.3456"), **overrides,
    })


def returned(connection, line_id, **overrides):
    return insert(connection, "sales_returns", **{
        "source_system": "synthetic-pos", "source_return_id": "synthetic-return-01",
        "source_line_id": "synthetic-return-line-01", "sale_line_id": line_id,
        "quantity": Decimal("2"), "returned_at": WHEN, **overrides,
    })


@pytest.fixture
def sales(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    with psycopg.connect(migration_database_url) as connection:
        sku_id = insert(connection, "skus", sku="SYNTHETIC-P0013", name="Synthetic item")
        order_id = order(connection)
        line_id = line(connection, order_id, sku_id)
    return migration_database_url, order_id, sku_id, line_id


def test_duplicate_order_and_line_rejected_but_source_and_order_scopes_are_distinct(sales):
    url, order_id, sku_id, _ = sales
    for duplicate in (lambda c: order(c), lambda c: line(c, order_id, sku_id)):
        with pytest.raises(psycopg.errors.UniqueViolation):
            with psycopg.connect(url) as connection:
                duplicate(connection)
    with psycopg.connect(url) as connection:
        second_order = order(connection, source_order_id="synthetic-order-02")
        line(connection, second_order, sku_id)  # Same line ID in a different order.
        other_source = order(connection, source_system="synthetic-other-pos")
        line(connection, other_source, sku_id, source_system="synthetic-other-pos")


def test_return_id_deduplication_is_source_scoped_and_cannot_target_another_sale(sales):
    url, order_id, sku_id, line_id = sales
    with psycopg.connect(url) as connection:
        returned(connection, line_id)
        other_line = line(connection, order_id, sku_id, source_line_id="synthetic-sale-02")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(url) as connection:
            returned(connection, other_line)
    with psycopg.connect(url) as connection:
        other_order = order(connection, source_system="synthetic-other-pos")
        other_line = line(connection, other_order, sku_id, source_system="synthetic-other-pos")
        returned(connection, other_line, source_system="synthetic-other-pos")


@pytest.mark.parametrize("entity,overrides", [
    ("order", {"customer_id": -1}),
    ("line", {"order_id": -1}),
    ("line", {"source_system": "synthetic-other-pos"}),
    ("line", {"sku_id": -1}),
    ("return", {"sale_line_id": -1}),
    ("return", {"source_system": "synthetic-other-pos"}),
])
def test_orphan_and_cross_source_links_rejected(sales, entity, overrides):
    url, order_id, sku_id, line_id = sales
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(url) as connection:
            if entity == "order":
                order(connection, source_order_id="synthetic-invalid", **overrides)
            elif entity == "line":
                values = {"order_id": order_id, "sku_id": sku_id,
                          "source_line_id": "synthetic-invalid", **overrides}
                line(connection, **values)
            else:
                values = {"sale_line_id": line_id, **overrides}
                returned(connection, values.pop("sale_line_id"), **values)


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity", "-Infinity",
                                       "0.0000001", "1000000000000"])
@pytest.mark.parametrize("entity", ["line", "return"])
def test_invalid_quantities_rejected_without_rounding(sales, quantity, entity):
    url, order_id, sku_id, line_id = sales
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            if entity == "line":
                line(connection, order_id, sku_id, source_line_id="synthetic-invalid",
                     quantity=Decimal(quantity))
            else:
                returned(connection, line_id, quantity=Decimal(quantity))


@pytest.mark.parametrize("field", ["unit_price", "unit_cost"])
@pytest.mark.parametrize("amount", ["-0.0001", "0.00001", "1000000000000000",
                                    "NaN", "Infinity", "-Infinity"])
def test_money_rejects_out_of_range_nonfinite_and_excess_precision(sales, field, amount):
    url, order_id, sku_id, _ = sales
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            line(connection, order_id, sku_id, source_line_id="synthetic-invalid",
                 **{field: Decimal(amount)})


def test_exact_money_fractional_quantity_nullable_cost_and_inherited_currency(sales):
    url, order_id, sku_id, line_id = sales
    with psycopg.connect(url) as connection:
        line(connection, order_id, sku_id, source_line_id="synthetic-zero-cost",
             unit_price=Decimal("0"), unit_cost=Decimal("0"), quantity=Decimal("0.000001"))
        line(connection, order_id, sku_id, source_line_id="synthetic-large-amount",
             unit_price=Decimal("999999999999999.9999"), unit_cost=Decimal("0.0001"))
        returned(connection, line_id, quantity=Decimal("0.123456"))
    # Reconnect to verify persisted decimal values, not Python-side coercion.
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT quantity, unit_price, unit_cost FROM sales_lines ORDER BY id",
        ).fetchall() == [
            (Decimal("10"), Decimal("12.3456"), None),
            (Decimal("0.000001"), Decimal("0"), Decimal("0")),
            (Decimal("10"), Decimal("999999999999999.9999"), Decimal("0.0001")),
        ]
        assert connection.execute(
            "SELECT r.quantity, o.currency, o.customer_id FROM sales_returns r "
            "JOIN sales_lines l ON l.id = r.sale_line_id "
            "JOIN sales_orders o ON o.id = l.order_id",
        ).fetchall() == [(Decimal("0.123456"), "MXN", None)]


@pytest.mark.parametrize("entity,overrides", [
    ("order", {"currency": "mxn"}), ("order", {"currency": "MX"}),
    ("order", {"currency": "MXN "}), ("order", {"source_system": ""}),
    ("order", {"source_order_id": " synthetic-padded "}),
    ("order", {"sold_at": "infinity"}),
    ("line", {"source_line_id": ""}),
    ("return", {"source_return_id": ""}),
    ("return", {"source_line_id": " synthetic-padded "}),
    ("return", {"returned_at": "-infinity"}),
])
def test_malformed_identifiers_currency_and_nonfinite_times_rejected(sales, entity, overrides):
    url, order_id, sku_id, line_id = sales
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            if entity == "order":
                order(connection, **{"source_order_id": "synthetic-invalid", **overrides})
            elif entity == "line":
                line(connection, order_id, sku_id, **overrides)
            else:
                returned(connection, line_id, **overrides)


def test_partial_returns_updates_deletes_and_sale_reductions_respect_total(sales):
    url, _, _, line_id = sales
    with psycopg.connect(url) as connection:
        first = returned(connection, line_id, quantity=Decimal("4"))
        second = returned(connection, line_id, source_return_id="synthetic-return-02",
                          quantity=Decimal("6"))
    invalid_statements = [
        ("UPDATE sales_returns SET quantity = 7 WHERE id = %s", (second,)),
        ("UPDATE sales_lines SET quantity = 9 WHERE id = %s", (line_id,)),
    ]
    for statement, params in invalid_statements:
        with pytest.raises(psycopg.errors.CheckViolation):
            with psycopg.connect(url) as connection:
                connection.execute(statement, params)
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            returned(connection, line_id, source_return_id="synthetic-over-return",
                     quantity=Decimal("0.000001"))
    with psycopg.connect(url) as connection:
        connection.execute("UPDATE sales_returns SET quantity = 3 WHERE id = %s", (first,))
        connection.execute("DELETE FROM sales_returns WHERE id = %s", (second,))
        returned(connection, line_id, source_return_id="synthetic-replacement",
                 quantity=Decimal("7"))
        assert connection.execute(
            "SELECT sum(quantity) FROM sales_returns WHERE sale_line_id = %s", (line_id,),
        ).fetchone() == (Decimal("10"),)


def test_return_reparenting_and_deletion_of_linked_sales_rejected(sales):
    url, order_id, sku_id, line_id = sales
    with psycopg.connect(url) as connection:
        return_id = returned(connection, line_id)
        other = line(connection, order_id, sku_id, source_line_id="synthetic-other-sale")
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            connection.execute("UPDATE sales_returns SET sale_line_id = %s WHERE id = %s",
                               (other, return_id))
    for statement, params in [
        ("DELETE FROM sales_lines WHERE id = %s", (line_id,)),
        ("DELETE FROM sales_orders WHERE id = %s", (order_id,)),
    ]:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with psycopg.connect(url) as connection:
                connection.execute(statement, params)


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("second_operation", ["return", "reduce_sale"])
def test_concurrent_returns_and_sale_reduction_cannot_over_return(sales, isolation,
                                                                 second_operation):
    url, _, _, line_id = sales
    ready = Barrier(2)

    def writer(number):
        try:
            with psycopg.connect(url, options="-c statement_timeout=5000") as connection:
                connection.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(
                    sql.SQL(isolation),
                ))
                connection.execute("SELECT count(*) FROM sales_returns").fetchone()
                ready.wait(timeout=5)  # Both snapshots exist before either writes.
                if number == 1 and second_operation == "reduce_sale":
                    connection.execute("UPDATE sales_lines SET quantity = 4 WHERE id = %s",
                                       (line_id,))
                else:
                    returned(connection, line_id, source_return_id=f"synthetic-race-{number}",
                             quantity=Decimal("7"))
            return "committed"
        except psycopg.errors.CheckViolation:
            return "rejected"
        except psycopg.errors.SerializationFailure:
            return "retry"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(writer, (0, 1)))
    assert outcomes.count("committed") == 1
    assert outcomes.count("rejected") + outcomes.count("retry") == 1
    with psycopg.connect(url) as connection:
        sold, total = connection.execute(
            "SELECT l.quantity, COALESCE(sum(r.quantity), 0) FROM sales_lines l "
            "LEFT JOIN sales_returns r ON r.sale_line_id = l.id "
            "WHERE l.id = %s GROUP BY l.id", (line_id,),
        ).fetchone()
        assert total <= sold


def test_metadata_matches_and_sqlalchemy_decimal_round_trip(sales):
    url, order_id, sku_id, _ = sales
    engine = sa.create_engine(make_url(url).set(drivername="postgresql+psycopg"))
    try:
        with engine.begin() as connection:
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
            line_id = connection.execute(sales_lines.insert().values(
                order_id=order_id, source_system="synthetic-pos",
                source_line_id="synthetic-metadata", sku_id=sku_id,
                quantity=Decimal("1.123456"), unit_price=Decimal("0.1234"),
                unit_cost=None,
            ).returning(sales_lines.c.id)).scalar_one()
            connection.execute(sales_returns.insert().values(
                source_system="synthetic-pos", source_return_id="synthetic-metadata",
                source_line_id="synthetic-return-01", sale_line_id=line_id,
                quantity=Decimal("0.000001"), returned_at=WHEN,
            ))
        with engine.connect() as connection:
            record = connection.execute(sa.select(sales_lines).where(
                sales_lines.c.id == line_id,
            )).one()
            assert record.quantity == Decimal("1.123456")
            assert record.unit_price == Decimal("0.1234")
            assert record.unit_cost is None
            assert connection.execute(sa.select(sales_orders.c.currency)).scalar_one() == "MXN"
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_preserves_prior_schema_and_data(sales):
    url, _, sku_id, line_id = sales
    with psycopg.connect(url) as connection:
        returned(connection, line_id)
        insert(connection, "customers", opaque_ref="synthetic-p0013-customer",
               subject_kind="anonymous", created_at=WHEN, last_activity_at=WHEN)
    run_alembic(url, "upgrade", "head")
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT count(*) FROM sales_returns").fetchone() == (1,)
    run_alembic(url, "downgrade", PREVIOUS)
    assert revisions(url) == [(PREVIOUS,)]
    assert all((name,) not in tables(url) for name in
               ("sales_orders", "sales_lines", "sales_returns"))
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT id FROM skus").fetchall() == [(sku_id,)]
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (1,)
        assert connection.execute(
            "SELECT proname FROM pg_proc WHERE proname IN "
            "('sales_return_quantity_guard', 'sales_line_quantity_guard')",
        ).fetchall() == []
    run_alembic(url, "upgrade", "head")
    assert revisions(url) == [(HEAD,)]
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT count(*) FROM sales_orders").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (1,)
