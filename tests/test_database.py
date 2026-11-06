"""Synthetic doubles plus an ephemeral local PostgreSQL cluster, never production.

Native initdb/pg_ctl are optional for portable unit runs. A skipped integration
check is not evidence that connectivity or transaction behavior was verified.
"""

from concurrent.futures import ThreadPoolExecutor
import os
import shlex
import shutil
import subprocess
from threading import get_ident
from urllib.parse import urlencode
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
import pytest

from clavel.api.app import create_app
from clavel.core.settings import Settings
from clavel.database import Database


@pytest.fixture
def settings():
    return Settings(
        _env_file=None, app_env="test",
        database_url="postgresql://synthetic:synthetic_password@localhost/synthetic",
    )


def test_startup_and_liveness_never_connect(settings, monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("startup/liveness must not contact PostgreSQL")

    monkeypatch.setattr(psycopg, "connect", unexpected_connection)
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_readiness_recovers_and_redacts_driver_errors(settings, monkeypatch, caplog):
    attempts = []

    def unavailable(*args, **kwargs):
        attempts.append(kwargs)
        raise psycopg.OperationalError("synthetic_password private driver failure")

    monkeypatch.setattr(psycopg, "connect", unavailable)
    app = create_app(settings=settings)
    with TestClient(app) as client:
        for _ in range(2):
            response = client.get("/ready", headers={"X-Request-ID": "synthetic-ready-1"})
            assert response.status_code == 503
            assert response.json() == {
                "error": {"code": "database_unavailable", "message": "Database unavailable"},
                "request_id": "synthetic-ready-1",
            }
            assert response.headers["X-Request-ID"] == "synthetic-ready-1"
            assert "synthetic_password" not in response.text
        assert len(attempts) == 2  # Failures are rechecked, never cached as ready.
        assert attempts[0]["connect_timeout"] == 3
        assert attempts[0]["options"] == "-c statement_timeout=3000"
        assert client.get("/health").status_code == 200
        monkeypatch.setattr(app.state.database, "is_ready", lambda: True)
        assert client.get("/ready").json() == {"status": "ok"}
    assert "synthetic_password" not in caplog.text


def test_readiness_runs_outside_event_loop(settings, monkeypatch):
    app = create_app(settings=settings)
    with TestClient(app) as client:
        async def event_loop_thread():
            return {"thread": get_ident()}

        app.add_api_route("/synthetic-thread", event_loop_thread)
        event_thread = client.get("/synthetic-thread").json()["thread"]
        probe_threads = []

        def probe():
            probe_threads.append(get_ident())
            return True

        monkeypatch.setattr(app.state.database, "is_ready", probe)
        assert client.get("/ready").status_code == 200
        assert probe_threads[0] != event_thread


def test_readiness_runtime_schema(settings):
    schema = create_app(settings=settings).openapi()
    operation = schema["paths"]["/ready"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse",
    }
    assert operation["responses"]["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse",
    }
    assert "database_unavailable" in schema["components"]["schemas"]["ErrorCode"]["enum"]


@pytest.fixture(scope="module")
def postgres_settings(tmp_path_factory):
    """Actual local PostgreSQL; disposable cluster with synthetic role/data only."""
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl or os.geteuid() == 0:
        pytest.skip("local PostgreSQL integration needs initdb/pg_ctl and non-root user")
    root = tmp_path_factory.mktemp("p0008-postgres")
    data = root / "data"
    sockets = root / "socket"
    sockets.mkdir()
    subprocess.run(
        [initdb, "-D", str(data), "-U", "synthetic_p0008", "--auth=trust",
         "--no-locale", "--encoding=UTF8"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    try:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-l", str(root / "postgres.log"),
             "-o", shlex.join(["-h", "", "-k", str(sockets)]), "-w", "start"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        yield Settings(
            _env_file=None, app_env="test",
            database_url="postgresql://synthetic_p0008@localhost/postgres?"
            + urlencode({"host": str(sockets)}),
        )
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=True, capture_output=True, text=True, timeout=30,
        )


@pytest.fixture
def table(postgres_settings):
    database = Database(postgres_settings)
    name = sql.Identifier("synthetic_p0008_" + uuid4().hex)
    with database.session() as connection:
        connection.execute(sql.SQL("CREATE TABLE {} (value integer)").format(name))
    try:
        yield database, name
    finally:
        with database.session() as connection:
            connection.execute(sql.SQL("DROP TABLE {}").format(name))


def test_postgres_connectivity_readiness_and_close(postgres_settings):
    database = Database(postgres_settings)
    with database.session() as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
        assert connection.execute("SHOW statement_timeout").fetchone() == ("3s",)
    assert connection.closed
    assert database.is_ready()
    with TestClient(create_app(settings=postgres_settings)) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/health").status_code == 200


def test_postgres_commit_and_rollback(table):
    database, name = table
    insert = sql.SQL("INSERT INTO {} VALUES (%s)").format(name)
    select = sql.SQL("SELECT value FROM {} ORDER BY value").format(name)
    with database.session() as committed:
        committed.execute(insert, (1,))
    assert committed.closed
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with database.session() as rolled_back:
            rolled_back.execute(insert, (2,))
            raise RuntimeError("synthetic failure")
    assert rolled_back.closed
    with pytest.raises(psycopg.errors.DivisionByZero):
        with database.session() as failed_sql:
            failed_sql.execute(insert, (3,))
            failed_sql.execute("SELECT 1 / 0")
    assert failed_sql.closed
    with database.session() as connection:
        assert connection.execute(select).fetchall() == [(1,)]


def test_postgres_commit_failure_closes_and_rolls_back(table):
    database, name = table
    # A deferred constraint forces failure on context exit, after the body succeeds.
    with database.session() as connection:
        connection.execute(sql.SQL(
            "ALTER TABLE {} ADD UNIQUE (value) DEFERRABLE INITIALLY DEFERRED"
        ).format(name))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with database.session() as failed_commit:
            failed_commit.execute(sql.SQL("INSERT INTO {} VALUES (1), (1)").format(name))
    assert failed_commit.closed
    with database.session() as connection:
        assert connection.execute(sql.SQL("SELECT count(*) FROM {}").format(name)).fetchone() == (0,)


def test_postgres_concurrent_sessions_are_isolated(postgres_settings):
    database = Database(postgres_settings)
    with database.session() as outer:
        outer_pid = outer.info.backend_pid

        def other_session():
            with database.session() as inner:
                return inner.info.backend_pid

        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(other_session).result(timeout=5) != outer_pid
        assert outer.execute("SELECT 1").fetchone() == (1,)


def test_real_unavailable_postgres_is_not_ready(tmp_path):
    # A nonexistent Unix socket cannot accidentally contact an installed server.
    settings = Settings(
        _env_file=None, app_env="test",
        database_url="postgresql://synthetic_p0008@localhost/postgres?"
        + urlencode({"host": str(tmp_path / "missing")}),
    )
    database = Database(settings)
    with pytest.raises(psycopg.OperationalError):
        with database.session():
            pytest.fail("nonexistent server must be unreachable")
    assert not database.is_ready()
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200
