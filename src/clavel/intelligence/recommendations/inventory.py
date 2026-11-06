"""Inventory-only eligibility; no production freshness SLA is implied.

Callers supply both the evaluation clock and a freshness policy. Age is measured
from the source observation, never receipt time. The maximum age is inclusive;
future observations fail closed without an implicit clock-skew allowance.
Eligibility here says nothing about compatibility or other recommendation gates.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from clavel.database.repositories import StockObservation


@dataclass(frozen=True)
class FreshnessPolicy:
    max_age: timedelta

    def __post_init__(self):
        if self.max_age <= timedelta(0):
            raise ValueError("max_age must be positive")


class InventoryEligibility(StrEnum):
    IN_STOCK = "in_stock"
    UNKNOWN_STOCK = "unknown_stock"
    OUT_OF_STOCK = "out_of_stock"
    INVALID_STOCK = "invalid_stock"
    FRESHNESS_UNCONFIGURED = "freshness_unconfigured"
    INVALID_OBSERVATION_TIME = "invalid_observation_time"
    FUTURE_OBSERVATION = "future_observation"
    STALE_STOCK = "stale_stock"
    SKU_MISMATCH = "sku_mismatch"

    @property
    def eligible(self) -> bool:
        return self is InventoryEligibility.IN_STOCK


def inventory_eligibility(
    observation: StockObservation | None,
    *,
    now: datetime,
    policy: FreshnessPolicy | None,
) -> InventoryEligibility:
    """Return one explicit reason, preserving unknown stock instead of zeroing it.

Quantity failures take precedence over freshness failures. Missing policy never
qualifies positive stock; a naive evaluation clock is a caller error.
"""
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if observation is None or observation.sellable_stock is None:
        return InventoryEligibility.UNKNOWN_STOCK
    quantity = observation.sellable_stock
    if type(quantity) is not int or quantity < 0:
        return InventoryEligibility.INVALID_STOCK
    if quantity == 0:
        return InventoryEligibility.OUT_OF_STOCK
    if policy is None:
        return InventoryEligibility.FRESHNESS_UNCONFIGURED
    observed_at = observation.observed_at
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        return InventoryEligibility.INVALID_OBSERVATION_TIME
    # A shared ZoneInfo can subtract wall times across DST, ignoring fold.
    age = now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)
    if age < timedelta(0):
        return InventoryEligibility.FUTURE_OBSERVATION
    if age > policy.max_age:
        return InventoryEligibility.STALE_STOCK
    return InventoryEligibility.IN_STOCK


@dataclass
class InventoryFilterResult:
    eligible_sku_ids: tuple[int, ...]
    decisions: dict[int, InventoryEligibility]


def filter_inventory(
    candidate_sku_ids: Iterable[int],
    observations: Mapping[int, StockObservation],
    *,
    now: datetime,
    policy: FreshnessPolicy | None,
) -> InventoryFilterResult:
    """Filter unique candidates in ranking order and retain every decision.

An absent inventory row is unknown. Observations for unrelated SKUs are ignored;
a mismatched mapping entry fails closed rather than borrowing another SKU's stock.
"""
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    decisions = {}
    for sku_id in dict.fromkeys(candidate_sku_ids):
        observation = observations.get(sku_id)
        if observation is not None and observation.sku_id != sku_id:
            decisions[sku_id] = InventoryEligibility.SKU_MISMATCH
        else:
            decisions[sku_id] = inventory_eligibility(observation, now=now, policy=policy)
    return InventoryFilterResult(
        tuple(sku_id for sku_id, decision in decisions.items() if decision.eligible),
        decisions,
    )
