"""Offline canonical JSONL batches; no vendor mapping or HTTP contract changes."""

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal, DecimalException
import json
from pathlib import Path

import psycopg

from clavel.core.settings import ConfigurationError, load_settings
from clavel.data.import_validation import (
    RowDiagnostic, SaleRowV1, ValidatedRow, validate_rows,
)
from clavel.database import Database
from clavel.database.customer_sessions import CustomerRepository
from clavel.database.repositories import CatalogRepository
from clavel.database.sales_repository import (
    ReturnLine, SaleLine, SalesConflict, SalesRepository, UnknownSale,
)


@dataclass(frozen=True)
class ImportReport:
    status: str
    row_count: int
    processed_rows: int
    diagnostics: tuple[RowDiagnostic, ...]


class _Rejected(Exception):
    def __init__(self, diagnostics):
        self.diagnostics = tuple(diagnostics)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON number")


def _read(path):
    """Keep physical line numbers; reject blanks, duplicate keys and nonfinite JSON."""
    rows, diagnostics, count = [], [], 0
    try:
        with Path(path).open(encoding="utf-8") as stream:
            for count, line in enumerate(stream, 1):
                try:
                    raw = json.loads(line, parse_float=Decimal, parse_constant=_constant,
                                     object_pairs_hook=_object)
                except (ValueError, RecursionError, DecimalException):
                    diagnostics.append(RowDiagnostic(count, "$row", "invalid_json"))
                    continue
                result = validate_rows([raw])
                rows.extend(ValidatedRow(count, row.value) for row in result.rows)
                diagnostics.extend(RowDiagnostic(count, d.field, d.code, d.severity)
                                   for d in result.diagnostics)
    except (OSError, UnicodeError):
        diagnostics.append(RowDiagnostic(0, "$batch", "input_unavailable"))
    if count == 0 and not diagnostics:
        diagnostics.append(RowDiagnostic(0, "$batch", "empty_batch"))
    return rows, diagnostics, count


def _groups(rows):
    orders, returns, diagnostics = defaultdict(list), defaultdict(list), []
    seen = set()
    for row in rows:
        value = row.value
        if isinstance(value, SaleRowV1):
            key = ("sale", value.source_system, value.source_order_id, value.source_line_id)
            group = orders[value.source_system, value.source_order_id]
            if group:
                first = group[0].value
                if ((value.sold_at, value.currency, value.customer_ref)
                        != (first.sold_at, first.currency, first.customer_ref)):
                    diagnostics.append(RowDiagnostic(row.row_number, "$row", "header_conflict"))
        else:
            key = ("return", value.source_system, value.source_return_id, value.source_line_id)
            group = returns[value.source_system]
        if key in seen:
            diagnostics.append(RowDiagnostic(row.row_number, "source_line_id", "duplicate_line"))
        seen.add(key)
        group.append(row)
    if diagnostics:
        raise _Rejected(diagnostics)
    return orders, returns


def _persist(connection, orders, returns):
    catalog, customers = CatalogRepository(connection), CustomerRepository(connection)
    sales = SalesRepository(connection)
    # Stable group order also makes lock acquisition reproducible across reruns.
    for (source, order), group in sorted(orders.items()):
        lines, diagnostics = [], []
        first = group[0].value
        customer = customers.resolve(first.customer_ref) if first.customer_ref else None
        if first.customer_ref and customer is None:
            diagnostics.extend(RowDiagnostic(row.row_number, "customer_ref", "unknown_customer")
                               for row in group)
        for row in group:
            value = row.value
            sku = catalog.get_sku(value.sku)
            if sku is None:
                diagnostics.append(RowDiagnostic(row.row_number, "sku", "unknown_sku"))
            else:
                lines.append(SaleLine(value.source_line_id, sku.id, value.quantity,
                                      value.unit_price, value.unit_cost))
        if diagnostics:
            raise _Rejected(diagnostics)
        _write(group, lambda: sales.record_order(
            source, order, sold_at=first.sold_at, currency=first.currency,
            customer_id=customer.id if customer else None, lines=tuple(lines),
        ))
    for source, group in sorted(returns.items()):
        lines = tuple(ReturnLine(
            row.value.source_return_id, row.value.source_line_id, row.value.source_order_id,
            row.value.sale_source_line_id, row.value.quantity, row.value.returned_at,
        ) for row in group)
        _write(group, lambda: sales.record_returns(source, lines))


def _write(group, operation):
    try:
        operation()
    except (SalesConflict, UnknownSale, psycopg.IntegrityError) as exc:
        code = ("replay_conflict" if isinstance(exc, SalesConflict) else
                "unknown_sale" if isinstance(exc, UnknownSale) else "constraint_violation")
        # A repository group fails atomically. Report all its positions without
        # guessing the offending member or exposing SQL parameters/driver text.
        raise _Rejected(RowDiagnostic(row.row_number, "$row", code) for row in group) from None


def import_file(path, database: Database, *, dry_run: bool = False) -> ImportReport:
    """One file/transaction, including exact replays; errors roll back every group.

    A dry run performs the same writes/checks and explicitly rolls back. Database
    sequence values may advance, but no imported rows survive. Input must contain
    complete orders; no provider completeness or production authorization inferred.
    """
    rows, diagnostics, count = _read(path)
    if any(d.severity == "error" for d in diagnostics):
        return ImportReport("rejected", count, 0, tuple(diagnostics))
    try:
        orders, returns = _groups(rows)
        with database.session() as connection:
            _persist(connection, orders, returns)
            if dry_run:
                connection.rollback()
    except _Rejected as exc:
        return ImportReport("rejected", count, 0, tuple(diagnostics) + exc.diagnostics)
    except psycopg.Error:
        return ImportReport("unavailable", count, 0, tuple(diagnostics) + (
            RowDiagnostic(0, "$batch", "database_unavailable"),
        ))
    return ImportReport("dry_run" if dry_run else "imported", count, count, tuple(diagnostics))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import one atomic canonical v1 JSONL batch")
    parser.add_argument("input", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Check PostgreSQL then roll back")
    args = parser.parse_args(argv)
    try:
        # Explicit environment only: never silently import into a checkout's .env database.
        database = Database(load_settings(env_file=None))
    except ConfigurationError:
        report = ImportReport("unavailable", 0, 0, (
            RowDiagnostic(0, "$batch", "configuration_error"),
        ))
    else:
        report = import_file(args.input, database, dry_run=args.dry_run)
    print(json.dumps(asdict(report), sort_keys=True))
    return 0 if report.status in ("imported", "dry_run") else 1 if report.status == "rejected" else 2


if __name__ == "__main__":
    raise SystemExit(main())
