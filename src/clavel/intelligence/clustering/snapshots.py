"""Deterministic, materialized snapshots of the behavioral-v1 feature definition.

Inputs are explicitly verified recommendation telemetry, including purchase and
return observations. Accounting sales/returns are separate: their current schema
has no receipt timestamp, so it cannot establish what was known at a past cutoff.
No accounting history or complete coverage is inferred from these inputs.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from clavel.database.recommendation_repository import RecommendationEvent
from clavel.intelligence.clustering.features import (
    BehavioralFeatures,
    FeaturePolicy,
    HistoryCoverage,
    _positive_id,
    _utc,
    build_features,
)


@dataclass(frozen=True)
class FeatureSnapshot:
    cutoff: datetime
    policy: FeaturePolicy
    rows: tuple[BehavioralFeatures, ...]


def extract_snapshot(
    events: Iterable[RecommendationEvent],
    *,
    customer_ids: Iterable[int],
    cutoff: datetime,
    coverage: Iterable[HistoryCoverage] = (),
    policy: FeaturePolicy = FeaturePolicy(),
) -> FeatureSnapshot:
    """Materialize one row per requested customer, ordered by customer ID.

    Both event occurrence and receipt must precede cutoff; the lookback includes
    its lower bound. Coverage must explicitly establish completeness at cutoff.
    Requested customers with no coverage retain unknown features, even if empty.
    Exact customer/coverage retries collapse; conflicting coverage fails closed.
    Iterables are consumed once and no caller-owned collection is retained.
    """
    cutoff = _utc(cutoff)
    grouped = {}
    for customer_id in customer_ids:
        _positive_id(customer_id)
        grouped.setdefault(customer_id, [])

    by_customer = {}
    for item in coverage:
        if item.customer_id not in grouped:
            raise ValueError("coverage belongs to an unrequested customer")
        previous = by_customer.setdefault(item.customer_id, item)
        if previous != item:
            raise ValueError("conflicting customer coverage")

    for event in events:
        _positive_id(event.customer_id)
        if event.customer_id in grouped:
            grouped[event.customer_id].append(event)

    rows = tuple(
        build_features(grouped[customer_id], customer_id=customer_id,
                       cutoff=cutoff, coverage=by_customer.get(customer_id),
                       policy=policy)
        for customer_id in sorted(grouped)
    )
    return FeatureSnapshot(cutoff, policy, rows)
