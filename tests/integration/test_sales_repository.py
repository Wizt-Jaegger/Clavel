"""Synthetic P0017 mechanics on disposable PostgreSQL, never live feed evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier

import psycopg
import pytest

from clavel.core.settings import Settings
from clavel.database import Database
from clavel.database.repositories import CatalogRepository
from clavel.database.sales_repository import (
    ReturnLine, SaleLine, SalesConflict, SalesRepository, UnknownSale,
)
from tests.integration.test_migrations import run_alembic


WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
SOURCE = "synthetic-pos"


@pytest.fixture
def sales_database(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    database = Database(Settings(
        _env_file=None, app_env="test", database_url=migration_database_url,
    ))
    with database.session() as connection:
        sku = CatalogRepository(connection).upsert_sku("SYNTHETIC-P0017", "Synthetic item")
    return database, sku.id


def sale(sku_id, reference="synthetic-line", **changes):
    return replace(SaleLine(reference, sku_id, Decimal("10"), Decimal("12.3456")), **changes)


def order(connection, lines, reference="synthetic-order", source=SOURCE, **changes):
    values = {"sold_at": WHEN, "currency": "MXN", **changes}
    return SalesRepository(connection).record_order(source, reference, lines=lines, **values)


def returned(reference="synthetic-return", **changes):
    return replace(ReturnLine(reference, "synthetic-return-line", "synthetic-order",
                              "synthetic-line", Decimal("4"), WHEN), **changes)


def counts(connection):
    return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                 for table in ("sales_orders", "sales_lines", "sales_returns"))


def test_exact_order_and_return_replay_after_reconnect(sales_database):
    database, sku = sales_database
    lines = (sale(sku), sale(sku, "synthetic-line-2", unit_cost=Decimal("0")))
    returns = (returned(), returned("synthetic-return-2", quantity=Decimal("6")))
    with database.session() as connection:
        order_id = order(connection, lines)
        ids = SalesRepository(connection).record_returns(SOURCE, returns)
    with database.session() as connection:
        offset_time = WHEN.astimezone(timezone(timedelta(hours=-6)))
        assert order(connection, lines[::-1], sold_at=offset_time) == order_id
        assert SalesRepository(connection).record_returns(SOURCE, returns[::-1]) == ids[::-1]
        assert counts(connection) == (1, 2, 2)
        assert connection.execute(
            "SELECT unit_cost FROM sales_lines ORDER BY id",
        ).fetchall() == [(None,), (Decimal("0"),)]
        assert connection.execute("SELECT sum(quantity) FROM sales_returns").fetchone() == (10,)


@pytest.mark.parametrize("change", ["currency", "time", "customer", "quantity", "price",
                                     "cost", "sku", "missing", "extra", "line_id"])
def test_order_conflicts_preserve_original(sales_database, change):
    database, sku = sales_database
    original = (sale(sku), sale(sku, "synthetic-second"))
    with database.session() as connection:
        order(connection, original)
    lines, header = original, {}
    if change in ("currency", "time", "customer"):
        header = {"currency": {"currency": "USD"},
                  "time": {"sold_at": WHEN + timedelta(seconds=1)},
                  "customer": {"customer_id": -1}}[change]
    elif change in ("quantity", "price", "cost", "sku", "line_id"):
        field, value = {"quantity": ("quantity", Decimal("9")),
                        "price": ("unit_price", Decimal("13")),
                        "cost": ("unit_cost", Decimal("0")),
                        "sku": ("sku_id", -1),
                        "line_id": ("source_line_id", "synthetic-renamed")}[change]
        lines = (replace(original[0], **{field: value}), original[1])
    elif change == "missing":
        lines = original[:1]
    else:
        lines = (*original, sale(sku, "synthetic-extra"))
    with database.session() as connection:
        with pytest.raises(SalesConflict):
            order(connection, lines, **header)
        assert order(connection, original)
        assert counts(connection) == (1, 2, 0)


def test_partial_order_failure_caught_by_caller_leaves_no_partial_order(sales_database):
    database, sku = sales_database
    with database.session() as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            order(connection, (sale(sku, "synthetic-a"), sale(-1, "synthetic-z")))
        assert counts(connection) == (0, 0, 0)
        order(connection, (sale(sku),))
    with database.session() as connection:
        assert counts(connection) == (1, 1, 0)


@pytest.mark.parametrize("operation", ["order", "return"])
def test_repository_does_not_commit_idle_callers_transaction(sales_database, operation):
    database, sku = sales_database
    if operation == "return":
        with database.session() as connection:
            order(connection, (sale(sku),))
    with pytest.raises(RuntimeError):
        with database.session() as connection:
            if operation == "order":
                order(connection, (sale(sku),))
            else:
                SalesRepository(connection).record_returns(SOURCE, (returned(),))
            raise RuntimeError("synthetic downstream failure")
    with database.session() as connection:
        assert counts(connection) == ((0, 0, 0) if operation == "order" else (1, 1, 0))


@pytest.mark.parametrize("failure", ["over_return", "unknown", "conflict", "precision"])
def test_partial_return_batch_failure_is_atomic(sales_database, failure):
    database, sku = sales_database
    with database.session() as connection:
        order(connection, (sale(sku),))
        repo = SalesRepository(connection)
        repo.record_returns(SOURCE, (returned(),))
        invalid, error = {
            "over_return": (returned("synthetic-z", quantity=Decimal("5")),
                            psycopg.errors.CheckViolation),
            "unknown": (returned("synthetic-z", source_order_id="synthetic-absent"), UnknownSale),
            "conflict": (returned(quantity=Decimal("3")), SalesConflict),
            "precision": (returned("synthetic-z", quantity=Decimal("0.0000001")),
                          psycopg.errors.CheckViolation),
        }[failure]
        with pytest.raises(error):
            repo.record_returns(SOURCE, (returned("synthetic-a", quantity=Decimal("2")), invalid))
        assert counts(connection) == (1, 1, 1)
        assert connection.execute("SELECT sum(quantity) FROM sales_returns").fetchone() == (4,)
        repo.record_returns(SOURCE, (returned("synthetic-valid", quantity=Decimal("6")),))
    with database.session() as connection:
        assert counts(connection) == (1, 1, 2)


def test_order_and_linked_returns_share_callers_unit_of_work(sales_database):
    database, sku = sales_database
    with pytest.raises(psycopg.errors.CheckViolation):
        with database.session() as connection:
            order(connection, (sale(sku),))
            SalesRepository(connection).record_returns(SOURCE, (
                returned(), returned("synthetic-excess", quantity=Decimal("7")),
            ))
    with database.session() as connection:
        assert counts(connection) == (0, 0, 0)


def test_concurrent_batches_lock_multiple_sales_in_stable_order(sales_database):
    database, sku = sales_database
    with database.session() as connection:
        order(connection, (sale(sku), sale(sku, "synthetic-second")))
    barrier = Barrier(2)

    def write(index):
        lines = (returned(f"synthetic-{index}-first"),
                 returned(f"synthetic-{index}-second", sale_source_line_id="synthetic-second"))
        with database.session() as connection:
            barrier.wait(timeout=10)
            return SalesRepository(connection).record_returns(
                SOURCE, lines if index == 0 else lines[::-1],
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, range(2)))
    assert len({return_id for batch in results for return_id in batch}) == 4
    with database.session() as connection:
        assert connection.execute(
            "SELECT sum(quantity) FROM sales_returns GROUP BY sale_line_id",
        ).fetchall() == [(Decimal("8"),), (Decimal("8"),)]


@pytest.mark.parametrize("field,value", [("quantity", Decimal("3")),
                                          ("returned_at", WHEN + timedelta(seconds=1)),
                                          ("sale_source_line_id", "synthetic-second")])
def test_return_replay_cannot_change_payload_or_sale_link(sales_database, field, value):
    database, sku = sales_database
    with database.session() as connection:
        order(connection, (sale(sku), sale(sku, "synthetic-second")))
        repo = SalesRepository(connection)
        original = repo.record_returns(SOURCE, (returned(),))
        with pytest.raises(SalesConflict):
            repo.record_returns(SOURCE, (returned(**{field: value}),))
        assert repo.record_returns(SOURCE, (returned(),)) == original
        assert counts(connection) == (1, 2, 1)


def test_source_order_and_return_line_scopes(sales_database):
    database, sku = sales_database
    with database.session() as connection:
        for source in (SOURCE, "synthetic-other-pos"):
            order(connection, (sale(sku),), source=source)
            SalesRepository(connection).record_returns(source, (returned(),))
        order(connection, (sale(sku),), reference="synthetic-order-2")
        repo = SalesRepository(connection)
        repo.record_returns(SOURCE, (returned(source_line_id="synthetic-return-line-2",
                                              source_order_id="synthetic-order-2"),))
        with pytest.raises(UnknownSale):
            repo.record_returns("synthetic-absent-source", (returned(),))
        assert counts(connection) == (3, 3, 3)


@pytest.mark.parametrize("kind", ["order_replay", "order_conflict", "return_replay", "over_return"])
def test_concurrent_writers(sales_database, kind):
    database, sku = sales_database
    if kind.startswith("return") or kind == "over_return":
        with database.session() as connection:
            order(connection, (sale(sku),))
    barrier = Barrier(2)

    def write(index):
        with database.session() as connection:
            barrier.wait(timeout=10)
            try:
                if kind.startswith("order"):
                    quantity = Decimal("9") if kind == "order_conflict" and index else Decimal("10")
                    value = order(connection, (sale(sku, quantity=quantity),))
                else:
                    line = (returned(quantity=Decimal("10")) if kind == "return_replay" else
                            returned(f"synthetic-return-{index}", quantity=Decimal("6")))
                    value = SalesRepository(connection).record_returns(SOURCE, (line,))
                return "ok", value
            except (SalesConflict, psycopg.errors.CheckViolation) as error:
                return type(error).__name__, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, range(2)))
    statuses = sorted(status for status, _ in results)
    if kind.endswith("replay"):
        assert statuses == ["ok", "ok"]
        assert results[0][1] == results[1][1]
    else:
        assert statuses == (["SalesConflict", "ok"] if kind == "order_conflict"
                            else ["CheckViolation", "ok"])
    with database.session() as connection:
        assert counts(connection) == (1, 1, 0 if kind.startswith("order") else 1)


def test_validation_and_autocommit_rejected(sales_database):
    database, sku = sales_database
    with database.session() as connection:
        for lines in ((), (sale(sku), sale(sku)),
                      (sale(sku, quantity=1.2),), (sale(sku, " padded "),)):
            with pytest.raises(ValueError):
                order(connection, lines)
        with pytest.raises(ValueError, match="timezone-aware"):
            order(connection, (sale(sku),), sold_at=WHEN.replace(tzinfo=None))
        repo = SalesRepository(connection)
        for lines in ((), (returned(), returned()),
                      (returned(returned_at=WHEN.replace(tzinfo=None)),),
                      (returned(quantity=1.2),)):
            with pytest.raises(ValueError):
                repo.record_returns(SOURCE, lines)
        assert counts(connection) == (0, 0, 0)
    with database.session() as connection:
        connection.autocommit = True
        with pytest.raises(ValueError, match="caller-managed"):
            SalesRepository(connection)
