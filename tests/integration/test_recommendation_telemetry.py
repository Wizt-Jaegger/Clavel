"""Disposable PostgreSQL with synthetic subjects/SKUs; no live usage evidence."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import psycopg
from psycopg import sql
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from clavel.database.telemetry import (
    metadata, recommendation_events, recommendation_requests, recommendation_results,
)
from tests.integration.test_migrations import HEAD, revisions, run_alembic, tables


WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
PREVIOUS = "0005_sales_return_schema"


def insert(connection, table, **record):
    return connection.execute(sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) RETURNING *",
    ).format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, record)),
        sql.SQL(", ").join(sql.Placeholder() for _ in record),
    ), tuple(record.values())).fetchone()[0]


def request(connection, customer_id, **overrides):
    return insert(connection, "recommendation_requests", **{
        "request_id": uuid4(), "customer_id": customer_id,
        "requested_at": WHEN, **overrides,
    })


def result(connection, request_id, sku_id, customer_id, **overrides):
    return insert(connection, "recommendation_results", **{
        "request_id": request_id, "sku_id": sku_id, "customer_id": customer_id,
        "position": 1, "generated_at": WHEN, **overrides,
    })


def event(connection, request_id, sku_id, customer_id, **overrides):
    return insert(connection, "recommendation_events", **{
        "event_id": uuid4(), "request_id": request_id, "sku_id": sku_id,
        "customer_id": customer_id, "event_type": "exposure",
        "occurred_at": WHEN, "recorded_at": WHEN + timedelta(seconds=1), **overrides,
    })


@pytest.fixture
def telemetry(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    with psycopg.connect(migration_database_url) as connection:
        subjects = [insert(
            connection, "customers", opaque_ref=f"synthetic-p0014-{kind}",
            subject_kind=kind, created_at=WHEN, last_activity_at=WHEN,
        ) for kind in ("anonymous", "registered")]
        sessions = [insert(
            connection, "sessions", opaque_ref=f"synthetic-p0014-session-{number}",
            customer_id=subject, started_at=WHEN, last_activity_at=WHEN,
        ) for number, subject in enumerate([*subjects, None])]
        skus = [insert(connection, "skus", sku=f"SYNTHETIC-P0014-{number}",
                       name="Synthetic telemetry item") for number in (1, 2)]
        requests = [request(connection, subject, session_id=session)
                    for subject, session in zip(subjects, sessions)]
        for req, subject in zip(requests, subjects):
            result(connection, req, skus[0], subject)
        empty_request = request(connection, subjects[0])
    return SimpleNamespace(
        url=migration_database_url, customer=subjects[0], other_customer=subjects[1],
        session=sessions[0], other_session=sessions[1], unresolved_session=sessions[2],
        sku=skus[0], other_sku=skus[1], request=requests[0], other_request=requests[1],
        empty_request=empty_request,
    )


def test_generated_results_and_empty_responses_do_not_imply_exposure(telemetry):
    t = telemetry
    with psycopg.connect(t.url) as connection:
        assert connection.execute("SELECT count(*) FROM recommendation_requests").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM recommendation_results").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM recommendation_events").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM recommendation_results WHERE request_id = %s", (t.empty_request,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT session_id FROM recommendation_requests WHERE request_id = %s", (t.empty_request,),
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT customer_id FROM sessions WHERE id = %s", (t.unresolved_session,),
        ).fetchone() == (None,)
        result(connection, t.request, t.other_sku, t.customer, position=2)


def test_explicit_event_types_and_repeated_exposures_persist_independently(telemetry):
    t = telemetry
    kinds = ["exposure", "click", "add_to_cart", "purchase", "exposure"]
    with psycopg.connect(t.url) as connection:
        ids = [event(connection, t.request, t.sku, t.customer, event_type=kind) for kind in kinds]
    with psycopg.connect(t.url) as connection:
        assert len(set(ids)) == len(kinds)
        assert connection.execute(
            "SELECT event_type, count(*) FROM recommendation_events GROUP BY event_type ORDER BY event_type",
        ).fetchall() == [("add_to_cart", 1), ("click", 1), ("exposure", 2), ("purchase", 1)]
        # Downstream events can arrive without exposure telemetry; none is inferred.
        event(connection, t.other_request, t.sku, t.other_customer, event_type="purchase")
        assert connection.execute(
            "SELECT event_type FROM recommendation_events WHERE request_id = %s", (t.other_request,),
        ).fetchall() == [("purchase",)]


@pytest.mark.parametrize("relink", [False, True])
def test_event_id_replay_cannot_duplicate_or_retarget_observation(telemetry, relink):
    t = telemetry
    with psycopg.connect(t.url) as connection:
        event_id = event(connection, t.request, t.sku, t.customer)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(t.url) as connection:
            event(connection, t.other_request if relink else t.request, t.sku,
                  t.other_customer if relink else t.customer, event_id=event_id)
    with psycopg.connect(t.url) as connection:
        assert connection.execute(
            "SELECT request_id, customer_id FROM recommendation_events WHERE event_id = %s", (event_id,),
        ).fetchall() == [(t.request, t.customer)]


@pytest.mark.parametrize("entity,field,value,error", [
    ("request", "request_id", None, psycopg.errors.NotNullViolation),
    ("request", "request_id", "synthetic-invalid", psycopg.errors.InvalidTextRepresentation),
    ("event", "event_id", None, psycopg.errors.NotNullViolation),
    ("event", "event_id", "synthetic-invalid", psycopg.errors.InvalidTextRepresentation),
    ("result", "position", 0, psycopg.errors.CheckViolation),
    ("result", "position", -1, psycopg.errors.CheckViolation),
    ("result", "position", None, psycopg.errors.NotNullViolation),
    ("event", "event_type", "generated", psycopg.errors.CheckViolation),
    ("event", "event_type", "", psycopg.errors.CheckViolation),
    ("event", "event_type", "Exposure", psycopg.errors.CheckViolation),
    ("event", "event_type", None, psycopg.errors.NotNullViolation),
    ("request", "requested_at", "infinity", psycopg.errors.CheckViolation),
    ("request", "requested_at", None, psycopg.errors.NotNullViolation),
    ("result", "generated_at", "-infinity", psycopg.errors.CheckViolation),
    ("result", "generated_at", None, psycopg.errors.NotNullViolation),
    ("event", "occurred_at", "infinity", psycopg.errors.CheckViolation),
    ("event", "recorded_at", "-infinity", psycopg.errors.CheckViolation),
    ("event", "occurred_at", None, psycopg.errors.NotNullViolation),
    ("event", "recorded_at", None, psycopg.errors.NotNullViolation),
])
def test_invalid_identifiers_types_positions_and_times_rejected(telemetry, entity, field, value, error):
    t = telemetry
    with pytest.raises(error):
        with psycopg.connect(t.url) as connection:
            if entity == "request":
                request(connection, t.customer, **{field: value})
            elif entity == "result":
                result(connection, t.empty_request, t.sku, t.customer, **{field: value})
            else:
                event(connection, t.request, t.sku, t.customer, **{field: value})


@pytest.mark.parametrize("entity,field,attribute", [
    ("request", "customer_id", "missing"),
    ("request", "session_id", "other_session"),
    ("request", "session_id", "unresolved_session"),
    ("request", "session_id", "missing"),
    ("result", "customer_id", "other_customer"),
    ("result", "customer_id", "missing"),
    ("result", "request_id", "unknown_request"),
    ("result", "sku_id", "missing"),
    ("event", "customer_id", "other_customer"),
    ("event", "customer_id", "missing"),
    ("event", "request_id", "empty_request"),
    ("event", "request_id", "unknown_request"),
    ("event", "sku_id", "other_sku"),
    ("event", "sku_id", "missing"),
])
def test_orphan_cross_subject_and_ungenerated_item_references_rejected(telemetry, entity, field, attribute):
    t = telemetry
    value = {"missing": -1, "unknown_request": uuid4()}.get(attribute, getattr(t, attribute, None))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(t.url) as connection:
            if entity == "request":
                request(connection, **{"customer_id": t.customer, field: value})
            else:
                record = {"request_id": t.request, "sku_id": t.sku,
                          "customer_id": t.customer, field: value}
                # Use an otherwise unoccupied key for invalid generated results.
                if entity == "result" and field != "request_id":
                    record["request_id"] = t.empty_request
                (result if entity == "result" else event)(connection, **record)


@pytest.mark.parametrize("entity,field", [
    ("request", "customer_id"), ("result", "customer_id"), ("event", "customer_id"),
    ("result", "request_id"), ("event", "request_id"),
    ("result", "sku_id"), ("event", "sku_id"),
])
def test_null_cannot_bypass_subject_or_item_linkage(telemetry, entity, field):
    t = telemetry
    record = {"request_id": t.empty_request if entity == "result" else t.request,
              "sku_id": t.sku, "customer_id": t.customer, field: None}
    with pytest.raises(psycopg.errors.NotNullViolation):
        with psycopg.connect(t.url) as connection:
            if entity == "request":
                request(connection, None)
            else:
                (result if entity == "result" else event)(connection, **record)


@pytest.mark.parametrize("duplicate", ["request", "result_sku", "result_position"])
def test_request_ids_generated_skus_and_positions_are_unique(telemetry, duplicate):
    t = telemetry
    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(t.url) as connection:
            if duplicate == "request":
                request(connection, t.other_customer, request_id=t.request)
            elif duplicate == "result_sku":
                result(connection, t.request, t.sku, t.customer, position=2)
            else:
                result(connection, t.request, t.other_sku, t.customer)


@pytest.mark.parametrize("change", ["request_subject", "session_subject", "result_subject", "event_subject",
                                     "event_sku", "event_request"])
def test_updates_cannot_break_existing_attribution(telemetry, change):
    t = telemetry
    with psycopg.connect(t.url) as connection:
        event_id = event(connection, t.request, t.sku, t.customer)
    statements = {
        "request_subject": ("UPDATE recommendation_requests SET customer_id = %s, session_id = NULL WHERE request_id = %s",
                            (t.other_customer, t.request)),
        "session_subject": ("UPDATE sessions SET customer_id = %s WHERE id = %s", (t.other_customer, t.session)),
        "result_subject": ("UPDATE recommendation_results SET customer_id = %s WHERE request_id = %s",
                           (t.other_customer, t.request)),
        "event_subject": ("UPDATE recommendation_events SET customer_id = %s WHERE event_id = %s",
                          (t.other_customer, event_id)),
        "event_sku": ("UPDATE recommendation_events SET sku_id = %s WHERE event_id = %s", (t.other_sku, event_id)),
        "event_request": ("UPDATE recommendation_events SET request_id = %s WHERE event_id = %s",
                          (t.empty_request, event_id)),
    }
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(t.url) as connection:
            connection.execute(*statements[change])


@pytest.mark.parametrize("table,key,attribute", [
    ("recommendation_requests", "request_id", "request"),
    ("recommendation_results", "request_id", "request"),
    ("customers", "id", "customer"), ("sessions", "id", "session"), ("skus", "id", "sku"),
])
def test_deleting_referenced_records_is_rejected(telemetry, table, key, attribute):
    t = telemetry
    with psycopg.connect(t.url) as connection:
        event(connection, t.request, t.sku, t.customer)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with psycopg.connect(t.url) as connection:
            connection.execute(sql.SQL("DELETE FROM {} WHERE {} = %s").format(
                sql.Identifier(table), sql.Identifier(key),
            ), (getattr(t, attribute),))


def test_metadata_uuid_and_timezone_round_trip(telemetry):
    t = telemetry
    engine = sa.create_engine(make_url(t.url).set(drivername="postgresql+psycopg"))
    request_id, event_id = uuid4(), uuid4()
    offset_time = WHEN.astimezone(timezone(timedelta(hours=-6)))
    try:
        with engine.begin() as connection:
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
            connection.execute(recommendation_requests.insert().values(
                request_id=request_id, customer_id=t.customer, requested_at=offset_time,
            ))
            connection.execute(recommendation_results.insert().values(
                request_id=request_id, sku_id=t.sku, customer_id=t.customer,
                position=1, generated_at=offset_time,
            ))
            connection.execute(recommendation_events.insert().values(
                event_id=event_id, request_id=request_id, sku_id=t.sku,
                customer_id=t.customer, event_type="click", occurred_at=offset_time, recorded_at=WHEN,
            ))
        with engine.connect() as connection:
            connection.execute(sa.text("SET TIME ZONE 'UTC'"))
            record = connection.execute(sa.select(recommendation_events)).one()
            assert (record.event_id, record.request_id, record.sku_id, record.customer_id) == (
                event_id, request_id, t.sku, t.customer,
            )
            assert record.occurred_at == record.recorded_at == WHEN
            assert record.occurred_at.utcoffset() == timedelta(0)
            assert connection.execute(sa.select(recommendation_requests.c.requested_at).where(
                recommendation_requests.c.request_id == request_id,
            )).scalar_one() == WHEN
            assert connection.execute(sa.select(recommendation_results.c.generated_at).where(
                recommendation_results.c.request_id == request_id,
            )).scalar_one() == WHEN
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_preserves_prior_data(telemetry):
    t = telemetry
    with psycopg.connect(t.url) as connection:
        event(connection, t.request, t.sku, t.customer)
    run_alembic(t.url, "upgrade", "head")
    with psycopg.connect(t.url) as connection:
        assert connection.execute("SELECT count(*) FROM recommendation_events").fetchone() == (1,)
    run_alembic(t.url, "downgrade", PREVIOUS)
    assert revisions(t.url) == [(PREVIOUS,)]
    assert all((name,) not in tables(t.url) for name in (
        "recommendation_requests", "recommendation_results", "recommendation_events",
    ))
    with psycopg.connect(t.url) as connection:
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM skus").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM sales_orders").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'session_id_customer_unique'",
        ).fetchone() == (0,)
    run_alembic(t.url, "upgrade", "head")
    assert revisions(t.url) == [(HEAD,)]
    with psycopg.connect(t.url) as connection:
        assert connection.execute("SELECT count(*) FROM recommendation_requests").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)
