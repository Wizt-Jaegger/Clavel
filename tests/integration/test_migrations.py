"""Real PostgreSQL migration mechanics using only disposable synthetic data."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import psycopg


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "0001_migration_baseline"
HEAD = "0006_recommendation_telemetry"


def run_alembic(url, *args, config=None, succeeds=True, expected_error=None):
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(config or ROOT / "alembic.ini"),
         *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    # Do not echo driver failures: environment-supplied connection details may
    # be private even though these fixtures require synthetic infrastructure.
    returncode = result.returncode
    assert (returncode == 0) == succeeds, "unexpected Alembic command outcome"
    if expected_error:
        matches_expected_error = expected_error in result.stderr
        assert matches_expected_error, "expected migration failure missing"


def revisions(url):
    with psycopg.connect(url) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchall()


def tables(url):
    with psycopg.connect(url) as connection:
        return connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
        ).fetchall()


def test_empty_postgres_upgrade_downgrade_upgrade(migration_database_url):
    url = migration_database_url
    assert tables(url) == []
    run_alembic(url, "upgrade", BASELINE)
    assert revisions(url) == [(BASELINE,)]
    assert tables(url) == [("alembic_version",)]
    run_alembic(url, "upgrade", BASELINE)  # Already applied: no duplicate effects.
    assert revisions(url) == [(BASELINE,)]
    run_alembic(url, "downgrade", "base")
    assert revisions(url) == []
    run_alembic(url, "upgrade", BASELINE)
    assert revisions(url) == [(BASELINE,)]


def test_generated_revision_reverses_ddl_and_failed_upgrade_rolls_back(
    migration_database_url, tmp_path,
):
    url = migration_database_url
    # Generate from the actual project template, without changing repo history.
    directory = tmp_path / "migrations"
    shutil.copytree(ROOT / "migrations", directory)
    config = tmp_path / "alembic.ini"
    config.write_text(f"[alembic]\nscript_location = {directory}\n")
    run_alembic(url, "upgrade", "head", config=config)
    initial_tables = tables(url)
    run_alembic(
        url, "revision", "--rev-id", "synthetic_p0009", "-m", "synthetic mechanics",
        config=config,
    )
    revision = next((directory / "versions").glob("synthetic_p0009_*.py"))
    generated = revision.read_text()
    assert f"down_revision = '{HEAD}'" in generated
    revision.write_text(generated.replace(
        "    pass", "    op.execute('CREATE TABLE synthetic_probe (value integer)')\n"
        "    op.execute('INSERT INTO synthetic_probe VALUES (9)')", 1,
    ).replace("    pass", "    op.drop_table('synthetic_probe')", 1))

    run_alembic(url, "upgrade", "head", config=config)
    assert revisions(url) == [("synthetic_p0009",)]
    with psycopg.connect(url) as connection:
        assert connection.execute("SELECT value FROM synthetic_probe").fetchall() == [(9,)]
    run_alembic(url, "downgrade", "-1", config=config)
    assert revisions(url) == [(HEAD,)]
    assert tables(url) == initial_tables
    run_alembic(url, "upgrade", "head", config=config)
    assert revisions(url) == [("synthetic_p0009",)]

    # A second revision fails after DDL; both its table and version must roll back.
    (directory / "versions" / "synthetic_failure.py").write_text(
        '"""Synthetic failure injection; never a deployable project revision."""\n'
        "from alembic import op\n"
        "revision = 'synthetic_failure'\n"
        "down_revision = 'synthetic_p0009'\n"
        "def upgrade():\n"
        "    op.execute('CREATE TABLE synthetic_failed (value integer)')\n"
        "    op.execute('SELECT 1 / 0')\n"
        "def downgrade():\n"
        "    op.drop_table('synthetic_failed')\n",
    )
    run_alembic(
        url, "upgrade", "head", config=config, succeeds=False,
        expected_error="DivisionByZero",
    )
    assert revisions(url) == [("synthetic_p0009",)]
    assert tables(url) == sorted([*initial_tables, ("synthetic_probe",)])
    run_alembic(url, "downgrade", "base", config=config)
    assert revisions(url) == []
    assert tables(url) == [("alembic_version",)]
