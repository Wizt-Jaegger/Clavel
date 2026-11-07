"""Invented telemetry and coverage; mechanics only, no live/representative evidence."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from clavel.database.recommendation_repository import RecommendationEvent
from clavel.intelligence.clustering.features import (
    EVENT_TYPES,
    FeaturePolicy,
    HistoryCoverage,
    build_features,
)


CUTOFF = datetime(2026, 4, 1, tzinfo=timezone.utc)
START = CUTOFF - timedelta(days=90)
COVERAGE = HistoryCoverage(1, START, CUTOFF, frozenset(EVENT_TYPES))


def event(number, kind="click", *, age=timedelta(days=1), sku=11, **changes):
    """A synthetic verified-event test double, not a provider observation."""
    occurred = CUTOFF - age
    row = RecommendationEvent(UUID(int=number), UUID(int=100), sku, 1, kind,
                              occurred, occurred + timedelta(seconds=1))
    return replace(row, **changes)


def features(rows=(), **kwargs):
    return build_features(rows, customer_id=1, cutoff=CUTOFF,
                          coverage=kwargs.pop("coverage", COVERAGE), **kwargs)


def test_documented_cutoff_example():
    # Same invented example as docs/DICCIONARIO_DATOS.md, P0023 section.
    rows = [
        event(1, age=timedelta(days=2)),
        event(2),
        event(3, sku=22),
        event(4, "purchase", age=timedelta(days=90), sku=22),
        event(5, "return", sku=22),
        event(6, "exposure", sku=33),
        event(7, age=timedelta(0), recorded_at=CUTOFF - timedelta(seconds=1)),
        event(8, recorded_at=CUTOFF),
        event(9, age=timedelta(days=90, microseconds=1)),
    ]
    result = features(rows + [rows[0]])
    assert result.definition_version == "behavioral-v1"
    assert result.frequency == {
        "exposure": 1, "click": 3, "add_to_cart": 0, "purchase": 1, "return": 1,
    }
    assert result.recency_days == {
        "exposure": 1, "click": 1, "add_to_cart": None, "purchase": 90, "return": 1,
    }
    assert result.product_affinities == {
        "exposure": {33: 1}, "click": {11: 2 / 3, 22: 1 / 3},
        "add_to_cart": None, "purchase": {22: 1}, "return": {22: 1},
    }
    assert (result.interaction_count, result.active_days, result.cold_start) == (4, 3, "sufficient")
    assert result.cutoff == CUTOFF and result.window_start == START


def test_missing_history_differs_from_observed_empty_history():
    missing = features(coverage=None)
    empty = features()
    assert all(value is None for value in missing.frequency.values())
    assert (missing.interaction_count, missing.active_days, missing.cold_start) == (None, None, "unknown")
    assert all(value == 0 for value in empty.frequency.values())
    assert (empty.interaction_count, empty.active_days, empty.cold_start) == (0, 0, "insufficient")
    for result in (missing, empty):
        assert all(value is None for value in result.recency_days.values())
        assert all(value is None for value in result.product_affinities.values())


def test_partial_types_preserve_unknown_even_when_rows_exist():
    result = features([event(1), event(2, "purchase")], coverage=replace(
        COVERAGE, event_types=frozenset({"click", "exposure"})))
    assert result.frequency["click"] == 1
    assert result.frequency["exposure"] == 0
    assert result.frequency["purchase"] is None
    assert result.product_affinities["purchase"] is None
    assert result.interaction_count is None
    assert result.cold_start == "unknown"


@pytest.mark.parametrize("changes", [
    {"start": START + timedelta(microseconds=1)},
    {"end": CUTOFF - timedelta(microseconds=1)},
    {"end": CUTOFF + timedelta(microseconds=1)},
])
def test_incomplete_or_different_snapshot_cannot_claim_zero(changes):
    assert features(coverage=replace(COVERAGE, **changes)).cold_start == "unknown"
    assert features(coverage=replace(COVERAGE, **changes)).frequency["click"] is None


def test_customer_isolation_and_no_automatic_anonymous_linking():
    assert features([event(1, customer_id=2)]).frequency["click"] == 0
    with pytest.raises(ValueError, match="different customer"):
        features(coverage=replace(COVERAGE, customer_id=2))


@pytest.mark.parametrize("age,recorded,included", [
    (timedelta(days=90), START, True),
    (timedelta(days=90, microseconds=1), START, False),
    (timedelta(microseconds=1), CUTOFF - timedelta(microseconds=1), True),
    (timedelta(0), CUTOFF - timedelta(seconds=1), False),
    (-timedelta(seconds=1), CUTOFF - timedelta(seconds=1), False),
    (timedelta(days=1), CUTOFF, False),
    (timedelta(days=1), CUTOFF + timedelta(seconds=1), False),
])
def test_occurrence_and_receipt_boundaries(age, recorded, included):
    result = features([event(1, age=age, recorded_at=recorded)])
    assert result.frequency["click"] == int(included)


def test_uuid_retries_are_idempotent_and_conflicts_fail():
    row = event(1)
    assert features([row, row]).frequency["click"] == 1
    with pytest.raises(ValueError, match="conflicting event UUID"):
        features([row, replace(row, sku_id=22)])
    # A later arrival must not contaminate the earlier snapshot or its validation.
    assert features([row, replace(row, sku_id=22, recorded_at=CUTOFF)]).frequency["click"] == 1


@pytest.mark.parametrize("rows,count,days,state", [
    ([event(1), event(2)], 2, 1, "insufficient"),
    ([event(1), event(2), event(3)], 3, 1, "insufficient"),
    ([event(1), event(2), event(3, "add_to_cart", age=timedelta(days=2))], 3, 2, "sufficient"),
    ([event(1, "exposure"), event(2, "return")], 0, 0, "insufficient"),
])
def test_cold_start_requires_both_evidence_thresholds(rows, count, days, state):
    result = features(rows)
    assert (result.interaction_count, result.active_days, result.cold_start) == (count, days, state)


def test_explicit_policy_changes_window_and_evidence_thresholds():
    policy = FeaturePolicy(timedelta(days=1), 1, 1)
    result = features([event(1), event(2, age=timedelta(days=2))], policy=policy)
    assert result.policy == policy
    assert result.window_start == CUTOFF - timedelta(days=1)
    assert (result.interaction_count, result.cold_start) == (1, "sufficient")


def test_unknown_exposure_and_return_do_not_block_positive_evidence():
    result = features([event(1), event(2), event(3, age=timedelta(days=2))],
                      coverage=replace(COVERAGE, event_types=frozenset({
                          "click", "add_to_cart", "purchase"})))
    assert result.cold_start == "sufficient"
    assert result.frequency["exposure"] is None
    assert result.frequency["return"] is None


def test_two_local_dates_on_one_utc_date_do_not_meet_active_days_minimum():
    offset = timezone(timedelta(hours=-6))
    rows = [event(number, occurred_at=(CUTOFF - age).astimezone(offset),
                  recorded_at=CUTOFF - timedelta(seconds=1))
            for number, age in enumerate([
                timedelta(hours=23), timedelta(hours=22), timedelta(hours=1),
            ], start=1)]
    result = features(rows)
    assert result.interaction_count == 3
    assert result.active_days == 1
    assert result.cold_start == "insufficient"


def test_offsets_and_input_order_do_not_change_features():
    rows = [event(1), event(2, age=timedelta(days=2), sku=22)]
    offset = timezone(timedelta(hours=-6))
    shifted = [replace(row, occurred_at=row.occurred_at.astimezone(offset),
                       recorded_at=row.recorded_at.astimezone(offset)) for row in rows]
    result = build_features(reversed(shifted), customer_id=1,
                            cutoff=CUTOFF.astimezone(offset), coverage=COVERAGE)
    assert result == features(rows)


def test_recency_and_lookback_use_elapsed_utc_time_across_dst():
    zone = ZoneInfo("America/New_York")
    cutoff = datetime(2026, 3, 9, 0, tzinfo=zone)
    occurred = datetime(2026, 3, 8, 0, tzinfo=zone)
    coverage = HistoryCoverage(1, cutoff.astimezone(timezone.utc) - timedelta(days=90),
                               cutoff, frozenset(EVENT_TYPES))
    result = build_features([event(1, occurred_at=occurred, recorded_at=occurred)],
                            customer_id=1, cutoff=cutoff, coverage=coverage)
    assert result.recency_days["click"] == 23 / 24


@pytest.mark.parametrize("changes", [
    {"occurred_at": CUTOFF.replace(tzinfo=None)},
    {"recorded_at": CUTOFF.replace(tzinfo=None)},
    {"event_type": "unverified_view"}, {"sku_id": True}, {"customer_id": 0},
    {"event_id": "unstable"}, {"request_id": "unstable"},
])
def test_invalid_event_inputs_fail_instead_of_becoming_features(changes):
    with pytest.raises(ValueError):
        features([event(1, **changes)])


@pytest.mark.parametrize("changes", [
    {"lookback": timedelta(0)}, {"lookback": -timedelta(days=1)},
    {"min_interactions": 0}, {"min_active_days": True},
])
def test_invalid_policy_is_rejected(changes):
    with pytest.raises(ValueError):
        FeaturePolicy(**changes)


def test_invalid_cutoff_and_coverage_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_features([], customer_id=1, cutoff=CUTOFF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="precede"):
        replace(COVERAGE, start=CUTOFF)
    with pytest.raises(ValueError, match="unknown coverage"):
        replace(COVERAGE, event_types=frozenset({"unknown"}))
