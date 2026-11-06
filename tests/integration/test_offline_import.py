"""P0020 synthetic fixtures on disposable PostgreSQL, never live feed evidence."""

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg
import pytest

from clavel.core.settings import Settings
from clavel.data.offline_import import import_file
from clavel.database import Database
from clavel.database.customer_sessions import CustomerRepository
from clavel.database.repositories import CatalogRepository
from tests.integration.test_migrations import run_alembic


ROOT = Path(__file__).resolve().parents[2]


def sale(**changes):
    """Hand-authored canonical input, not derived from any provider dataset."""
    return {
        "contract_version": "v1", "record_type": "sale", "source_system": "synthetic-pos",
        "source_order_id": "synthetic-order", "source_line_id": "synthetic-line",
        "sku": "SYNTHETIC-SKU", "sold_at": "2026-01-01T06:00:00-06:00",
        "currency": " mxn ", "quantity": "10", "unit_price": "12.3456", **changes,
    }


def returned(**changes):
    return {
        "contract_version": "v1", "record_type": "return", "source_system": "synthetic-pos",
        "source_order_id": "synthetic-order", "source_line_id": "synthetic-refund-line",
        "source_return_id": "synthetic-refund", "sale_source_line_id": "synthetic-line",
        "quantity": "4", "returned_at": "2026-01-02T12:00:00Z", **changes,
    }


def write_batch(tmp_path, *rows):
    path = tmp_path / "synthetic.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.fixture
