"""Immutable, replay-safe sales in caller-owned PostgreSQL transactions.

Apply migrations first. Each call uses a savepoint, so a failed multi-line write
leaves no partial rows even if the caller catches the error. Calls never commit
the caller's transaction; let errors escape Database.session() to undo the whole
unit of work. Retry serialization/deadlock failures at that transaction boundary.

Orders are complete snapshots: a replay must match the header and entire line
set, regardless of line ordering. Return batches may contain incremental lines;
each (source, return ID, return line ID) is immutable, including its sale link.
Source IDs are trusted opaque tokens, never raw personal data. Unknown customer
and cost remain None. Currency is inherited from the original order.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from psycopg.pq import TransactionStatus

from clavel.database.repositories import _Repository


class SalesConflict(ValueError):
    """A source identifier was replayed with a different immutable payload."""


class UnknownSale(ValueError):
    """A return references a sale line that has not been imported."""


@dataclass(frozen=True)
class SaleLine:
    source_line_id: str
    sku_id: int
    quantity: Decimal
    unit_price: Decimal
    unit_cost: Decimal | None = None


@dataclass(frozen=True)
class ReturnLine:
    source_return_id: str
    source_line_id: str
    source_order_id: str
    sale_source_line_id: str
    quantity: Decimal
    returned_at: datetime


def _reference(value: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("source references must be nonempty without outer whitespace")


def _time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("sale and return timestamps must be timezone-aware")


def _decimal(value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise ValueError("quantities and amounts require exact Decimal values")


class SalesRepository(_Repository):
    def _savepoint(self):
        # psycopg.transaction() on an idle connection would commit on exit.
        # Start the caller's transaction first so our context is always nested.
        if self.connection.info.transaction_status == TransactionStatus.IDLE:
            self.connection.execute("SELECT 1")
        return self.connection.transaction()

    def record_order(self, source_system: str, source_order_id: str, *,
                     sold_at: datetime, currency: str, lines: tuple[SaleLine, ...],
                     customer_id: int | None = None) -> int:
        """Return the stable order ID; reject changes or incomplete replays."""
        _reference(source_system)
        _reference(source_order_id)
        _time(sold_at)
        lines = tuple(lines)
        if not lines or len({line.source_line_id for line in lines}) != len(lines):
            raise ValueError("orders require a nonempty set of distinct source lines")
        for line in lines:
            _reference(line.source_line_id)
            _decimal(line.quantity)
            _decimal(line.unit_price)
            if line.unit_cost is not None:
                _decimal(line.unit_cost)
        expected = sorted((line.source_line_id, line.sku_id, line.quantity,
                           line.unit_price, line.unit_cost) for line in lines)
        with self._savepoint():
            inserted = self.connection.execute("""
                INSERT INTO sales_orders
                    (source_system, source_order_id, customer_id, sold_at, currency)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_system, source_order_id) DO NOTHING RETURNING id
            """, (source_system, source_order_id, customer_id, sold_at, currency)).fetchone()
            if inserted is None:
                existing = self.connection.execute("""
                    SELECT id, customer_id, sold_at, currency FROM sales_orders
                    WHERE source_system = %s AND source_order_id = %s FOR UPDATE
                """, (source_system, source_order_id)).fetchone()
                if existing is None or existing[1:] != (customer_id, sold_at, currency):
                    raise SalesConflict("order header differs from the original")
                order_id = existing[0]
                actual = self.connection.execute("""
                    SELECT source_line_id, sku_id, quantity, unit_price, unit_cost
                    FROM sales_lines WHERE order_id = %s
                """, (order_id,)).fetchall()
                if sorted(actual) != expected:
                    raise SalesConflict("order line set differs from the original")
            else:
                order_id = inserted[0]
                for reference, sku_id, quantity, price, cost in expected:
                    self.connection.execute("""
                        INSERT INTO sales_lines
                            (order_id, source_system, source_line_id, sku_id,
                             quantity, unit_price, unit_cost)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (order_id, source_system, reference, sku_id, quantity, price, cost))
        return order_id

    def record_returns(self, source_system: str, lines: tuple[ReturnLine, ...]) -> tuple[int, ...]:
        """Write a batch atomically; return stable IDs in supplied input order.

        Missing/cross-source sale references raise UnknownSale. Over-returns and
        invalid numeric values raise PostgreSQL constraint errors. Replays do not
        insert another return or consume the remaining returnable quantity.
        """
        _reference(source_system)
        lines = tuple(lines)
        keys = [(line.source_return_id, line.source_line_id) for line in lines]
        if not lines or len(set(keys)) != len(keys):
            raise ValueError("return batches require distinct source return/line pairs")
        for line in lines:
            for reference in (line.source_return_id, line.source_line_id,
                              line.source_order_id, line.sale_source_line_id):
                _reference(reference)
            _time(line.returned_at)
            _decimal(line.quantity)
        with self._savepoint():
            resolved = []
            for index, line in enumerate(lines):
                sale = self.connection.execute("""
                    SELECT l.id FROM sales_lines l JOIN sales_orders o ON o.id = l.order_id
                    WHERE o.source_system = %s AND o.source_order_id = %s
                        AND l.source_line_id = %s
                """, (source_system, line.source_order_id, line.sale_source_line_id)).fetchone()
                if sale is None:
                    raise UnknownSale("return requires an existing sale in the same source")
                resolved.append((sale[0], index, line))
            # Lock all parent lines in stable order before taking FK/return locks.
            # This also serializes cumulative totals with concurrent return batches.
            self.connection.execute("""
                SELECT id FROM sales_lines WHERE id = ANY(%s) ORDER BY id FOR NO KEY UPDATE
            """, ([sale_id for sale_id, _, _ in resolved],)).fetchall()
            result = [0] * len(lines)
            for sale_id, index, line in sorted(resolved, key=lambda item: item[:2]):
                inserted = self.connection.execute("""
                    INSERT INTO sales_returns
                        (source_system, source_return_id, source_line_id,
                         sale_line_id, quantity, returned_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_system, source_return_id, source_line_id)
                        DO NOTHING RETURNING id
                """, (source_system, line.source_return_id, line.source_line_id,
                      sale_id, line.quantity, line.returned_at)).fetchone()
                if inserted is None:
                    existing = self.connection.execute("""
                        SELECT id, sale_line_id, quantity, returned_at FROM sales_returns
                        WHERE source_system = %s AND source_return_id = %s
                            AND source_line_id = %s FOR UPDATE
                    """, (source_system, line.source_return_id, line.source_line_id)).fetchone()
                    if existing is None or existing[1:] != (sale_id, line.quantity, line.returned_at):
                        raise SalesConflict("return line differs from the original")
                    result[index] = existing[0]
                else:
                    result[index] = inserted[0]
        return tuple(result)
