"""Replay-safe generation and explicit observations in caller-owned transactions.

Generation stores a complete, immutable response, including empty responses. It
never creates events. Each verified event has its own stable UUID and lifecycle;
an absent exposure/click/purchase is unknown, never inferred from another event.
Returns here are telemetry, not sales returns or accounting adjustments.

``verified=True`` is an assertion by a trusted caller that authenticated the
observation externally. This repository validates result/customer linkage, not
provider identity, consent, channel policy, stock, compatibility or attribution
windows. Do not pass a client-supplied verification flag through to this method.
No provider protocol or live trust policy is introduced by this persistence API.

Apply migrations first. Calls use savepoints, never commit the caller's work,
and leave no partial writes when a caller catches an error. Retry deadlocks or
serialization errors at the outer transaction boundary. Replays must match all
stored fields, including the original receipt timestamp for events.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from psycopg.pq import TransactionStatus
from psycopg.rows import class_row

from clavel.database.repositories import _one, _Repository


class RecommendationConflict(ValueError):
    """A stable UUID was reused with a different immutable payload."""


@dataclass(frozen=True)
class GeneratedItem:
    sku_id: int
    position: int
    generated_at: datetime


@dataclass(frozen=True)
class GeneratedRecommendation:
    request_id: UUID
    customer_id: int
    requested_at: datetime
    items: tuple[GeneratedItem, ...]
    session_id: int | None = None


@dataclass(frozen=True)
class RecommendationEvent:
    event_id: UUID
    request_id: UUID
    sku_id: int
    customer_id: int
    event_type: Literal["exposure", "click", "add_to_cart", "purchase", "return"]
    occurred_at: datetime
    recorded_at: datetime


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise ValueError("stable request and event UUIDs are required")


def _time(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("recommendation timestamps must be timezone-aware")


def _id(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("subject, session, SKU IDs and positions must be positive integers")


class RecommendationRepository(_Repository):
    def _savepoint(self):
        # On an idle connection transaction() would otherwise commit on exit.
        if self.connection.info.transaction_status == TransactionStatus.IDLE:
            self.connection.execute("SELECT 1")
        return self.connection.transaction()

    def get_generation(self, request_id: UUID) -> GeneratedRecommendation | None:
        _uuid(request_id)
        header = self.connection.execute("""
            SELECT customer_id, requested_at, session_id FROM recommendation_requests
            WHERE request_id = %s
        """, (request_id,)).fetchone()
        if header is None:
            return None
        with self.connection.cursor(row_factory=class_row(GeneratedItem)) as cursor:
            cursor.execute("""
                SELECT sku_id, position, generated_at FROM recommendation_results
                WHERE request_id = %s ORDER BY position
            """, (request_id,))
            items = tuple(cursor.fetchall())
        return GeneratedRecommendation(request_id, header[0], header[1], items, header[2])

    def record_generation(self, generation: GeneratedRecommendation) -> UUID:
        """Persist the whole response atomically; an exact replay is a no-op."""
        _uuid(generation.request_id)
        _id(generation.customer_id)
        _time(generation.requested_at)
        if generation.session_id is not None:
            _id(generation.session_id)
        items = tuple(generation.items)
        for item in items:
            _id(item.sku_id)
            _id(item.position)
            _time(item.generated_at)
        if (len({item.sku_id for item in items}) != len(items)
                or len({item.position for item in items}) != len(items)):
            raise ValueError("generated SKUs and positions must be distinct")
        canonical = GeneratedRecommendation(
            generation.request_id, generation.customer_id, generation.requested_at,
            tuple(sorted(items, key=lambda item: item.position)), generation.session_id,
        )
        with self._savepoint():
            inserted = self.connection.execute("""
                INSERT INTO recommendation_requests
                    (request_id, customer_id, requested_at, session_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING RETURNING request_id
            """, (canonical.request_id, canonical.customer_id,
                  canonical.requested_at, canonical.session_id)).fetchone()
            if inserted is None:
                self.connection.execute("""
                    SELECT request_id FROM recommendation_requests
                    WHERE request_id = %s FOR UPDATE
                """, (canonical.request_id,)).fetchone()
                if self.get_generation(canonical.request_id) != canonical:
                    raise RecommendationConflict("generation differs from the original response")
            else:
                for item in canonical.items:
                    self.connection.execute("""
                        INSERT INTO recommendation_results
                            (request_id, sku_id, customer_id, position, generated_at)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (canonical.request_id, item.sku_id, canonical.customer_id,
                          item.position, item.generated_at))
        return canonical.request_id

    def get_event(self, event_id: UUID) -> RecommendationEvent | None:
        _uuid(event_id)
        return _one(self.connection, """
            SELECT event_id, request_id, sku_id, customer_id, event_type, occurred_at, recorded_at
            FROM recommendation_events WHERE event_id = %s
        """, (event_id,), RecommendationEvent)

    def record_verified_event(self, event: RecommendationEvent, *, verified: bool) -> UUID:
        """Record only an explicitly verified observation; infer no other events."""
        if verified is not True:
            raise ValueError("event requires explicit verification by a trusted caller")
        _uuid(event.event_id)
        _uuid(event.request_id)
        _id(event.customer_id)
        _id(event.sku_id)
        _time(event.occurred_at)
        _time(event.recorded_at)
        if event.event_type not in ("exposure", "click", "add_to_cart", "purchase", "return"):
            raise ValueError("unsupported recommendation event type")
        with self._savepoint():
            inserted = self.connection.execute("""
                INSERT INTO recommendation_events
                    (event_id, request_id, sku_id, customer_id, event_type, occurred_at, recorded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING RETURNING event_id
            """, (event.event_id, event.request_id, event.sku_id, event.customer_id,
                  event.event_type, event.occurred_at, event.recorded_at)).fetchone()
            if inserted is None:
                self.connection.execute("""
                    SELECT event_id FROM recommendation_events WHERE event_id = %s FOR UPDATE
                """, (event.event_id,)).fetchone()
                if self.get_event(event.event_id) != event:
                    raise RecommendationConflict("event differs from the original observation")
        return event.event_id