def database(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    db = Database(Settings(_env_file=None, app_env="test", database_url=migration_database_url))
    with db.session() as connection:
        CatalogRepository(connection).upsert_sku("SYNTHETIC-SKU", "Synthetic item")
        CustomerRepository(connection).resolve_or_create(
            "synthetic-customer", subject_kind="registered",
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    return db


def snapshot(database):
    with database.session() as connection:
        return tuple(connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                     for table in ("sales_orders", "sales_lines", "sales_returns"))


def cli(path, url, *options):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/import_canonical.py"), str(path), *options],
        cwd=ROOT, env={**os.environ, "DATABASE_URL": url, "APP_ENV": "test"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.stderr == "", "CLI leaked diagnostics outside its JSON report"
    return result.returncode, json.loads(result.stdout)


def test_cli_dry_run_import_replay_and_bad_row_on_postgres(database, migration_database_url, tmp_path):
    path = write_batch(tmp_path, returned(), sale(customer_ref="synthetic-customer"),
                       sale(source_line_id="synthetic-second", unit_cost="0",
                            customer_ref="synthetic-customer"))
    code, report = cli(path, migration_database_url, "--dry-run")
    assert code == 0 and report["status"] == "dry_run" and report["processed_rows"] == 3
    assert snapshot(database) == ([], [], [])
    code, report = cli(path, migration_database_url)
    assert code == 0 and report["status"] == "imported"
    original = snapshot(database)
    assert tuple(map(len, original)) == (1, 2, 1)
    assert original[0][0][3] is not None  # resolved customer_id
    assert [line[-1] for line in original[1]] == [None, Decimal("0")]
    # Normalized input and physical row ordering do not affect replay identity.
    write_batch(tmp_path, sale(source_line_id="synthetic-second", unit_cost="0",
                               customer_ref="synthetic-customer", currency="MXN"),
                sale(customer_ref="synthetic-customer", sold_at="2026-01-01T12:00:00Z"),
                returned())
    code, report = cli(path, migration_database_url)
    assert code == 0 and report["status"] == "imported"
    assert snapshot(database) == original
    write_batch(tmp_path, sale(source_order_id="synthetic-new"),
                sale(source_order_id="synthetic-newer", quantity="synthetic-private"))
    code, report = cli(path, migration_database_url)
    assert code == 1 and report["status"] == "rejected"
    assert report["diagnostics"][-1] == {
        "row_number": 2, "field": "quantity", "code": "invalid_value", "severity": "error",
    }
    assert "synthetic-private" not in json.dumps(report)
    assert snapshot(database) == original


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("failure,code", [
    ("sku", "unknown_sku"), ("customer", "unknown_customer"),
    ("sale", "unknown_sale"), ("over_return", "constraint_violation"),
])
def test_late_failure_rolls_back_earlier_order(database, tmp_path, dry_run, failure, code):
    bad = {
        "sku": sale(source_order_id="synthetic-z", sku="SYNTHETIC-MISSING"),
        "customer": sale(source_order_id="synthetic-z", customer_ref="synthetic-missing"),
        "sale": returned(source_order_id="synthetic-absent"),
        "over_return": returned(quantity="11"),
    }[failure]
    path = write_batch(tmp_path, sale(), bad)
    report = import_file(path, database, dry_run=dry_run)
    assert report.status == "rejected" and report.processed_rows == 0
    assert report.diagnostics[-1].row_number == 2 and report.diagnostics[-1].code == code
    assert snapshot(database) == ([], [], [])


@pytest.mark.parametrize("change", [
    {"quantity": "9"}, {"unit_cost": "0"}, {"currency": "USD"},
    {"customer_ref": "synthetic-customer"},
])
def test_conflicting_replay_rolls_back_other_new_orders(database, tmp_path, change):
    assert import_file(write_batch(tmp_path, sale()), database).status == "imported"
    original = snapshot(database)
    path = write_batch(tmp_path, sale(source_order_id="synthetic-a"), sale(**change))
    report = import_file(path, database)
    assert report.status == "rejected" and report.diagnostics[-1].code == "replay_conflict"
    assert snapshot(database) == original


def test_complete_order_replay_rejects_missing_or_extra_lines(database, tmp_path):
    first, second = sale(), sale(source_line_id="synthetic-second")
    assert import_file(write_batch(tmp_path, first, second), database).status == "imported"
    original = snapshot(database)
    for rows in ((first,), (first, second, sale(source_line_id="synthetic-third"))):
        report = import_file(write_batch(tmp_path, *rows), database)
        assert report.status == "rejected" and report.diagnostics[-1].code == "replay_conflict"
        assert snapshot(database) == original


def test_incremental_returns_replays_and_cumulative_limit(database, tmp_path):
    assert import_file(write_batch(tmp_path, sale()), database).status == "imported"
    refund = returned(quantity="10")
    for _ in range(2):
        assert import_file(write_batch(tmp_path, refund), database).status == "imported"
    original = snapshot(database)
    for row, code in ((returned(quantity="9"), "replay_conflict"),
                      (returned(source_return_id="synthetic-excess"), "constraint_violation"),
                      (returned(source_system="synthetic-other"), "unknown_sale")):
        report = import_file(write_batch(tmp_path, row), database)
        assert report.status == "rejected" and report.diagnostics[-1].code == code
        assert snapshot(database) == original


def test_source_namespaces_and_unknown_cost_customer_remain_distinct(database, tmp_path):
    rows = (sale(), sale(source_system="synthetic-other", unit_cost="0"))
    report = import_file(write_batch(tmp_path, *rows), database)
    assert report.status == "imported"
    orders, lines, _ = snapshot(database)
    assert len(orders) == 2 and all(order[3] is None for order in orders)
    assert {line[-1] for line in lines} == {None, Decimal("0")}
    with database.session() as connection:
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM inventory").fetchone() == (0,)


@pytest.mark.parametrize("rows,code", [
    ((sale(), sale()), "duplicate_line"),
    ((returned(), returned()), "duplicate_line"),
    ((sale(), sale(source_line_id="synthetic-second", currency="USD")), "header_conflict"),
    ((sale(), sale(source_line_id="synthetic-second", customer_ref="synthetic-customer")),
     "header_conflict"),
    ((sale(), sale(source_line_id="synthetic-second", sold_at="2026-01-02T12:00:00Z")),
     "header_conflict"),
])
def test_batch_assembly_rejections_without_database_access(tmp_path, rows, code):
    report = import_file(write_batch(tmp_path, *rows), object())
    assert report.status == "rejected" and report.diagnostics[-1].code == code
    assert report.diagnostics[-1].row_number == 2


@pytest.mark.parametrize("contents,code,number", [
    (b"", "empty_batch", 0), (b"\n", "invalid_json", 1),
    (b"{\n", "invalid_json", 1), (b"{}\nNaN\n", "invalid_json", 2),
    (b'{"synthetic-private":1,"synthetic-private":2}\n', "invalid_json", 1),
    (b"null\n", "invalid_row", 1), (b"\xff", "input_unavailable", 0),
])
def test_invalid_input_has_redacted_report_without_database_access(tmp_path, contents, code, number):
    path = tmp_path / "synthetic.jsonl"
    path.write_bytes(contents)
    report = import_file(path, object())
    assert report.status == "rejected"
    assert (report.diagnostics[-1].code, report.diagnostics[-1].row_number) == (code, number)
    assert "synthetic-private" not in json.dumps(asdict(report))


def test_json_numeric_tokens_preserve_exact_decimals(database, tmp_path):
    path = write_batch(tmp_path, sale())
    path.write_text(path.read_text().replace('"12.3456"', '12.3456'), encoding="utf-8")
    assert import_file(path, database).status == "imported"
    assert snapshot(database)[1][0][-2] == Decimal("12.3456")


@pytest.mark.parametrize("token", [
    "1e999999999999999999999999999", "-1e999999999999999999999999999",
    "1e-999999999999999999999999999", "-1e-999999999999999999999999999",
])
@pytest.mark.parametrize("options", [(), ("--dry-run",)])
def test_cli_out_of_range_numeric_exponent_is_redacted(
    database, migration_database_url, tmp_path, token, options,
):
    path = write_batch(tmp_path, sale(), sale(source_order_id="synthetic-private"))
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"12.3456"', token)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code, report = cli(path, migration_database_url, *options)
    assert code == 1 and report["status"] == "rejected"
    assert report["row_count"] == 2 and report["processed_rows"] == 0
    assert report["diagnostics"][-1] == {
        "row_number": 2, "field": "$row", "code": "invalid_json", "severity": "error",
    }
    assert token not in json.dumps(report)
    assert "synthetic-private" not in json.dumps(report)
    assert snapshot(database) == ([], [], [])


def test_missing_input_is_safe(tmp_path):
    report = import_file(tmp_path / "synthetic-missing.jsonl", object())
    assert report.status == "rejected" and report.diagnostics[-1].code == "input_unavailable"


def test_database_error_is_redacted_and_rolls_back(database, tmp_path, monkeypatch):
    from clavel.data import offline_import

    def fail(connection, orders, returns):
        connection.execute("INSERT INTO sales_orders "
                           "(source_system, source_order_id, sold_at, currency) "
                           "VALUES ('synthetic', 'synthetic', now(), 'MXN')")
        raise psycopg.OperationalError("synthetic-private-driver-message")

    monkeypatch.setattr(offline_import, "_persist", fail)
    report = import_file(write_batch(tmp_path, sale()), database)
    assert report.status == "unavailable" and report.diagnostics[-1].code == "database_unavailable"
    assert "synthetic-private" not in json.dumps(asdict(report))
    assert snapshot(database) == ([], [], [])


def test_cli_configuration_error_is_safe(tmp_path):
    code, report = cli(write_batch(tmp_path, sale()), "synthetic-private-invalid-url")
    assert code == 2 and report["diagnostics"][0]["code"] == "configuration_error"
    assert "synthetic-private" not in json.dumps(report)
