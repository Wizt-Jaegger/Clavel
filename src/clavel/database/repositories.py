"""Catalog and stock access inside a caller-owned PostgreSQL transaction.

Use with ``Database.session()``; repositories never commit, roll back, or close
the connection. Let SQL errors escape the session to roll back the whole unit
of work. Catalog writes replace supplied fields (including explicit unknowns);
catalog metadata has no source version, so competing writes serialize with the
last writer winning. Stock replays/regressions raise the schema's CheckViolation.

Pages use immutable IDs, ascending, with bounded, collection-specific cursors.
Updates to names/stock cannot move a row across a cursor. Under READ COMMITTED,
later pages can see newly committed rows ahead of the cursor; deletions and late
commits behind it are not replayed. Use one REPEATABLE READ transaction when a
consistent traversal snapshot is required. Cursors confer no authorization.

Missing stock rows and NULL quantities are unknown, not zero. Stored observations
carry their source time/version; these repositories make no freshness,
compatibility, or eligibility determination.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypeVar

import psycopg
from psycopg.rows import class_row


@dataclass(frozen=True)
class Category:
    id: int
    code: str
    name: str


@dataclass(frozen=True)
class Sku:
    id: int
    sku: str
    name: str
    category_id: int | None


@dataclass(frozen=True)
class HardwareAttribute:
    sku_id: int
    name: str
    value_kind: str = "unknown"
    text_value: str | None = None
    number_value: Decimal | None = None
    boolean_value: bool | None = None
    unit: str | None = None


@dataclass(frozen=True)
class StockObservation:
    sku_id: int
    sellable_stock: int | None
    source_version: int
    observed_at: datetime


@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    next_cursor: str | None


T = TypeVar("T")


def _one(connection, statement, params, record: type[T]) -> T | None:
    with connection.cursor(row_factory=class_row(record)) as cursor:
        cursor.execute(statement, params)
        return cursor.fetchone()


def _page(connection, statement, record: type[T], scope: str, key: str,
          limit: int, cursor: str | None) -> Page[T]:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("page limit must be an integer from 1 to 500")
    after_id = 0
    if cursor is not None:
        prefix = f"v1:{scope}:"
        if not isinstance(cursor, str) or not cursor.startswith(prefix):
            raise ValueError("invalid cursor for collection")
        value = cursor[len(prefix):]
        if (not value.isascii() or not value.isdecimal() or len(value) > 19
                or value.startswith("0") or int(value) > 2**63 - 1):
            raise ValueError("invalid cursor ID")
        after_id = int(value)
    with connection.cursor(row_factory=class_row(record)) as query:
        query.execute(statement, (after_id, limit + 1))
        rows = query.fetchall()
    items = tuple(rows[:limit])
    next_cursor = (
        f"v1:{scope}:{getattr(items[-1], key)}" if len(rows) > limit else None
    )
    return Page(items, next_cursor)


class _Repository:
    def __init__(self, connection: psycopg.Connection) -> None:
        if connection.autocommit:
            raise ValueError("repositories require a caller-managed transaction")
        self.connection = connection


class CatalogRepository(_Repository):
    def upsert_category(self, code: str, name: str) -> Category:
        return _one(self.connection, """
            INSERT INTO categories (code, name) VALUES (%s, %s)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id, code, name
        """, (code, name), Category)

    def get_category(self, category_id: int) -> Category | None:
        return _one(self.connection,
                    "SELECT id, code, name FROM categories WHERE id = %s",
                    (category_id,), Category)

    def list_categories(self, *, limit: int = 100, cursor: str | None = None) -> Page[Category]:
        return _page(self.connection, """
            SELECT id, code, name FROM categories WHERE id > %s ORDER BY id LIMIT %s
        """, Category, "categories", "id", limit, cursor)

    def upsert_sku(self, sku: str, name: str, category_id: int | None = None) -> Sku:
        return _one(self.connection, """
            INSERT INTO skus (sku, name, category_id) VALUES (%s, %s, %s)
            ON CONFLICT (sku) DO UPDATE SET
                name = EXCLUDED.name, category_id = EXCLUDED.category_id
            RETURNING id, sku, name, category_id
        """, (sku, name, category_id), Sku)

    def get_sku(self, sku: str) -> Sku | None:
        return _one(self.connection,
                    "SELECT id, sku, name, category_id FROM skus WHERE sku = %s",
                    (sku,), Sku)

    def list_skus(self, *, limit: int = 100, cursor: str | None = None) -> Page[Sku]:
        return _page(self.connection, """
            SELECT id, sku, name, category_id FROM skus
            WHERE id > %s ORDER BY id LIMIT %s
        """, Sku, "skus", "id", limit, cursor)

    def upsert_attribute(self, attribute: HardwareAttribute) -> HardwareAttribute:
        return _one(self.connection, """
            INSERT INTO hardware_attributes
                (sku_id, name, value_kind, text_value, number_value, boolean_value, unit)
            VALUES (%(sku_id)s, %(name)s, %(value_kind)s, %(text_value)s,
                    %(number_value)s, %(boolean_value)s, %(unit)s)
            ON CONFLICT (sku_id, name) DO UPDATE SET
                value_kind = EXCLUDED.value_kind, text_value = EXCLUDED.text_value,
                number_value = EXCLUDED.number_value, boolean_value = EXCLUDED.boolean_value,
                unit = EXCLUDED.unit
            RETURNING sku_id, name, value_kind, text_value, number_value, boolean_value, unit
        """, asdict(attribute), HardwareAttribute)

    def get_attributes(self, sku_id: int) -> tuple[HardwareAttribute, ...]:
        with self.connection.cursor(row_factory=class_row(HardwareAttribute)) as cursor:
            cursor.execute("""
                SELECT sku_id, name, value_kind, text_value, number_value, boolean_value, unit
                FROM hardware_attributes WHERE sku_id = %s ORDER BY name COLLATE "C"
            """, (sku_id,))
            return tuple(cursor.fetchall())


class StockRepository(_Repository):
    def upsert(self, observation: StockObservation) -> StockObservation:
        if observation.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return _one(self.connection, """
            INSERT INTO inventory (sku_id, sellable_stock, source_version, observed_at)
            VALUES (%(sku_id)s, %(sellable_stock)s, %(source_version)s, %(observed_at)s)
            ON CONFLICT (sku_id) DO UPDATE SET
                sellable_stock = EXCLUDED.sellable_stock,
                source_version = EXCLUDED.source_version, observed_at = EXCLUDED.observed_at
            RETURNING sku_id, sellable_stock, source_version, observed_at
        """, asdict(observation), StockObservation)

    def get(self, sku_id: int) -> StockObservation | None:
        return _one(self.connection, """
            SELECT sku_id, sellable_stock, source_version, observed_at
            FROM inventory WHERE sku_id = %s
        """, (sku_id,), StockObservation)

    def list_stock(self, *, limit: int = 100, cursor: str | None = None) -> Page[StockObservation]:
        return _page(self.connection, """
            SELECT sku_id, sellable_stock, source_version, observed_at
            FROM inventory WHERE sku_id > %s ORDER BY sku_id LIMIT %s
        """, StockObservation, "stock", "sku_id", limit, cursor)
