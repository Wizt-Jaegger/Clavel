"""Repository mechanics on disposable PostgreSQL with synthetic records only.

No provider, production catalog, live stock, freshness, or eligibility evidence.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier

import psycopg
import pytest

from clavel.core.settings import Settings
from clavel.database import Database
from clavel.database.repositories import (
    CatalogRepository, HardwareAttribute, StockObservation, StockRepository,
)
from tests.integration.test_migrations import run_alembic


OBSERVED = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def database(migration_database_url):
    """Actual local database, synthetic data only, migrated through accepted head."""
    run_alembic(migration_database_url, "upgrade", "head")
    return Database(Settings(
        _env_file=None, app_env="test", database_url=migration_database_url,
    ))


def seed(database, count=1):
    with database.session() as connection:
        catalog = CatalogRepository(connection)
        return tuple(catalog.upsert_sku(f"SYNTHETIC-{i}", f"Synthetic item {i}")
                     for i in range(count))


def test_catalog_upserts_read_back_without_duplicates_and_preserve_unknowns(database):
    with database.session() as connection:
        catalog = CatalogRepository(connection)
        category = catalog.upsert_category("SYNTHETIC", "Synthetic category")
        assert catalog.upsert_category(category.code, category.name) == category
        updated_category = catalog.upsert_category(category.code, "Synthetic revised")
        assert updated_category.id == category.id
        assert catalog.get_category(category.id) == updated_category
        # Parameterized SQL must preserve quotes and SQL-like text as literal data.
        sku = catalog.upsert_sku("SYNTHETIC-'quoted", "Synthetic '; SELECT 1;", category.id)
        assert catalog.upsert_sku(sku.sku, sku.name, category.id) == sku
        changed = catalog.upsert_sku(sku.sku, "Synthetic renamed", None)
        assert changed.id == sku.id and changed.category_id is None
        assert catalog.get_sku(sku.sku) == changed
        assert catalog.get_attributes(sku.id) == ()  # Absent is unobserved.
        attributes = (
            HardwareAttribute(sku.id, "diameter", "number", number_value=Decimal("12.50"),
                              unit="mm"),
            HardwareAttribute(sku.id, "coated", "boolean", boolean_value=False),
            HardwareAttribute(sku.id, "material", "text", text_value="Synthetic steel"),
            HardwareAttribute(sku.id, "thread", unit="mm"),
        )
        for attribute in attributes:
            assert catalog.upsert_attribute(attribute) == attribute
            assert catalog.upsert_attribute(attribute) == attribute
        assert catalog.get_attributes(sku.id) == tuple(sorted(attributes, key=lambda a: a.name))
        unknown = HardwareAttribute(sku.id, "diameter", unit="mm")
        assert catalog.upsert_attribute(unknown) == unknown
        assert catalog.get_attributes(sku.id)[1] == unknown  # Clear former numeric value.
        assert len(catalog.list_skus().items) == 1
        assert len(catalog.list_categories().items) == 1
    with database.session() as connection:
        assert CatalogRepository(connection).get_sku(sku.sku) == changed


def test_missing_reads_and_empty_pages(database):
    with database.session() as connection:
        catalog, stock = CatalogRepository(connection), StockRepository(connection)
        assert catalog.get_sku("SYNTHETIC-MISSING") is None
        assert catalog.get_category(-1) is None
        assert catalog.get_attributes(-1) == ()
        assert stock.get(-1) is None
        for page in (catalog.list_skus(), catalog.list_categories(), stock.list_stock()):
            assert page.items == () and page.next_cursor is None


def test_missing_unknown_zero_and_positive_stock_are_distinct(database):
    sku, = seed(database)
    with database.session() as connection:
        stock = StockRepository(connection)
        assert stock.get(sku.id) is None
        for version, quantity in enumerate((None, 0, 7, None)):
            observation = StockObservation(sku.id, quantity, version, OBSERVED)
            assert stock.upsert(observation) == observation
            assert stock.get(sku.id) == observation
        assert stock.list_stock().items == (observation,)


@pytest.mark.parametrize("version,quantity,observed_at", [
    (10, 5, OBSERVED),  # Exact duplicate is a replay, not a new observation.
    (10, 99, OBSERVED + timedelta(seconds=1)),
    (9, 99, OBSERVED + timedelta(seconds=1)),
    (11, 99, OBSERVED - timedelta(seconds=1)),
])
def test_duplicate_and_stale_stock_reject_and_roll_back_unit_of_work(
    database, version, quantity, observed_at,
):
    sku, = seed(database)
    original = StockObservation(sku.id, 5, 10, OBSERVED)
    with database.session() as connection:
        StockRepository(connection).upsert(original)
    with pytest.raises(psycopg.errors.CheckViolation) as failure:
        with database.session() as connection:
            CatalogRepository(connection).upsert_sku(sku.sku, "Synthetic must roll back")
            StockRepository(connection).upsert(
                StockObservation(sku.id, quantity, version, observed_at),
            )
    assert failure.value.diag.constraint_name == "inventory_update_fresh"
    with database.session() as connection:
        assert StockRepository(connection).get(sku.id) == original
        assert CatalogRepository(connection).get_sku(sku.sku) == sku


def test_failed_catalog_write_rolls_back_catalog_attributes_and_stock(database):
    with pytest.raises(psycopg.errors.CheckViolation):
        with database.session() as connection:
            catalog = CatalogRepository(connection)
            category = catalog.upsert_category("SYNTHETIC", "Synthetic")
            sku = catalog.upsert_sku("SYNTHETIC-ROLLBACK", "Synthetic", category.id)
            StockRepository(connection).upsert(StockObservation(sku.id, 0, 0, OBSERVED))
            catalog.upsert_attribute(HardwareAttribute(sku.id, "valid"))
            catalog.upsert_attribute(HardwareAttribute(sku.id, "invalid", "number"))
    with database.session() as connection:
        catalog = CatalogRepository(connection)
        assert catalog.list_skus().items == ()
        assert catalog.list_categories().items == ()
        assert catalog.get_attributes(sku.id) == ()
        assert StockRepository(connection).list_stock().items == ()


def test_invalid_stock_and_naive_timestamp_never_replace_observation(database):
    sku, = seed(database)
    original = StockObservation(sku.id, 5, 10, OBSERVED)
    with database.session() as connection:
        StockRepository(connection).upsert(original)
    for invalid, error in (
        (StockObservation(sku.id, -1, 11, OBSERVED), psycopg.errors.CheckViolation),
        (StockObservation(-1, 1, 11, OBSERVED), psycopg.errors.ForeignKeyViolation),
        (StockObservation(sku.id, 1, 11, OBSERVED.replace(tzinfo=None)), ValueError),
    ):
        with pytest.raises(error):
            with database.session() as connection:
                StockRepository(connection).upsert(invalid)
    with database.session() as connection:
        assert StockRepository(connection).get(sku.id) == original
        offset_time = OBSERVED.astimezone(timezone(timedelta(hours=-6)))
        assert StockRepository(connection).upsert(
            StockObservation(sku.id, 0, 11, offset_time),
        ).observed_at == OBSERVED


@pytest.mark.parametrize("existing", [False, True], ids=["insert-race", "update-race"])
def test_concurrent_stock_upserts_keep_newest_committed_version(database, existing):
    sku, = seed(database)
    if existing:
        with database.session() as connection:
            StockRepository(connection).upsert(StockObservation(sku.id, None, 10, OBSERVED))
    barrier = Barrier(2, timeout=5)

    def write(version):
        try:
            with database.session() as connection:
                barrier.wait()
                StockRepository(connection).upsert(StockObservation(
                    sku.id, version, version, OBSERVED + timedelta(seconds=version),
                ))
            return "applied"
        except psycopg.errors.CheckViolation as error:
            assert error.diag.constraint_name == "inventory_update_fresh"
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, (11, 12)))
    assert outcomes[1] == "applied" and outcomes[0] in {"applied", "stale"}
    with database.session() as connection:
        assert StockRepository(connection).get(sku.id) == StockObservation(
            sku.id, 12, 12, OBSERVED + timedelta(seconds=12),
        )


def test_concurrent_equal_stock_versions_allow_exactly_one_writer(database):
    sku, = seed(database)
    barrier = Barrier(2, timeout=5)

    def write(quantity):
        try:
            with database.session() as connection:
                barrier.wait()
                StockRepository(connection).upsert(StockObservation(sku.id, quantity, 1, OBSERVED))
            return "applied"
        except psycopg.errors.CheckViolation as error:
            assert error.diag.constraint_name == "inventory_update_fresh"
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, (5, 8))) == ["applied", "stale"]
    with database.session() as connection:
        observation = StockRepository(connection).get(sku.id)
        assert observation.source_version == 1 and observation.sellable_stock in (5, 8)


def test_concurrent_catalog_upserts_reuse_identity_without_partial_attribute_values(database):
    barrier = Barrier(2, timeout=5)

    def write(value):
        with database.session() as connection:
            catalog = CatalogRepository(connection)
            barrier.wait()
            category = catalog.upsert_category("SYNTHETIC", f"Synthetic category {value}")
            sku = catalog.upsert_sku("SYNTHETIC-RACE", f"Synthetic item {value}", category.id)
            attribute = HardwareAttribute(sku.id, "size", "number", number_value=Decimal(value),
                                          unit=f"synthetic-{value}")
            catalog.upsert_attribute(attribute)
            return category.id, sku.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(write, (1, 2)))
    assert ids[0] == ids[1]
    with database.session() as connection:
        catalog = CatalogRepository(connection)
        assert len(catalog.list_skus().items) == len(catalog.list_categories().items) == 1
        sku = catalog.get_sku("SYNTHETIC-RACE")
        value = int(sku.name.rsplit(" ", 1)[1])
        assert catalog.get_category(sku.category_id).name == f"Synthetic category {value}"
        assert catalog.get_attributes(sku.id) == (
            HardwareAttribute(sku.id, "size", "number", number_value=Decimal(value),
                              unit=f"synthetic-{value}"),
        )


@pytest.mark.parametrize("collection", ["skus", "categories", "stock"])
def test_stable_pages_across_updates_inserts_and_boundary_deletion(database, collection):
    items = seed(database, 5)
    with database.session() as connection:
        catalog, stock = CatalogRepository(connection), StockRepository(connection)
        for item in items:
            catalog.upsert_category(item.sku, item.name)
            stock.upsert(StockObservation(item.id, 0, 0, OBSERVED))

    def read_page(connection, **kwargs):
        return {
            "skus": CatalogRepository(connection).list_skus,
            "categories": CatalogRepository(connection).list_categories,
            "stock": StockRepository(connection).list_stock,
        }[collection](limit=2, **kwargs)

    def key(item):
        return item.sku_id if collection == "stock" else item.id

    with database.session() as connection:
        first = read_page(connection)
        original_cursor = first.next_cursor
        assert len(first.items) == 2 and original_cursor is not None
    with database.session() as connection:
        catalog, stock = CatalogRepository(connection), StockRepository(connection)
        for item in items:
            catalog.upsert_sku(item.sku, "Synthetic renamed")
            catalog.upsert_category(item.sku, "Synthetic renamed")
            stock.upsert(StockObservation(item.id, None, 1, OBSERVED))
        new = catalog.upsert_sku("SYNTHETIC-LATE", "Synthetic late")
        new_category = catalog.upsert_category(new.sku, new.name)
        stock.upsert(StockObservation(new.id, 9, 0, OBSERVED))
        boundary = key(first.items[-1])
        # Delete the boundary row: an ID cursor must work without looking it up.
        if collection == "skus":
            connection.execute("DELETE FROM inventory WHERE sku_id = %s", (boundary,))
            connection.execute("DELETE FROM skus WHERE id = %s", (boundary,))
        elif collection == "categories":
            connection.execute("DELETE FROM categories WHERE id = %s", (boundary,))
        else:
            connection.execute("DELETE FROM inventory WHERE sku_id = %s", (boundary,))
    seen = [key(item) for item in first.items]
    cursor = original_cursor
    while cursor:
        with database.session() as connection:
            page = read_page(connection, cursor=cursor)
        seen.extend(key(item) for item in page.items)
        cursor = page.next_cursor
    assert seen == sorted(set(seen))
    assert len(seen) == 6
    assert seen[-1] == (new_category.id if collection == "categories" else new.id)
    with database.session() as connection:
        repeated = read_page(connection, cursor=original_cursor)
        assert [key(item) for item in repeated.items] == seen[2:4]
        empty = read_page(connection, cursor=f"v1:{collection}:9223372036854775807")
        assert empty.items == () and empty.next_cursor is None


def test_repeatable_read_keeps_catalog_and_stock_traversal_snapshot(database):
    first, second = seed(database, 2)
    with database.session() as connection:
        stock = StockRepository(connection)
        stock.upsert(StockObservation(first.id, 0, 0, OBSERVED))
        stock.upsert(StockObservation(second.id, 7, 0, OBSERVED))
    with database.session() as reader:
        reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        catalog, stock = CatalogRepository(reader), StockRepository(reader)
        sku_page, stock_page = catalog.list_skus(limit=1), stock.list_stock(limit=1)
        with database.session() as writer:
            CatalogRepository(writer).upsert_sku(second.sku, "Synthetic changed")
            CatalogRepository(writer).upsert_sku("SYNTHETIC-LATE", "Synthetic late")
            StockRepository(writer).upsert(StockObservation(second.id, None, 1, OBSERVED))
        remaining = catalog.list_skus(cursor=sku_page.next_cursor)
        assert remaining.items == (second,) and remaining.next_cursor is None
        remaining_stock = stock.list_stock(cursor=stock_page.next_cursor)
        assert remaining_stock.items == (StockObservation(second.id, 7, 0, OBSERVED),)
        assert remaining_stock.next_cursor is None
    with database.session() as connection:
        assert CatalogRepository(connection).get_sku(second.sku).name == "Synthetic changed"
        assert StockRepository(connection).get(second.id).sellable_stock is None


def test_page_limits_and_malformed_or_cross_collection_cursors_rejected(database):
    with database.session() as connection:
        catalog = CatalogRepository(connection)
        for invalid in (0, -1, 501, True, 1.5, "2", None):
            for method in (catalog.list_skus, catalog.list_categories,
                           StockRepository(connection).list_stock):
                with pytest.raises(ValueError, match="page limit"):
                    method(limit=invalid)
        for invalid in ("", "v2:skus:1", "v1:stock:1", "v1:categories:1", "v1:skus:0",
                        "v1:skus:-1", "v1:skus:01", "v1:skus:", "v1:skus:1:2",
                        "v1:skus:١", "v1:skus:1 OR TRUE", "v1:skus:9223372036854775808",
                        "v1:skus:" + "9" * 100, 1):
            with pytest.raises(ValueError, match="cursor"):
                catalog.list_skus(cursor=invalid)
        # Invalid pagination performs no SQL and leaves the caller's session usable.
        assert catalog.list_skus(limit=500).items == ()


def test_exact_page_boundary_has_no_spurious_next_cursor(database):
    expected = seed(database, 2)
    with database.session() as connection:
        page = CatalogRepository(connection).list_skus(limit=2)
        assert page.items == expected and page.next_cursor is None


def test_repositories_require_caller_managed_transactions(database):
    with database.session() as connection:
        connection.autocommit = True
        for repository in (CatalogRepository, StockRepository):
            with pytest.raises(ValueError, match="caller-managed transaction"):
                repository(connection)
