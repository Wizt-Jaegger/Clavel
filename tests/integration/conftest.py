"""Disposable PostgreSQL fixtures; synthetic role/data, never application settings."""

import os
import shlex
import shutil
import subprocess
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest


@pytest.fixture(scope="session")
def postgres_admin_url(tmp_path_factory):
    if url := os.environ.get("CLAVEL_MIGRATION_TEST_URL"):
        yield url
        return

    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl or os.geteuid() == 0:
        message = "migration checks need native PostgreSQL or CLAVEL_MIGRATION_TEST_URL"
        if os.environ.get("CLAVEL_REQUIRE_POSTGRES") == "1":
            pytest.fail(message)
        pytest.skip(message)

    root = tmp_path_factory.mktemp("p0009-postgres")
    data, sockets = root / "data", root / "socket"
    sockets.mkdir()
    subprocess.run(
        [initdb, "-D", str(data), "-U", "synthetic_p0009", "--auth=trust",
         "--no-locale", "--encoding=UTF8"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    try:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-l", str(root / "postgres.log"),
             "-o", shlex.join(["-h", "", "-k", str(sockets)]), "-w", "start"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        yield "postgresql://synthetic_p0009@localhost/postgres?" + urlencode(
            {"host": str(sockets)},
        )
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=True, capture_output=True, text=True, timeout=30,
        )


@pytest.fixture
def migration_database_url(postgres_admin_url):
    """Only create/drop our own unique database, including with a CI service."""
    name = "synthetic_p0009_" + uuid4().hex
    with psycopg.connect(postgres_admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        # Preserve escaped credentials and socket query options verbatim;
        # change only the database name, never the administrative connection.
        parts = urlsplit(postgres_admin_url)
        yield urlunsplit(parts._replace(path="/" + name))
    finally:
        with psycopg.connect(postgres_admin_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)),
            )
