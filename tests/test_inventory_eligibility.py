"""Synthetic stock and clock fixtures; no live stock or production SLA evidence."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from clavel.database.repositories import StockObservation
from clavel.intelligence.recommendations.inventory import (
    FreshnessPolicy,
    InventoryEligibility as Reason,
    filter_inventory,
    inventory_eligibility,
)


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
POLICY = FreshnessPolicy(timedelta(minutes=5))  # Synthetic, not a Q07 decision.


def stock(quantity=4, *, age=timedelta(0), sku_id=1):
    """Build a synthetic repository observation, never a provider response."""
    return StockObservation(sku_id, quantity, 1, NOW - age)


@pytest.mark.parametrize("observation,reason", [
    (None, Reason.UNKNOWN_STOCK),
    (stock(None), Reason.UNKNOWN_STOCK),
    (stock(0), Reason.OUT_OF_STOCK),
    (stock(1), Reason.IN_STOCK),
    (stock(100), Reason.IN_STOCK),
    (stock(age=timedelta(minutes=6)), Reason.STALE_STOCK),
    (stock(age=POLICY.max_age), Reason.IN_STOCK),
    (stock(age=POLICY.max_age + timedelta(microseconds=1)), Reason.STALE_STOCK),
    (stock(age=POLICY.max_age - timedelta(microseconds=1)), Reason.IN_STOCK),
    (stock(age=-timedelta(microseconds=1)), Reason.FUTURE_OBSERVATION),
    (stock(-1), Reason.INVALID_STOCK),
    (stock(True), Reason.INVALID_STOCK),
    (stock(1.5), Reason.INVALID_STOCK),
    (stock("4"), Reason.INVALID_STOCK),
    (stock(None, age=timedelta(days=1)), Reason.UNKNOWN_STOCK),
    (stock(0, age=timedelta(days=1)), Reason.OUT_OF_STOCK),
])
def test_inventory_states_and_freshness_boundaries(observation, reason):
    decision = inventory_eligibility(observation, now=NOW, policy=POLICY)
    assert decision is reason
    assert decision.eligible is (reason is Reason.IN_STOCK)


@pytest.mark.parametrize("quantity,reason", [
    (4, Reason.FRESHNESS_UNCONFIGURED),
    (None, Reason.UNKNOWN_STOCK),
    (0, Reason.OUT_OF_STOCK),
])
def test_missing_policy_never_makes_stock_eligible(quantity, reason):
    assert inventory_eligibility(stock(quantity), now=NOW, policy=None) is reason


@pytest.mark.parametrize("observed_at", [None, NOW.replace(tzinfo=None)])
def test_unknown_or_naive_observation_time_fails_closed(observed_at):
    observation = StockObservation(1, 4, 1, observed_at)
    assert inventory_eligibility(observation, now=NOW, policy=POLICY) is (
        Reason.INVALID_OBSERVATION_TIME
    )


def test_equivalent_timezone_offsets_have_identical_freshness():
    observed = (NOW - POLICY.max_age).astimezone(timezone(timedelta(hours=-6)))
    observation = StockObservation(1, 4, 1, observed)
    assert inventory_eligibility(observation, now=NOW, policy=POLICY) is Reason.IN_STOCK


def test_freshness_uses_source_time_even_with_high_version():
    observation = StockObservation(1, 4, 999999, NOW - timedelta(days=1))
    assert inventory_eligibility(observation, now=NOW, policy=POLICY) is Reason.STALE_STOCK


@pytest.mark.parametrize("max_age", [timedelta(0), -timedelta(seconds=1)])
def test_nonpositive_policy_is_rejected(max_age):
    with pytest.raises(ValueError, match="max_age must be positive"):
        FreshnessPolicy(max_age)


def test_naive_clock_is_rejected_including_empty_filter():
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        inventory_eligibility(stock(), now=NOW.replace(tzinfo=None), policy=POLICY)
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        filter_inventory([], {}, now=NOW.replace(tzinfo=None), policy=POLICY)


def test_filter_preserves_rank_and_explicit_exclusions_without_mutating_inputs():
    candidates = [7, 2, 3, 4, 5, 6, 1, 7, 8]
    observations = {
        7: stock(sku_id=7),
        2: stock(0, sku_id=2),
        3: stock(age=timedelta(hours=1), sku_id=3),
        4: stock(None, sku_id=4),
        6: stock(age=-timedelta(seconds=1), sku_id=6),
        1: stock(),
        8: stock(sku_id=9),  # Incorrect mapping must not qualify SKU 8.
        99: stock(sku_id=99),  # Unrequested SKU must never enter candidates.
    }
    before = observations.copy()
    result = filter_inventory(iter(candidates), observations, now=NOW, policy=POLICY)
    assert result.eligible_sku_ids == (7, 1)
    assert result.decisions == {
        7: Reason.IN_STOCK,
        2: Reason.OUT_OF_STOCK,
        3: Reason.STALE_STOCK,
        4: Reason.UNKNOWN_STOCK,
        5: Reason.UNKNOWN_STOCK,
        6: Reason.FUTURE_OBSERVATION,
        1: Reason.IN_STOCK,
        8: Reason.SKU_MISMATCH,
    }
    assert list(result.decisions) == list(dict.fromkeys(candidates))
    assert observations == before
    assert candidates == [7, 2, 3, 4, 5, 6, 1, 7, 8]


def test_empty_filter_and_unconfigured_filter():
    empty = filter_inventory([], {}, now=NOW, policy=POLICY)
    assert empty.eligible_sku_ids == ()
    assert empty.decisions == {}
    result = filter_inventory([1, 2], {1: stock()}, now=NOW, policy=None)
    assert result.eligible_sku_ids == ()
    assert result.decisions == {1: Reason.FRESHNESS_UNCONFIGURED, 2: Reason.UNKNOWN_STOCK}


@pytest.mark.parametrize("now_fields,observed_fields,reason", [
    ((1, 30, 1), (1, 30, 0), Reason.STALE_STOCK),
    ((1, 30, 0), (1, 30, 1), Reason.FUTURE_OBSERVATION),
    ((1, 10, 1), (1, 55, 0), Reason.STALE_STOCK),
    ((1, 55, 0), (1, 10, 1), Reason.FUTURE_OBSERVATION),
    ((1, 0, 1), (1, 55, 0), Reason.IN_STOCK),
])
def test_freshness_uses_utc_instants_across_dst_fallback(
    now_fields, observed_fields, reason,
):
    """Synthetic repeated-hour clocks must preserve actual elapsed time."""
    zone = ZoneInfo("America/New_York")
    hour, minute, fold = now_fields
    now = datetime(2026, 11, 1, hour, minute, tzinfo=zone, fold=fold)
    hour, minute, fold = observed_fields
    observed_at = datetime(2026, 11, 1, hour, minute, tzinfo=zone, fold=fold)
    observation = StockObservation(1, 4, 1, observed_at)
    assert inventory_eligibility(observation, now=now, policy=POLICY) is reason
    result = filter_inventory([1], {1: observation}, now=now, policy=POLICY)
    assert result.decisions == {1: reason}
    assert result.eligible_sku_ids == ((1,) if reason is Reason.IN_STOCK else ())
