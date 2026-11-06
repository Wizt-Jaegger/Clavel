"""Resolve opaque identities in a caller-owned PostgreSQL transaction.

References are case-sensitive, trusted opaque tokens, never personal data.
Lookup never creates a subject or infers its kind. Explicit creation can attach
a new session to an existing customer; that ownership (including None) and the
customer's kind are immutable here. Anonymous promotion, merging and historical
attribution require a separately reviewed policy and are deliberately absent.
Let errors escape Database.session() to roll back the whole unit of work.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from clavel.database.repositories import _one, _Repository


class IdentityConflict(ValueError):
    """An existing opaque reference has different explicit identity information."""


@dataclass(frozen=True)
class Customer:
    id: int
    opaque_ref: str
    subject_kind: Literal["anonymous", "registered"]
    created_at: datetime
    last_activity_at: datetime


@dataclass(frozen=True)
class Session:
    id: int
    opaque_ref: str
    customer_id: int | None
    started_at: datetime
    last_activity_at: datetime


def _reference(opaque_ref: str) -> None:
    if not isinstance(opaque_ref, str) or not opaque_ref or opaque_ref.strip() != opaque_ref:
        raise ValueError("a nonempty opaque reference without outer whitespace is required")


def _activity(observed_at: datetime) -> None:
    if observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")


class CustomerRepository(_Repository):
    def resolve(self, opaque_ref: str) -> Customer | None:
        _reference(opaque_ref)
        return _one(self.connection, "SELECT * FROM customers WHERE opaque_ref = %s",
                    (opaque_ref,), Customer)

    def resolve_or_create(self, opaque_ref: str, *,
                          subject_kind: Literal["anonymous", "registered"],
                          observed_at: datetime) -> Customer:
        _reference(opaque_ref)
        _activity(observed_at)
        if subject_kind not in ("anonymous", "registered"):
            raise ValueError("subject_kind must be explicit: anonymous or registered")
        customer = _one(self.connection, """
            INSERT INTO customers (opaque_ref, subject_kind, created_at, last_activity_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (opaque_ref) DO UPDATE SET
                last_activity_at = GREATEST(customers.last_activity_at, EXCLUDED.last_activity_at)
            WHERE customers.subject_kind = EXCLUDED.subject_kind
            RETURNING *
        """, (opaque_ref, subject_kind, observed_at, observed_at), Customer)
        if customer is None:
            raise IdentityConflict("customer kind cannot change during resolution")
        return customer


class SessionRepository(_Repository):
    def resolve(self, opaque_ref: str) -> Session | None:
        _reference(opaque_ref)
        return _one(self.connection, "SELECT * FROM sessions WHERE opaque_ref = %s",
                    (opaque_ref,), Session)

    def resolve_or_create(self, opaque_ref: str, *, observed_at: datetime,
                          customer_id: int | None = None) -> Session:
        _reference(opaque_ref)
        _activity(observed_at)
        session = _one(self.connection, """
            INSERT INTO sessions (opaque_ref, customer_id, started_at, last_activity_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (opaque_ref) DO UPDATE SET
                last_activity_at = GREATEST(sessions.last_activity_at, EXCLUDED.last_activity_at)
            WHERE sessions.customer_id IS NOT DISTINCT FROM EXCLUDED.customer_id
            RETURNING *
        """, (opaque_ref, customer_id, observed_at, observed_at), Session)
        if session is None:
            raise IdentityConflict("session ownership cannot change during resolution")
        return session
