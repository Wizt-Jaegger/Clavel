"""Disposable real PostgreSQL with synthetic identities; no live linkage evidence."""

from datetime import datetime, timedelta, timezone

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from clavel.database.customers import customers, sessions
from clavel.database.telemetry import metadata
from tests.integration.test_migrations import HEAD, revisions, run_alembic, tables


ACTIVITY = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
PREVIOUS = "0003_inventory_schema"


@pytest.fixture
def subjects(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    return migration_database_url


def insert_customer(connection, **overrides):
    record = dict(opaque_ref="synthetic-anonymous-01", subject_kind="anonymous",
                  created_at=ACTIVITY, last_activity_at=ACTIVITY)
    record.update(overrides)
    return connection.execute(
        "INSERT INTO customers (opaque_ref, subject_kind, created_at, last_activity_at) "
        "VALUES (%(opaque_ref)s, %(subject_kind)s, %(created_at)s, %(last_activity_at)s) "
        "RETURNING id", record,
    ).fetchone()[0]


def insert_session(connection, **overrides):
    record = dict(opaque_ref="synthetic-session-01", customer_id=None,
                  started_at=ACTIVITY, last_activity_at=ACTIVITY)
    record.update(overrides)
    return connection.execute(
        "INSERT INTO sessions (opaque_ref, customer_id, started_at, last_activity_at) "
        "VALUES (%(opaque_ref)s, %(customer_id)s, %(started_at)s, %(last_activity_at)s) "
        "RETURNING id", record,
    ).fetchone()[0]


def test_anonymous_registered_and_unlinked_sessions_persist_after_reconnect(subjects):
    with psycopg.connect(subjects) as connection:
        anonymous = insert_customer(connection)
        registered = insert_customer(
            connection, opaque_ref="synthetic-registered-01", subject_kind="registered",
        )
        insert_session(connection, customer_id=anonymous)
        insert_session(connection, opaque_ref="synthetic-session-02", customer_id=anonymous)
        insert_session(connection, opaque_ref="synthetic-session-03", customer_id=registered)
        insert_session(connection, opaque_ref="synthetic-session-unresolved")
    with psycopg.connect(subjects) as connection:
        assert connection.execute(
            "SELECT id, subject_kind FROM customers ORDER BY id",
        ).fetchall() == [(anonymous, "anonymous"), (registered, "registered")]
        assert connection.execute(
            "SELECT customer_id FROM sessions ORDER BY id",
        ).fetchall() == [(anonymous,), (anonymous,), (registered,), (None,)]
        connection.execute("DELETE FROM sessions")
    # Anonymous subjects survive independently of session lifetime.
    with psycopg.connect(subjects) as connection:
        assert connection.execute(
            "SELECT id FROM customers WHERE subject_kind = 'anonymous'",
        ).fetchall() == [(anonymous,)]


@pytest.mark.parametrize("kind", ["anonymous", "registered"])
def test_customer_reference_unique_across_subject_kinds(subjects, kind):
    with psycopg.connect(subjects) as connection:
        insert_customer(connection)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(subjects) as connection:
            insert_customer(connection, subject_kind=kind)


def test_session_reference_unique_even_without_a_customer(subjects):
    with psycopg.connect(subjects) as connection:
        insert_session(connection)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(subjects) as connection:
            insert_session(connection)


@pytest.mark.parametrize("operation", ["insert", "update", "delete_customer"])
def test_invalid_links_and_linked_customer_deletion_rejected(subjects, operation):
    with psycopg.connect(subjects) as connection:
        customer_id = insert_customer(connection)
        session_id = insert_session(connection, customer_id=customer_id)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(subjects) as connection:
            if operation == "insert":
                insert_session(connection, opaque_ref="synthetic-orphan", customer_id=-1)
            elif operation == "update":
                connection.execute(
                    "UPDATE sessions SET customer_id = -1 WHERE id = %s", (session_id,),
                )
            else:
                connection.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
    with psycopg.connect(subjects) as connection:
        assert connection.execute(
            "SELECT customer_id FROM sessions WHERE id = %s", (session_id,),
        ).fetchone() == (customer_id,)


@pytest.mark.parametrize("entity", ["customer", "session"])
@pytest.mark.parametrize("reference,error", [
    (None, psycopg.errors.NotNullViolation),
    ("", psycopg.errors.CheckViolation),
    ("   ", psycopg.errors.CheckViolation),
    (" synthetic-padded ", psycopg.errors.CheckViolation),
])
def test_missing_or_malformed_opaque_references_rejected(subjects, entity, reference, error):
    insert = insert_customer if entity == "customer" else insert_session
    with pytest.raises(error):
        with psycopg.connect(subjects) as connection:
            insert(connection, opaque_ref=reference)


@pytest.mark.parametrize("kind,error", [
    (None, psycopg.errors.NotNullViolation),
    ("", psycopg.errors.CheckViolation),
    ("inferred", psycopg.errors.CheckViolation),
])
def test_missing_or_unsupported_subject_kind_rejected(subjects, kind, error):
    with pytest.raises(error):
        with psycopg.connect(subjects) as connection:
            insert_customer(connection, subject_kind=kind)


@pytest.mark.parametrize("entity", ["customer", "session"])
@pytest.mark.parametrize("field,value,error", [
    ("start", None, psycopg.errors.NotNullViolation),
    ("last_activity_at", None, psycopg.errors.NotNullViolation),
    ("start", "-infinity", psycopg.errors.CheckViolation),
    ("last_activity_at", "infinity", psycopg.errors.CheckViolation),
    ("last_activity_at", ACTIVITY - timedelta(seconds=1), psycopg.errors.CheckViolation),
])
def test_invalid_activity_rejected(subjects, entity, field, value, error):
    insert = insert_customer if entity == "customer" else insert_session
    if field == "start":
        field = "created_at" if entity == "customer" else "started_at"
    with pytest.raises(error):
        with psycopg.connect(subjects) as connection:
            insert(connection, **{field: value})


def test_metadata_and_utc_offset_round_trip(subjects):
    engine = sa.create_engine(make_url(subjects).set(drivername="postgresql+psycopg"))
    offset_time = ACTIVITY.astimezone(timezone(timedelta(hours=-6)))
    try:
        with engine.begin() as connection:
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
            connection.execute(sa.text("SET TIME ZONE 'UTC'"))
            customer_id = connection.execute(customers.insert().values(
                opaque_ref="synthetic-offset", subject_kind="anonymous",
                created_at=offset_time, last_activity_at=ACTIVITY,
            ).returning(customers.c.id)).scalar_one()
            connection.execute(sessions.insert().values(
                opaque_ref="synthetic-offset", customer_id=customer_id,
                started_at=offset_time, last_activity_at=ACTIVITY + timedelta(minutes=1),
            ))
        with engine.connect() as connection:
            connection.execute(sa.text("SET TIME ZONE 'UTC'"))
            customer = connection.execute(sa.select(customers)).one()
            session = connection.execute(sa.select(sessions)).one()
            assert customer.created_at == customer.last_activity_at == ACTIVITY
            assert session.started_at == ACTIVITY
            assert session.last_activity_at == ACTIVITY + timedelta(minutes=1)
            for value in (customer.created_at, customer.last_activity_at,
                          session.started_at, session.last_activity_at):
                assert value.utcoffset() == timedelta(0)
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_preserves_prior_data(subjects):
    with psycopg.connect(subjects) as connection:
        insert_customer(connection)
        insert_session(connection)
        sku_id = connection.execute(
            "INSERT INTO skus (sku, name) VALUES ('SYNTHETIC-P0010', 'Synthetic') RETURNING id",
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO inventory (sku_id, source_version, observed_at) VALUES (%s, 1, %s)",
            (sku_id, ACTIVITY),
        )
    run_alembic(subjects, "upgrade", "head")
    with psycopg.connect(subjects) as connection:
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (1,)
    run_alembic(subjects, "downgrade", PREVIOUS)
    assert revisions(subjects) == [(PREVIOUS,)]
    assert ("customers",) not in tables(subjects)
    assert ("sessions",) not in tables(subjects)
    with psycopg.connect(subjects) as connection:
        assert connection.execute("SELECT sku_id FROM inventory").fetchall() == [(sku_id,)]
    run_alembic(subjects, "upgrade", "head")
    assert revisions(subjects) == [(HEAD,)]
    with psycopg.connect(subjects) as connection:
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (0,)
        assert connection.execute("SELECT id FROM skus").fetchall() == [(sku_id,)]
