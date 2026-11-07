"""Synthetic P0018 mechanics on disposable PostgreSQL; no live provider evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest

from clavel.core.settings import Settings
from clavel.database import Database
from clavel.database.customer_sessions import CustomerRepository, SessionRepository
from clavel.database.recommendation_repository import (
    GeneratedItem, GeneratedRecommendation, RecommendationConflict,
    RecommendationEvent, RecommendationRepository,
)
from clavel.database.repositories import CatalogRepository
from tests.integration.test_migrations import HEAD, revisions, run_alembic


WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def recommendations(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    database = Database(Settings(
        _env_file=None, app_env="test", database_url=migration_database_url,
    ))
    with database.session() as connection:
        customers = [CustomerRepository(connection).resolve_or_create(
            f"synthetic-p0018-customer-{index}", subject_kind="anonymous", observed_at=WHEN,
        ).id for index in range(2)]
        sessions = [SessionRepository(connection).resolve_or_create(
            f"synthetic-p0018-session-{index}", customer_id=customer, observed_at=WHEN,
        ).id for index, customer in enumerate([*customers, None])]
        skus = [CatalogRepository(connection).upsert_sku(
            f"SYNTHETIC-P0018-{index}", "Synthetic recommendation item",
        ).id for index in range(3)]
    generation = GeneratedRecommendation(
        uuid4(), customers[0], WHEN,
        (GeneratedItem(skus[0], 1, WHEN), GeneratedItem(skus[1], 2, WHEN)), sessions[0],
    )
    observation = RecommendationEvent(
        uuid4(), generation.request_id, skus[0], customers[0],
        "exposure", WHEN, WHEN + timedelta(seconds=1),
    )
    return SimpleNamespace(
        database=database, url=migration_database_url, customers=customers, sessions=sessions,
        skus=skus, generation=generation, event=observation,
    )


def counts(connection):
    return tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                 for table in ("recommendation_requests", "recommendation_results",
                               "recommendation_events"))


def test_generation_replay_empty_response_and_zero_exposures(recommendations):
    t = recommendations
    empty = replace(t.generation, request_id=uuid4(), items=(), session_id=None)
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        assert repo.record_generation(t.generation) == t.generation.request_id
        repo.record_generation(empty)
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        offset = WHEN.astimezone(timezone(timedelta(hours=-6)))
        assert repo.record_generation(replace(
            t.generation, requested_at=offset, items=t.generation.items[::-1],
        )) == t.generation.request_id
        assert repo.record_generation(empty) == empty.request_id
        assert repo.get_generation(t.generation.request_id) == t.generation
        assert repo.get_generation(empty.request_id) == empty
        assert repo.get_generation(uuid4()) is None
        assert repo.get_event(uuid4()) is None
        assert counts(connection) == (2, 2, 0)


@pytest.mark.parametrize("kind", ["exposure", "click", "add_to_cart", "purchase", "return"])
def test_each_event_has_independent_lifecycle_and_exact_replay(recommendations, kind):
    t = recommendations
    event = replace(t.event, event_type=kind)
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        repo.record_generation(t.generation)
        assert repo.record_verified_event(event, verified=True) == event.event_id
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        assert repo.record_verified_event(event, verified=True) == event.event_id
        assert repo.get_event(event.event_id) == event
        assert counts(connection) == (1, 2, 1)
        # No exposure, purchase or intermediate state is manufactured.
        assert connection.execute(
            "SELECT event_type FROM recommendation_events",
        ).fetchall() == [(kind,)]
        repo.record_verified_event(replace(event, event_id=uuid4()), verified=True)
        assert counts(connection) == (1, 2, 2)


@pytest.mark.parametrize("change", ["customer", "session", "time", "sku", "position",
                                     "generated_at", "missing", "extra"])
def test_generation_replay_rejects_changes_without_overwriting(recommendations, change):
    t = recommendations
    changes = {
        "customer": {"customer_id": t.customers[1], "session_id": t.sessions[1]},
        "session": {"session_id": None},
        "time": {"requested_at": WHEN + timedelta(seconds=1)},
        "sku": {"items": (replace(t.generation.items[0], sku_id=t.skus[2]),)},
        "position": {"items": (replace(t.generation.items[0], position=3),)},
        "generated_at": {"items": (replace(t.generation.items[0],
                                           generated_at=WHEN + timedelta(seconds=1)),)},
        "missing": {"items": t.generation.items[:1]},
        "extra": {"items": (*t.generation.items, GeneratedItem(t.skus[2], 3, WHEN))},
    }[change]
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        repo.record_generation(t.generation)
        with pytest.raises(RecommendationConflict):
            repo.record_generation(replace(t.generation, **changes))
        assert repo.get_generation(t.generation.request_id) == t.generation
        assert counts(connection) == (1, 2, 0)


@pytest.mark.parametrize("field", ["request_id", "sku_id", "customer_id", "event_type",
                                    "occurred_at", "recorded_at"])
def test_event_replay_rejects_payload_changes_and_valid_retargeting(recommendations, field):
    t = recommendations
    other = replace(t.generation, request_id=uuid4(), customer_id=t.customers[1],
                    session_id=t.sessions[1])
    changes = {
        "request_id": {"request_id": other.request_id, "customer_id": t.customers[1]},
        "customer_id": {"request_id": other.request_id, "customer_id": t.customers[1]},
        "sku_id": {"sku_id": t.skus[1]}, "event_type": {"event_type": "purchase"},
        "occurred_at": {"occurred_at": WHEN + timedelta(seconds=1)},
        "recorded_at": {"recorded_at": WHEN + timedelta(seconds=2)},
    }[field]
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        repo.record_generation(t.generation)
        repo.record_generation(other)
        repo.record_verified_event(t.event, verified=True)
        with pytest.raises(RecommendationConflict):
            repo.record_verified_event(replace(t.event, **changes), verified=True)
        assert repo.get_event(t.event.event_id) == t.event
        assert counts(connection) == (2, 4, 1)


@pytest.mark.parametrize("changes", [
    {"customer_id": 999999}, {"request_id": uuid4()}, {"sku_id": 999999},
])
def test_forged_or_missing_event_linkage_is_rejected(recommendations, changes):
    t = recommendations
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        repo.record_generation(t.generation)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repo.record_verified_event(replace(t.event, **changes), verified=True)
        assert counts(connection) == (1, 2, 0)


def test_existing_wrong_customer_ungenerated_sku_and_empty_request_rejected(recommendations):
    t = recommendations
    empty = replace(t.generation, request_id=uuid4(), items=())
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        repo.record_generation(t.generation)
        repo.record_generation(empty)
        for changes in ({"customer_id": t.customers[1]}, {"sku_id": t.skus[2]},
                        {"request_id": empty.request_id}):
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                repo.record_verified_event(replace(t.event, **changes), verified=True)
        assert counts(connection) == (2, 2, 0)


@pytest.mark.parametrize("session_index", [1, 2])
def test_cross_subject_and_unresolved_session_rejected(recommendations, session_index):
    t = recommendations
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repo.record_generation(replace(t.generation, session_id=t.sessions[session_index]))
        assert counts(connection) == (0, 0, 0)


def test_partial_generation_failure_is_atomic_when_caught(recommendations):
    t = recommendations
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repo.record_generation(replace(t.generation, items=(
                t.generation.items[0], GeneratedItem(999999, 2, WHEN),
            )))
        assert counts(connection) == (0, 0, 0)
        repo.record_generation(t.generation)
    with t.database.session() as connection:
        assert counts(connection) == (1, 2, 0)


@pytest.mark.parametrize("operation", ["generation", "event"])
def test_repository_never_commits_callers_transaction(recommendations, operation):
    t = recommendations
    if operation == "event":
        with t.database.session() as connection:
            RecommendationRepository(connection).record_generation(t.generation)
    with pytest.raises(RuntimeError):
        with t.database.session() as connection:
            repo = RecommendationRepository(connection)
            if operation == "generation":
                repo.record_generation(t.generation)
            else:
                repo.record_verified_event(t.event, verified=True)
            raise RuntimeError("synthetic downstream failure")
    with t.database.session() as connection:
        assert counts(connection) == ((0, 0, 0) if operation == "generation" else (1, 2, 0))


@pytest.mark.parametrize("verified", [False, None, 1, "true"])
def test_unverified_or_unknown_observation_rejected(recommendations, verified):
    t = recommendations
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        repo.record_generation(t.generation)
        with pytest.raises(ValueError, match="verification"):
            repo.record_verified_event(t.event, verified=verified)
        assert counts(connection) == (1, 2, 0)


@pytest.mark.parametrize("entity,field,value", [
    ("generation", "request_id", None), ("generation", "customer_id", None),
    ("generation", "requested_at", WHEN.replace(tzinfo=None)),
    ("event", "event_id", None), ("event", "request_id", "synthetic-invalid"),
    ("event", "customer_id", None), ("event", "sku_id", None),
    ("event", "event_type", "generated"),
    ("event", "occurred_at", WHEN.replace(tzinfo=None)),
    ("event", "recorded_at", WHEN.replace(tzinfo=None)),
])
def test_unknown_ids_types_and_naive_timestamps_rejected(recommendations, entity, field, value):
    t = recommendations
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        with pytest.raises(ValueError):
            if entity == "generation":
                repo.record_generation(replace(t.generation, **{field: value}))
            else:
                repo.record_verified_event(replace(t.event, **{field: value}), verified=True)
        assert counts(connection) == (0, 0, 0)


@pytest.mark.parametrize("kind", ["generation_replay", "generation_conflict",
                                   "event_replay", "event_conflict"])
def test_concurrent_replay_or_conflict_has_one_immutable_winner(recommendations, kind):
    t = recommendations
    if kind.startswith("event"):
        with t.database.session() as connection:
            RecommendationRepository(connection).record_generation(t.generation)
    barrier = Barrier(2)

    def write(index):
        with t.database.session() as connection:
            repo = RecommendationRepository(connection)
            barrier.wait(timeout=10)
            try:
                if kind.startswith("generation"):
                    generation = (replace(t.generation, items=())
                                  if index and kind.endswith("conflict") else t.generation)
                    return "ok", repo.record_generation(generation)
                event = (replace(t.event, event_type="click")
                         if index and kind.endswith("conflict") else t.event)
                return "ok", repo.record_verified_event(event, verified=True)
            except RecommendationConflict:
                return "conflict", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, range(2)))
    if kind.endswith("conflict"):
        assert sorted(outcome for outcome, _ in results) == ["conflict", "ok"]
    else:
        assert results[0] == results[1]
    with t.database.session() as connection:
        requests, items, events = counts(connection)
        assert requests == 1
        if kind == "generation_conflict":
            assert items in (0, 2)
        else:
            assert items == 2
        assert events == int(kind.startswith("event"))


def test_return_migration_preserves_events_and_blocks_destructive_downgrade(recommendations):
    t = recommendations
    previous = "0006_recommendation_telemetry"
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        repo.record_generation(t.generation)
        repo.record_verified_event(t.event, verified=True)
    run_alembic(t.url, "downgrade", previous)
    assert revisions(t.url) == [(previous,)]
    run_alembic(t.url, "upgrade", "head")
    returned = replace(t.event, event_id=uuid4(), event_type="return")
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        assert repo.get_event(t.event.event_id) == t.event
        repo.record_verified_event(returned, verified=True)
    run_alembic(t.url, "downgrade", previous, succeeds=False, expected_error="CheckViolation")
    assert revisions(t.url) == [(HEAD,)]
    with t.database.session() as connection:
        repo = RecommendationRepository(connection)
        assert repo.get_event(returned.event_id) == returned
        assert counts(connection) == (1, 2, 2)
        # Failed DDL was transactional: the return-supporting constraint survived.
        repo.record_verified_event(replace(returned, event_id=uuid4()), verified=True)
