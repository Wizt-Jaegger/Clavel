"""Disposable real PostgreSQL with synthetic observations; no live stock evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from clavel.database.inventory import inventory
from clavel.database.sales import metadata
from tests.integration.test_migrations import HEAD, revisions, run_alembic, tables


OBSERVED = datetime(2026, 1, 1, tzinfo=timezone.utc)
CATALOG_REVISION = "0002_catalog_schema"


@pytest.fixture
def stock_database(migration_database_url):
    url = migration_database_url
    run_alembic(url, "upgrade", "head")
    with psycopg.connect(url) as connection:
        sku_id = connection.execute(
            "INSERT INTO skus (sku, name) VALUES ('SYNTHETIC-STOCK', 'Synthetic stock') "
            "RETURNING id",
        ).fetchone()[0]
    return url, sku_id


def write_observation(connection, sku_id, *, stock=5, version=10,
                      observed_at=OBSERVED, upsert=False):
    statement = (
        "INSERT INTO inventory (sku_id, sellable_stock, source_version, observed_at) "
        "VALUES (%s, %s, %s, %s)"
    )
    if upsert:
        statement += (
            " ON CONFLICT (sku_id) DO UPDATE SET "
            "sellable_stock = EXCLUDED.sellable_stock, "
            "source_version = EXCLUDED.source_version, observed_at = EXCLUDED.observed_at"
        )
    connection.execute(statement, (sku_id, stock, version, observed_at))


def observation(connection, sku_id):
    return connection.execute(
        "SELECT sellable_stock, source_version, observed_at FROM inventory WHERE sku_id = %s",
        (sku_id,),
    ).fetchone()


def test_unknown_zero_positive_and_timezone_round_trip(stock_database):
    url, sku_id = stock_database
    engine = sa.create_engine(make_url(url).set(drivername="postgresql+psycopg"))
    try:
        with engine.begin() as connection:
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
            assert connection.execute(sa.select(inventory)).all() == []  # Unknown, not zero.
            connection.execute(inventory.insert().values(
                sku_id=sku_id, source_version=0, observed_at=OBSERVED,
            ))
            assert connection.execute(sa.select(inventory.c.sellable_stock)).scalar() is None
            for version, quantity in enumerate((0, 7, None), start=1):
                # Same instant with a different UTC offset; not a time regression.
                connection.execute(inventory.update().values(
                    source_version=version, sellable_stock=quantity,
                    observed_at=OBSERVED.astimezone(timezone(timedelta(hours=-6))),
                ))
                row = connection.execute(sa.select(inventory)).one()
                assert row.sellable_stock == quantity
                assert row.source_version == version
                assert row.observed_at == OBSERVED
    finally:
        engine.dispose()


@pytest.mark.parametrize("values,error,constraint", [
    ({"stock": -1}, psycopg.errors.CheckViolation, "inventory_stock_nonnegative"),
    ({"version": -1}, psycopg.errors.CheckViolation, "inventory_version_nonnegative"),
    ({"version": None}, psycopg.errors.NotNullViolation, None),
    ({"observed_at": None}, psycopg.errors.NotNullViolation, None),
    ({"observed_at": "infinity"}, psycopg.errors.CheckViolation,
     "inventory_observation_finite"),
    ({"observed_at": "-infinity"}, psycopg.errors.CheckViolation,
     "inventory_observation_finite"),
    ({"sku_id": -1}, psycopg.errors.ForeignKeyViolation, None),
])
def test_invalid_observations_rejected(stock_database, values, error, constraint):
    url, sku_id = stock_database
    with pytest.raises(error) as failure:
        with psycopg.connect(url) as connection:
            write_observation(connection, **{"sku_id": sku_id, **values})
    if constraint:
        assert failure.value.diag.constraint_name == constraint
    with psycopg.connect(url) as connection:
        assert observation(connection, sku_id) is None


@pytest.mark.parametrize("upsert", [False, True], ids=["update", "upsert"])
@pytest.mark.parametrize("version,observed_at", [
    (9, OBSERVED + timedelta(seconds=1)),  # Older version, newer time.
    (10, OBSERVED),  # Replay.
    (10, OBSERVED + timedelta(seconds=1)),  # Equal version, different payload.
    (11, OBSERVED - timedelta(seconds=1)),  # Newer version, older time.
])
def test_stale_updates_rejected_without_changing_observation(
    stock_database, upsert, version, observed_at,
):
    url, sku_id = stock_database
    with psycopg.connect(url) as connection:
        write_observation(connection, sku_id)
    with pytest.raises(psycopg.errors.CheckViolation) as failure:
        with psycopg.connect(url) as connection:
            if upsert:
                write_observation(connection, sku_id, stock=99, version=version,
                                  observed_at=observed_at, upsert=True)
            else:
                connection.execute(
                    "UPDATE inventory SET sellable_stock = 99, source_version = %s, "
                    "observed_at = %s WHERE sku_id = %s", (version, observed_at, sku_id),
                )
    assert failure.value.diag.constraint_name == "inventory_update_fresh"
    with psycopg.connect(url) as connection:
        assert observation(connection, sku_id) == (5, 10, OBSERVED)


def test_negative_stock_update_rolls_back_and_fresh_update_succeeds(stock_database):
    url, sku_id = stock_database
    with psycopg.connect(url) as connection:
        write_observation(connection, sku_id)
    with pytest.raises(psycopg.errors.CheckViolation) as failure:
        with psycopg.connect(url) as connection:
            write_observation(connection, sku_id, stock=-1, version=11, upsert=True)
    assert failure.value.diag.constraint_name == "inventory_stock_nonnegative"
    with psycopg.connect(url) as connection:
        assert observation(connection, sku_id) == (5, 10, OBSERVED)
        write_observation(connection, sku_id, stock=0, version=11,
                          observed_at=OBSERVED + timedelta(seconds=1), upsert=True)
    with psycopg.connect(url) as connection:
        assert observation(connection, sku_id) == (0, 11, OBSERVED + timedelta(seconds=1))


def test_unique_sku_and_immutable_identity(stock_database):
    url, sku_id = stock_database
    with psycopg.connect(url) as connection:
        write_observation(connection, sku_id)
        other_sku = connection.execute(
            "INSERT INTO skus (sku, name) VALUES ('SYNTHETIC-OTHER', 'Synthetic other') "
            "RETURNING id",
        ).fetchone()[0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(url) as connection:
            write_observation(connection, sku_id, version=11)
    with pytest.raises(psycopg.errors.CheckViolation) as failure:
        with psycopg.connect(url) as connection:
            connection.execute(
                "UPDATE inventory SET sku_id = %s, source_version = 11 WHERE sku_id = %s",
                (other_sku, sku_id),
            )
    assert failure.value.diag.constraint_name == "inventory_sku_immutable"


def test_concurrent_upserts_keep_newest_observation(stock_database):
    url, sku_id = stock_database
    with psycopg.connect(url) as connection:
        write_observation(connection, sku_id)
    barrier = Barrier(2, timeout=10)

    def writer(version):
        try:
            with psycopg.connect(url, options="-c statement_timeout=10000") as connection:
                barrier.wait()
                write_observation(connection, sku_id, stock=version, version=version,
                                  observed_at=OBSERVED + timedelta(seconds=version), upsert=True)
            return "applied"
        except psycopg.errors.CheckViolation as error:
            assert error.diag.constraint_name == "inventory_update_fresh"
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(writer, (11, 12)))
    assert outcomes[1] == "applied"
    assert outcomes[0] in {"applied", "stale"}
    with psycopg.connect(url) as connection:
        assert observation(connection, sku_id) == (12, 12, OBSERVED + timedelta(seconds=12))


def test_inventory_migration_round_trip_preserves_catalog(stock_database):
    url, sku_id = stock_database
    with psycopg.connect(url) as connection:
        write_observation(connection, sku_id)
    run_alembic(url, "upgrade", "head")
    with psycopg.connect(url) as connection:
        assert observation(connection, sku_id) == (5, 10, OBSERVED)
    run_alembic(url, "downgrade", CATALOG_REVISION)
    assert ("inventory",) not in tables(url)
    assert revisions(url) == [(CATALOG_REVISION,)]
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT id FROM skus").fetchall() == [(sku_id,)]
        assert connection.execute(
            "SELECT count(*) FROM pg_proc WHERE proname = 'enforce_inventory_observation_order'",
        ).fetchone() == (0,)
    run_alembic(url, "upgrade", "head")
    assert revisions(url) == [(HEAD,)]
    with psycopg.connect(url) as connection:
        write_observation(connection, sku_id)
    # Re-upgrade restored the trigger, not only the table.
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            write_observation(connection, sku_id, version=9, upsert=True)
