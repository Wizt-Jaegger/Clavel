"""Synthetic verified telemetry/coverage only; no live sales or provider evidence."""

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from itertools import permutations
import json
from uuid import UUID

import pytest

from clavel.database.recommendation_repository import RecommendationEvent
from clavel.intelligence.clustering.features import EVENT_TYPES, FeaturePolicy, HistoryCoverage
from clavel.intelligence.clustering.snapshots import extract_snapshot


CUTOFF = datetime(2026, 4, 1, tzinfo=timezone.utc)
POLICY = FeaturePolicy()


def synthetic_event(number, kind="purchase", *, customer_id=1, sku_id=11, **changes):
    occurred = CUTOFF - timedelta(days=1)
    return replace(RecommendationEvent(
        UUID(int=number), UUID(int=100), sku_id, customer_id, kind,
        occurred, occurred + timedelta(seconds=1),
    ), **changes)


def synthetic_coverage(customer_id=1, *, cutoff=CUTOFF, policy=POLICY):
    return HistoryCoverage(customer_id, cutoff - policy.lookback, cutoff,
                           frozenset(EVENT_TYPES))


def snapshot(events=(), **changes):
    args = dict(customer_ids=[1], cutoff=CUTOFF, coverage=[synthetic_coverage()])
    return extract_snapshot(events, **(args | changes))


def test_identical_snapshots_and_serialized_order_across_input_permutations():
    rows = [synthetic_event(1, sku_id=22), synthetic_event(2, sku_id=11),
            synthetic_event(3, "return", customer_id=2)]
    coverage = [synthetic_coverage(2), synthetic_coverage(1)]
    expected = snapshot(rows, customer_ids=[2, 1], coverage=coverage)
    serialized = json.dumps(asdict(expected), default=str)
    for shuffled in permutations(rows):
        actual = snapshot(iter(shuffled), customer_ids=iter([1, 2, 1]),
                          coverage=iter(reversed(coverage)))
        assert actual == expected
        assert json.dumps(asdict(actual), default=str) == serialized
    assert [row.customer_id for row in expected.rows] == [1, 2]
    assert list(expected.rows[0].product_affinities["purchase"]) == [11, 22]
    assert expected.rows[0].frequency["purchase"] == 2
    assert expected.rows[1].frequency["return"] == 1


@pytest.mark.parametrize("kind", ["purchase", "return"])
@pytest.mark.parametrize("boundary", [timedelta(0), timedelta(microseconds=1)])
@pytest.mark.parametrize("clock", ["occurred_at", "recorded_at"])
def test_future_sales_and_returns_cannot_change_past_snapshot(kind, boundary, clock):
    past = synthetic_event(1, kind)
    future = synthetic_event(2, kind, **{clock: CUTOFF + boundary})
    before = snapshot([past])
    assert snapshot([past, future]) == before
    assert snapshot([future, past]) == before
    assert before.rows[0].frequency[kind] == 1


def test_future_return_does_not_erase_purchase_and_appears_only_after_cutoff():
    sale = synthetic_event(1)
    returned = synthetic_event(2, "return", occurred_at=CUTOFF,
                               recorded_at=CUTOFF + timedelta(seconds=1))
    earlier = snapshot([sale, returned])
    later_cutoff = CUTOFF + timedelta(days=1)
    later = snapshot([sale, returned], cutoff=later_cutoff,
                     coverage=[synthetic_coverage(cutoff=later_cutoff)])
    assert earlier.rows[0].frequency["purchase"] == 1
    assert earlier.rows[0].frequency["return"] == 0
    assert later.rows[0].frequency["purchase"] == 1
    assert later.rows[0].frequency["return"] == 1
    assert earlier == snapshot([sale])


def test_missing_partial_and_empty_coverage_remain_distinct_and_subjects_isolated():
    rows = [synthetic_event(1, customer_id=99), synthetic_event(2, customer_id=2)]
    partial = replace(synthetic_coverage(2), event_types=frozenset({"click"}))
    result = snapshot(rows, customer_ids=[3, 2, 1],
                      coverage=[synthetic_coverage(1), partial])
    known, partial_row, unknown = result.rows
    assert known.frequency["purchase"] == 0
    assert partial_row.frequency["purchase"] is None
    assert partial_row.frequency["click"] == 0
    assert all(value is None for value in unknown.frequency.values())
    assert (known.cold_start, partial_row.cold_start, unknown.cold_start) == (
        "insufficient", "unknown", "unknown",
    )


def test_custom_window_and_timezone_normalization_apply_to_every_row():
    policy = FeaturePolicy(lookback=timedelta(days=1), min_interactions=1, min_active_days=1)
    zone = timezone(timedelta(hours=-6))
    rows = [synthetic_event(1), synthetic_event(2, occurred_at=(
        CUTOFF - policy.lookback - timedelta(microseconds=1)))]
    result = snapshot(rows, cutoff=CUTOFF.astimezone(zone), policy=policy,
                      coverage=[synthetic_coverage(policy=policy)])
    assert result.cutoff.tzinfo == timezone.utc
    assert result.policy == policy
    assert result.rows[0].window_start == CUTOFF - policy.lookback
    assert result.rows[0].frequency["purchase"] == 1
    assert result.rows[0].cold_start == "sufficient"


def test_retries_conflicts_and_late_conflicts_follow_existing_event_contract():
    row = synthetic_event(1)
    assert snapshot([row, row]) == snapshot([row])
    assert snapshot(coverage=[synthetic_coverage()] * 2) == snapshot()
    changed = replace(row, sku_id=22)
    with pytest.raises(ValueError, match="conflicting event UUID"):
        snapshot([row, changed])
    assert snapshot([row, replace(changed, recorded_at=CUTOFF)]) == snapshot([row])


def test_conflicting_or_unrequested_coverage_fails_closed():
    with pytest.raises(ValueError, match="conflicting customer coverage"):
        snapshot(coverage=[synthetic_coverage(), replace(
            synthetic_coverage(), event_types=frozenset({"click"}))])
    with pytest.raises(ValueError, match="unrequested customer"):
        snapshot(coverage=[synthetic_coverage(2)])


@pytest.mark.parametrize("customer_id", [True, 0, -1, "1"])
def test_invalid_requested_customer_ids_fail(customer_id):
    with pytest.raises(ValueError, match="positive integers"):
        snapshot(customer_ids=[customer_id])


def test_invalid_cutoff_fails_even_for_empty_cohort():
    with pytest.raises(ValueError, match="timezone-aware"):
        snapshot(customer_ids=[], coverage=[], cutoff=CUTOFF.replace(tzinfo=None))
    assert snapshot(customer_ids=[], coverage=[]).rows == ()


def test_materialized_snapshot_does_not_retain_caller_owned_collections():
    rows = [synthetic_event(1)]
    customers = [1]
    coverage = [synthetic_coverage()]
    result = snapshot(rows, customer_ids=customers, coverage=coverage)
    rows.clear()
    customers.clear()
    coverage.clear()
    assert result == snapshot([synthetic_event(1)])
