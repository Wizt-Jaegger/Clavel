"""Real disposable PostgreSQL, synthetic catalog records only; no live evidence."""

from decimal import Decimal

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from clavel.database.catalog import categories, hardware_attributes, metadata, skus
from tests.integration.test_migrations import BASELINE, HEAD, revisions, run_alembic, tables


@pytest.fixture
def catalog(migration_database_url):
    url = migration_database_url
    run_alembic(url, "upgrade", "head")
    with psycopg.connect(url) as connection:
        sku_id = connection.execute(
            "INSERT INTO skus (sku, name) VALUES ('SYNTHETIC-001', 'Synthetic bolt') "
            "RETURNING id",
        ).fetchone()[0]
    return url, sku_id


def insert_attribute(connection, sku_id, **values):
    record = {
        "sku_id": sku_id, "name": "synthetic_attribute", "value_kind": "unknown",
        "text_value": None, "number_value": None, "boolean_value": None, "unit": None,
        **values,
    }
    connection.execute(
        "INSERT INTO hardware_attributes "
        "(sku_id, name, value_kind, text_value, number_value, boolean_value, unit) "
        "VALUES (%(sku_id)s, %(name)s, %(value_kind)s, %(text_value)s, "
        "%(number_value)s, %(boolean_value)s, %(unit)s)", record,
    )


def test_sku_unique_even_with_a_different_category(catalog):
    url, _ = catalog
    with psycopg.connect(url) as connection:
        category_id = connection.execute(
            "INSERT INTO categories (code, name) VALUES ('SYNTHETIC', 'Synthetic') "
            "RETURNING id",
        ).fetchone()[0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(url) as connection:
            connection.execute(
                "INSERT INTO skus (sku, name, category_id) "
                "VALUES ('SYNTHETIC-001', 'Synthetic duplicate', %s)", (category_id,),
            )


def test_typed_values_unknowns_and_metadata_match(catalog):
    url, sku_id = catalog
    engine = sa.create_engine(make_url(url).set(drivername="postgresql+psycopg"))
    try:
        with engine.begin() as connection:
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
            category_id = connection.execute(categories.insert().values(
                code="SYNTHETIC-FASTENERS", name="Synthetic fasteners",
            ).returning(categories.c.id)).scalar_one()
            connection.execute(skus.update().where(skus.c.id == sku_id).values(
                category_id=category_id,
            ))
            connection.execute(hardware_attributes.insert(), [
                dict(sku_id=sku_id, name="material", value_kind="text",
                     text_value="synthetic steel", number_value=None,
                     boolean_value=None, unit=None),
                dict(sku_id=sku_id, name="length", value_kind="number",
                     text_value=None, number_value=Decimal("12.50"),
                     boolean_value=None, unit="mm"),
                dict(sku_id=sku_id, name="zero", value_kind="number",
                     text_value=None, number_value=0, boolean_value=None, unit=None),
                dict(sku_id=sku_id, name="coated", value_kind="boolean",
                     text_value=None, number_value=None, boolean_value=False, unit=None),
                dict(sku_id=sku_id, name="diameter", value_kind="unknown",
                     text_value=None, number_value=None, boolean_value=None, unit="mm"),
            ])
            records = {row.name: row for row in connection.execute(
                sa.select(hardware_attributes),
            )}
            assert records["length"].number_value == Decimal("12.50")
            assert records["coated"].boolean_value is False
            assert records["zero"].number_value == 0
            assert records["diameter"].value_kind == "unknown"
            assert records["diameter"].number_value is None
            assert "thread_standard" not in records  # Absent means unobserved.
            unknown_sku = connection.execute(skus.insert().values(
                sku="SYNTHETIC-UNKNOWN", name="Synthetic unknown category",
            ).returning(skus.c.category_id)).scalar_one()
            assert unknown_sku is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("values", [
    {"value_kind": "unsupported"},
    {"value_kind": "text"},
    {"value_kind": "text", "text_value": "   "},
    {"value_kind": "text", "text_value": "synthetic", "number_value": 1},
    {"value_kind": "text", "text_value": "synthetic", "unit": "mm"},
    {"value_kind": "number"},
    {"value_kind": "number", "number_value": 1, "boolean_value": False},
    {"value_kind": "number", "number_value": Decimal("NaN")},
    {"value_kind": "number", "number_value": Decimal("Infinity")},
    {"value_kind": "number", "number_value": Decimal("-Infinity")},
    {"value_kind": "number", "number_value": 1, "unit": ""},
    {"value_kind": "number", "number_value": 1, "unit": " mm "},
    {"value_kind": "boolean"},
    {"value_kind": "boolean", "boolean_value": True, "text_value": "synthetic"},
    {"value_kind": "boolean", "boolean_value": False, "unit": "mm"},
    {"value_kind": "unknown", "number_value": 0},
    {"value_kind": "unknown", "boolean_value": False},
    {"value_kind": "unknown", "text_value": "synthetic"},
    {"name": ""},
    {"name": " synthetic "},
])
def test_malformed_attributes_rejected(catalog, values):
    url, sku_id = catalog
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            insert_attribute(connection, sku_id, **values)


@pytest.mark.parametrize("values,error", [
    ({"value_kind": None}, psycopg.errors.NotNullViolation),
    ({"value_kind": "number", "number_value": "synthetic-not-a-number"},
     psycopg.errors.InvalidTextRepresentation),
    ({"sku_id": -1}, psycopg.errors.ForeignKeyViolation),
])
def test_missing_type_invalid_number_and_orphan_rejected(catalog, values, error):
    url, sku_id = catalog
    record_sku_id = values.get("sku_id", sku_id)
    with pytest.raises(error):
        with psycopg.connect(url) as connection:
            insert_attribute(connection, **{**values, "sku_id": record_sku_id})


def test_duplicate_attributes_and_category_foreign_key_rejected(catalog):
    url, sku_id = catalog
    with psycopg.connect(url) as connection:
        insert_attribute(connection, sku_id)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(url) as connection:
            insert_attribute(connection, sku_id)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(url) as connection:
            connection.execute("UPDATE skus SET category_id = -1 WHERE id = %s", (sku_id,))


@pytest.mark.parametrize("sku", ["", "   ", " SYNTHETIC", "SYNTHETIC "])
def test_empty_or_padded_sku_rejected(catalog, sku):
    url, _ = catalog
    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(url) as connection:
            connection.execute("INSERT INTO skus (sku, name) VALUES (%s, 'Synthetic')", (sku,))


def test_catalog_upgrade_downgrade_upgrade(catalog):
    url, _ = catalog
    expected = [("alembic_version",), ("categories",), ("hardware_attributes",), ("skus",)]
    assert tables(url) == expected
    run_alembic(url, "upgrade", "head")  # Idempotent with an existing synthetic SKU.
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT count(*) FROM skus").fetchone() == (1,)
    run_alembic(url, "downgrade", BASELINE)
    assert revisions(url) == [(BASELINE,)]
    assert tables(url) == [("alembic_version",)]
    run_alembic(url, "upgrade", "head")
    assert revisions(url) == [(HEAD,)]
    assert tables(url) == expected
