"""Synthetic identity mechanics on disposable PostgreSQL; no live linkage evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import psycopg
import pytest

from clavel.core.settings import Settings
from clavel.database import Database
from clavel.database.customer_sessions import (
    CustomerRepository, IdentityConflict, SessionRepository,
)
from tests.integration.test_migrations import run_alembic


OBSERVED = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def database(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    return Database(Settings(
        _env_file=None, app_env="test", database_url=migration_database_url,
    ))


def customer(connection, reference="synthetic-subject", kind="anonymous", when=OBSERVED):
    return CustomerRepository(connection).resolve_or_create(
        reference, subject_kind=kind, observed_at=when,
    )


@pytest.mark.parametrize("kind", ["anonymous", "registered"])
def test_repeated_resolution_and_reconnect_keep_identity(database, kind):
    with database.session() as connection:
        subject = customer(connection, kind=kind)
        repository = SessionRepository(connection)
        session = repository.resolve_or_create(
            "synthetic-session", observed_at=OBSERVED, customer_id=subject.id,
        )
        assert customer(connection, kind=kind) == subject
        assert repository.resolve_or_create(
            session.opaque_ref, observed_at=OBSERVED, customer_id=subject.id,
        ) == session
    with database.session() as connection:
        assert CustomerRepository(connection).resolve(subject.opaque_ref) == subject
        assert SessionRepository(connection).resolve(session.opaque_ref) == session
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (1,)


def test_unknown_lookups_have_no_side_effects(database):
    with database.session() as connection:
        assert CustomerRepository(connection).resolve("synthetic-unknown") is None
        assert SessionRepository(connection).resolve("synthetic-unknown") is None
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (0,)


def test_anonymous_sessions_and_subjects_remain_separate(database):
    with database.session() as connection:
        first = customer(connection, "synthetic-anonymous-1")
        second = customer(connection, "synthetic-anonymous-2")
        sessions = SessionRepository(connection)
        records = [sessions.resolve_or_create(ref, observed_at=OBSERVED, customer_id=owner)
                   for ref, owner in (("synthetic-one", first.id),
                                      ("synthetic-two", second.id),
                                      ("synthetic-three", first.id),
                                      ("synthetic-unlinked-one", None),
                                      ("synthetic-unlinked-two", None))]
        assert first.id != second.id
        assert len({row.id for row in records}) == 5
    with database.session() as connection:
        assert [SessionRepository(connection).resolve(row.opaque_ref).customer_id
                for row in records] == [first.id, second.id, first.id, None, None]
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)


@pytest.mark.parametrize("original_kind,new_kind", [
    ("anonymous", "registered"), ("registered", "anonymous"),
])
def test_kind_conflict_rolls_back_whole_transaction(database, original_kind, new_kind):
    with database.session() as connection:
        original = customer(connection, kind=original_kind)
    with pytest.raises(IdentityConflict):
        with database.session() as connection:
            customer(connection, "synthetic-must-roll-back")
            customer(connection, kind=new_kind, when=OBSERVED + timedelta(days=1))
    with database.session() as connection:
        repo = CustomerRepository(connection)
        assert repo.resolve(original.opaque_ref) == original
        assert repo.resolve("synthetic-must-roll-back") is None


@pytest.mark.parametrize("before,after", [(None, 0), (0, None), (0, 1), (0, 2)])
def test_no_implicit_link_unlink_reassignment_or_promotion(database, before, after):
    with database.session() as connection:
        owners = [customer(connection, "synthetic-anonymous-1").id,
                  customer(connection, "synthetic-anonymous-2").id,
                  customer(connection, "synthetic-registered", "registered").id]
        original = SessionRepository(connection).resolve_or_create(
            "synthetic-session", observed_at=OBSERVED,
            customer_id=None if before is None else owners[before],
        )
    with pytest.raises(IdentityConflict):
        with database.session() as connection:
            customer(connection, "synthetic-must-roll-back")
            SessionRepository(connection).resolve_or_create(
                original.opaque_ref, observed_at=OBSERVED + timedelta(days=1),
                customer_id=None if after is None else owners[after],
            )
    with database.session() as connection:
        assert SessionRepository(connection).resolve(original.opaque_ref) == original
        assert CustomerRepository(connection).resolve("synthetic-must-roll-back") is None


def test_unknown_customer_link_rejected_and_unit_of_work_rolled_back(database):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with database.session() as connection:
            customer(connection)
            SessionRepository(connection).resolve_or_create(
                "synthetic-orphan", observed_at=OBSERVED, customer_id=-1,
            )
    with database.session() as connection:
        assert CustomerRepository(connection).resolve("synthetic-subject") is None
        assert SessionRepository(connection).resolve("synthetic-orphan") is None


def test_activity_replay_offset_and_older_events_preserve_creation(database):
    later = OBSERVED + timedelta(hours=2)
    offset = timezone(timedelta(hours=-6))
    with database.session() as connection:
        original = customer(connection)
        repository = SessionRepository(connection)
        first_session = repository.resolve_or_create("synthetic-session", observed_at=OBSERVED)
        for observed_at in (later.astimezone(offset), OBSERVED - timedelta(days=1), later):
            subject = customer(connection, when=observed_at)
            session = repository.resolve_or_create("synthetic-session", observed_at=observed_at)
            assert subject.id == original.id and subject.created_at == OBSERVED
            assert session.id == first_session.id and session.started_at == OBSERVED
            assert subject.last_activity_at == session.last_activity_at == later


@pytest.mark.parametrize("reference", [None, "", " ", " synthetic", "synthetic ", "\tsynthetic"])
def test_invalid_references_fail_before_any_write(database, reference):
    with database.session() as connection:
        for repository in (CustomerRepository(connection), SessionRepository(connection)):
            with pytest.raises(ValueError):
                repository.resolve(reference)
            with pytest.raises(ValueError):
                if isinstance(repository, CustomerRepository):
                    repository.resolve_or_create(reference, subject_kind="anonymous", observed_at=OBSERVED)
                else:
                    repository.resolve_or_create(reference, observed_at=OBSERVED)
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (0,)


@pytest.mark.parametrize("kind", [None, "", "unknown", "Anonymous"])
def test_kind_must_be_explicit_not_inferred(database, kind):
    with database.session() as connection:
        with pytest.raises(ValueError):
            customer(connection, kind=kind)
        assert CustomerRepository(connection).resolve("synthetic-subject") is None


def test_naive_time_and_autocommit_rejected(database):
    with database.session() as connection:
        with pytest.raises(ValueError, match="timezone-aware"):
            customer(connection, when=OBSERVED.replace(tzinfo=None))
        with pytest.raises(ValueError, match="timezone-aware"):
            SessionRepository(connection).resolve_or_create(
                "synthetic-session", observed_at=OBSERVED.replace(tzinfo=None),
            )
        connection.autocommit = True
        for repository in (CustomerRepository, SessionRepository):
            with pytest.raises(ValueError, match="caller-managed"):
                repository(connection)


def test_references_are_exact_case_sensitive_parameterized_tokens(database):
    with database.session() as connection:
        refs = ["synthetic-token", "SYNTHETIC-token", "synthetic-'; SELECT 1;--"]
        subjects = [customer(connection, ref) for ref in refs]
        sessions = [SessionRepository(connection).resolve_or_create(ref, observed_at=OBSERVED)
                    for ref in refs]
        assert len({row.id for row in subjects}) == len({row.id for row in sessions}) == 3
        assert [CustomerRepository(connection).resolve(ref).opaque_ref for ref in refs] == refs
        assert [SessionRepository(connection).resolve(ref).opaque_ref for ref in refs] == refs


@pytest.mark.parametrize("conflicting_kind", [False, True])
def test_concurrent_customer_creation_is_atomic(database, conflicting_kind):
    barrier = Barrier(2)

    def resolve(kind):
        barrier.wait(timeout=10)
        try:
            with database.session() as connection:
                return customer(connection, kind=kind)
        except IdentityConflict:
            return None

    kinds = ("anonymous", "registered" if conflicting_kind else "anonymous")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(resolve, kinds))
    successful = [row for row in results if row is not None]
    assert len(successful) == (1 if conflicting_kind else 2)
    assert len({row.id for row in successful}) == 1
    with database.session() as connection:
        assert CustomerRepository(connection).resolve("synthetic-subject") == successful[0]
        assert connection.execute("SELECT count(*) FROM customers").fetchone() == (1,)


@pytest.mark.parametrize("conflicting_owner", [False, True])
def test_concurrent_session_creation_preserves_explicit_owner(database, conflicting_owner):
    with database.session() as connection:
        owner = customer(connection).id
    barrier = Barrier(2)

    def resolve(customer_id):
        barrier.wait(timeout=10)
        try:
            with database.session() as connection:
                return SessionRepository(connection).resolve_or_create(
                    "synthetic-session", observed_at=OBSERVED, customer_id=customer_id,
                )
        except IdentityConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(resolve, (None, owner if conflicting_owner else None)))
    successful = [row for row in results if row is not None]
    assert len(successful) == (1 if conflicting_owner else 2)
    assert len({row.id for row in successful}) == 1
    with database.session() as connection:
        assert SessionRepository(connection).resolve("synthetic-session") == successful[0]
        assert connection.execute("SELECT count(*) FROM sessions").fetchone() == (1,)
