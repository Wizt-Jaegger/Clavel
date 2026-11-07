"""Point-in-time telemetry features; no fitting, ranking or provider decisions.

Only explicitly verified repository events belong in this input. Coverage is an
external assertion about a complete snapshot, not inferred from event presence.
The baseline defaults are local definitions, not calibrated live thresholds.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from clavel.database.recommendation_repository import RecommendationEvent


EVENT_TYPES = ("exposure", "click", "add_to_cart", "purchase", "return")
POSITIVE_TYPES = ("click", "add_to_cart", "purchase")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("feature timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_id(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("IDs and evidence thresholds must be positive integers")


@dataclass(frozen=True)
class FeaturePolicy:
    lookback: timedelta = timedelta(days=90)
    min_interactions: int = 3
    min_active_days: int = 2

    def __post_init__(self):
        if self.lookback <= timedelta(0):
            raise ValueError("lookback must be positive")
        _positive_id(self.min_interactions)
        _positive_id(self.min_active_days)


@dataclass(frozen=True)
class HistoryCoverage:
    """Complete verified history known at cutoff, for these types and interval.

    Mere repository availability does not establish historical completeness.
    Do not assert this for an unverified live provider or partial extraction.
    """

    customer_id: int
    start: datetime
    end: datetime
    event_types: frozenset[str]

    def __post_init__(self):
        _positive_id(self.customer_id)
        if _utc(self.start) >= _utc(self.end):
            raise ValueError("coverage start must precede end")
        if not self.event_types <= frozenset(EVENT_TYPES):
            raise ValueError("unknown coverage event type")


@dataclass(frozen=True)
class BehavioralFeatures:
    customer_id: int
    cutoff: datetime
    window_start: datetime
    policy: FeaturePolicy
    frequency: dict[str, int | None]
    recency_days: dict[str, float | None]
    product_affinities: dict[str, dict[int, float] | None]
    interaction_count: int | None
    active_days: int | None
    cold_start: Literal["unknown", "insufficient", "sufficient"]
    definition_version: str = "behavioral-v1"


def build_features(
    events: Iterable[RecommendationEvent],
    *,
    customer_id: int,
    cutoff: datetime,
    coverage: HistoryCoverage | None = None,
    policy: FeaturePolicy = FeaturePolicy(),
) -> BehavioralFeatures:
    """Aggregate [cutoff-lookback, cutoff), with recorded_at strictly < cutoff.

    Exact UUID retries count once; conflicting UUID payloads fail. Other subjects
    never contribute. Incomplete types yield None, even if some rows are present.
    A known zero count has no recency or affinity denominator (both None).
    """
    _positive_id(customer_id)
    cutoff = _utc(cutoff)
    start = cutoff - policy.lookback
    complete = frozenset()
    if coverage is not None:
        if coverage.customer_id != customer_id:
            raise ValueError("coverage belongs to a different customer")
        if _utc(coverage.start) <= start and _utc(coverage.end) == cutoff:
            complete = coverage.event_types

    seen = {}
    buckets = {kind: [] for kind in EVENT_TYPES}
    for event in events:
        _positive_id(event.customer_id)
        if event.customer_id != customer_id:
            continue
        _positive_id(event.sku_id)
        if not isinstance(event.event_id, UUID) or not isinstance(event.request_id, UUID):
            raise ValueError("stable event and request UUIDs are required")
        if event.event_type not in buckets:
            raise ValueError("unknown event type")
        event = replace(event, occurred_at=_utc(event.occurred_at),
                        recorded_at=_utc(event.recorded_at))
        # Later arrivals were not visible in this snapshot and cannot alter it.
        if event.recorded_at >= cutoff:
            continue
        if event.event_id in seen:
            if seen[event.event_id] != event:
                raise ValueError("conflicting event UUID")
            continue
        seen[event.event_id] = event
        if start <= event.occurred_at < cutoff:
            buckets[event.event_type].append(event)

    frequency = {}
    recency = {}
    affinities = {}
    for kind, rows in buckets.items():
        frequency[kind] = len(rows) if kind in complete else None
        recency[kind] = None
        affinities[kind] = None
        if kind in complete and rows:
            recency[kind] = (cutoff - max(row.occurred_at for row in rows)) / timedelta(days=1)
            counts = {}
            for row in rows:
                counts[row.sku_id] = counts.get(row.sku_id, 0) + 1
            affinities[kind] = {sku: counts[sku] / len(rows) for sku in sorted(counts)}

    interactions = active_days = None
    cold_start = "unknown"
    if set(POSITIVE_TYPES) <= complete:
        positive = [row for kind in POSITIVE_TYPES for row in buckets[kind]]
        interactions = len(positive)
        active_days = len({row.occurred_at.date() for row in positive})
        cold_start = ("sufficient" if interactions >= policy.min_interactions
                      and active_days >= policy.min_active_days else "insufficient")
    return BehavioralFeatures(customer_id, cutoff, start, policy, frequency, recency,
                              affinities, interactions, active_days, cold_start)
