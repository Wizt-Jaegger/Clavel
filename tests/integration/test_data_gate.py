"""P0022: execute the documented seed/reset on real, disposable PostgreSQL.

All records are invented P0021 fixtures; this proves mechanics, never live data.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg

from tests.integration.test_migrations import HEAD, revisions, run_alembic, tables


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COUNTS = {
    "categories": 2, "skus": 12, "hardware_attributes": 12, "inventory": 11,
    "customers": 8, "sessions": 0, "sales_orders": 24, "sales_lines": 24,
    "sales_returns": 6, "recommendation_requests": 0,
    "recommendation_results": 0, "recommendation_events": 0,
}


def counts(url):
    with psycopg.connect(url) as connection:
        return {table: connection.execute(
            psycopg.sql.SQL("SELECT count(*) FROM {}").format(psycopg.sql.Identifier(table)),
        ).fetchone()[0] for table in EXPECTED_COUNTS}


def run_cli(url, *args):
    result = subprocess.run(
        [sys.executable, *map(str, args)], cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url, "APP_ENV": "test"},
        capture_output=True, text=True, timeout=30,
    )
    # Never expose environment-supplied connection data through tracebacks.
    assert result.returncode == 0, "documented seed/import command failed"
    assert result.stderr == "", "unexpected diagnostic outside safe report"
    return result.stdout


def assert_unknowns_and_cold_start(url):
    with psycopg.connect(url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM inventory WHERE sellable_stock IS NULL",
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM inventory WHERE sellable_stock = 0",
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM inventory WHERE sellable_stock > 0 "
            "AND observed_at = '2026-01-01T00:00:00Z'::timestamptz",
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM skus s LEFT JOIN inventory i ON i.sku_id = s.id "
            "WHERE i.sku_id IS NULL",
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM hardware_attributes WHERE value_kind = 'unknown' "
            "AND text_value IS NULL AND number_value IS NULL AND boolean_value IS NULL",
        ).fetchone() == (12,)
        assert connection.execute(
            "SELECT count(*) FILTER (WHERE unit_cost IS NULL), "
            "count(*) FILTER (WHERE unit_cost = 0) FROM sales_lines",
        ).fetchone() == (8, 8)
        assert connection.execute(
            "SELECT count(*) FROM sales_orders WHERE customer_id IS NULL",
        ).fetchone() == (8,)
        assert connection.execute(
            "SELECT count(*) FROM skus s WHERE NOT EXISTS "
            "(SELECT 1 FROM sales_lines l WHERE l.sku_id = s.id)",
        ).fetchone()[0] >= 1
        assert connection.execute(
            "SELECT subject_kind, count(*) FROM customers c WHERE NOT EXISTS "
            "(SELECT 1 FROM sales_orders o WHERE o.customer_id = c.id) "
            "GROUP BY subject_kind ORDER BY subject_kind",
        ).fetchall() == [("anonymous", 2), ("registered", 2)]


def test_documented_empty_database_seed_import_replay_and_reset(migration_database_url, tmp_path):
    url = migration_database_url
    assert tables(url) == []
    # Run the actual documentation block, not a separately maintained seed copy.
    document = (ROOT / "docs/DICCIONARIO_DATOS.md").read_text(encoding="utf-8")
    seed_code = document.split("```python\n", 1)[1].split("```", 1)[0]
    seed_script = tmp_path / "synthetic_seed.py"
    seed_script.write_text(seed_code, encoding="utf-8")

    for cycle in range(2):
        run_alembic(url, "upgrade", "head")
        assert revisions(url) == [(HEAD,)]
        assert {name for name, in tables(url)} == {*EXPECTED_COUNTS, "alembic_version"}
        assert set(counts(url).values()) == {0}

        directory = tmp_path / f"synthetic-cycle-{cycle}"
        directory.mkdir()
        bundle_path, batch_path = directory / "bundle.json", directory / "batch.jsonl"
        run_cli(url, ROOT / "scripts/generate_fixtures.py", "--seed", "21",
                "--output", bundle_path)
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert bundle["provenance"]["synthetic"] is True
        assert bundle["provenance"]["scope"] == "all nested records"
        run_cli(url, seed_script, bundle_path, batch_path)
        seeded = counts(url)
        assert seeded == {table: count if table not in {
            "sales_orders", "sales_lines", "sales_returns",
        } else 0 for table, count in EXPECTED_COUNTS.items()}

        for options, status in [(('--dry-run',), "dry_run"), ((), "imported"), ((), "imported")]:
            report = json.loads(run_cli(url, ROOT / "scripts/import_canonical.py",
                                        batch_path, *options))
            assert report["status"] == status
            assert report["row_count"] == report["processed_rows"] == 30
            assert len(report["diagnostics"]) == 8
            assert all(d["code"] == "unknown_cost" and d["severity"] == "warning"
                       for d in report["diagnostics"])
            assert counts(url) == (seeded if status == "dry_run" else EXPECTED_COUNTS)
        assert_unknowns_and_cold_start(url)

        run_alembic(url, "downgrade", "base")
        assert revisions(url) == []
        assert tables(url) == [("alembic_version",)]
