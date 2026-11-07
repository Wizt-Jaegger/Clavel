"""Invented numeric snapshots; synthetic mechanics only, no live evidence."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from clavel.intelligence.clustering.features import EVENT_TYPES, FeaturePolicy
from clavel.intelligence.clustering.preprocessing import (
    COLUMNS, OUTPUT_COLUMNS, FittedPreprocessor, fit_preprocessor,
)
from clavel.intelligence.clustering.snapshots import extract_snapshot


CUTOFF = datetime(2026, 4, 1, tzinfo=timezone.utc)


def synthetic_snapshot(counts, *, cutoff=CUTOFF, policy=FeaturePolicy()):
    """Controlled invented values, derived from the public empty-snapshot shape."""
    snapshot = extract_snapshot([], customer_ids=range(1, len(counts) + 1),
                                cutoff=cutoff, policy=policy)
    return replace(snapshot, rows=tuple(
        replace(row, frequency=dict.fromkeys(EVENT_TYPES, count),
                recency_days=dict.fromkeys(EVENT_TYPES, None if count is None else 2.0),
                interaction_count=None if count is None else count * 3,
                active_days=None if count is None else min(count, 1))
        for row, count in zip(snapshot.rows, counts)
    ))


def test_train_only_fit_has_known_statistics_and_inference_cannot_refit():
    training = synthetic_snapshot([1, 3, None])
    fitted = fit_preprocessor(training)
    assert fitted.medians[0] == fitted.centers[0] == 2
    assert fitted.scales[0] == pytest.approx((2 / 3) ** .5)
    original = fitted.to_json()
    future = synthetic_snapshot([101], cutoff=CUTOFF + timedelta(days=10))
    transformed = fitted.transform(future)
    assert transformed.values[0][0] == pytest.approx(99 / ((2 / 3) ** .5))
    assert transformed.customer_ids == (1,)
    assert transformed.columns == OUTPUT_COLUMNS
    assert transformed.preprocessing_version == fitted.version
    assert fitted.to_json() == original
    # A held-out outlier would change statistics if it were incorrectly fit.
    assert fit_preprocessor(synthetic_snapshot([1, 3, None, 101])).centers != fitted.centers


def test_missing_zero_constant_and_all_missing_remain_distinguishable():
    snapshot = synthetic_snapshot([0, None])
    fitted = fit_preprocessor(snapshot)
    result = fitted.transform(snapshot)
    assert result.values[0][:len(COLUMNS)] == result.values[1][:len(COLUMNS)]
    assert result.values[0][len(COLUMNS):] == (0.0,) * len(COLUMNS)
    assert result.values[1][len(COLUMNS):] == (1.0,) * len(COLUMNS)
    assert all(scale == 1 for scale in fitted.scales)
    entirely_missing = fit_preprocessor(synthetic_snapshot([None]))
    assert entirely_missing.medians == entirely_missing.centers == (0.0,) * len(COLUMNS)
    assert entirely_missing.scales == (1.0,) * len(COLUMNS)
    assert entirely_missing.transform(synthetic_snapshot([None])).values == (
        (0.0,) * len(COLUMNS) + (1.0,) * len(COLUMNS),)
    assert snapshot.rows[1].frequency["click"] is None


def test_new_missing_values_at_inference_keep_fixed_indicator_columns():
    fitted = fit_preprocessor(synthetic_snapshot([1, 3]))
    result = fitted.transform(synthetic_snapshot([None]))
    assert result.values[0] == (0.0,) * len(COLUMNS) + (1.0,) * len(COLUMNS)


def test_artifact_round_trip_reuses_exact_transforms_and_rejects_mutation():
    training = synthetic_snapshot([1, 3, None])
    fitted = fit_preprocessor(training)
    loaded = FittedPreprocessor.from_json(fitted.to_json())
    assert loaded == fitted
    assert loaded.to_json() == fitted.to_json()
    assert loaded.transform(training) == fitted.transform(training)
    with pytest.raises(FrozenInstanceError):
        fitted.training_rows = 99
    reversed_rows = replace(training, rows=tuple(reversed(training.rows)))
    assert fit_preprocessor(reversed_rows).version == fitted.version
    assert fit_preprocessor(synthetic_snapshot([1, 4, None])).version != fitted.version


@pytest.mark.parametrize("change", [
    {"format": "future-v2"}, {"columns": list(reversed(COLUMNS))},
    {"scales": [0.0] * len(COLUMNS)}, {"scales": [1.0]},
    {"medians": [None] * len(COLUMNS)}, {"centers": [float("nan")] * len(COLUMNS)},
    {"training_rows": True}, {"training_cutoff": "2026-04-01T00:00:00"},
    {"training_rows": 100}, {"version": "invented"}, {"extra": 1},
    {"policy": {"lookback_microseconds": True}},
])
def test_invalid_or_modified_artifacts_fail_closed(change):
    payload = json.loads(fit_preprocessor(synthetic_snapshot([1, 3])).to_json())
    with pytest.raises(ValueError):
        FittedPreprocessor.from_json(json.dumps(payload | change))


@pytest.mark.parametrize("document", ["null", "[]", "{", "42"])
def test_malformed_artifact_rejected(document):
    with pytest.raises(ValueError):
        FittedPreprocessor.from_json(document)


@pytest.mark.parametrize("changes", [
    {"definition_version": "behavioral-v2"},
    {"frequency": {"click": 1}},
    {"recency_days": dict.fromkeys((*EVENT_TYPES, "unknown"), None)},
    {"frequency": dict.fromkeys(EVENT_TYPES, True)},
    {"frequency": dict.fromkeys(EVENT_TYPES, 1.5)},
    {"interaction_count": -1}, {"active_days": "1"},
    {"recency_days": dict.fromkeys(EVENT_TYPES, float("inf"))},
    {"recency_days": dict.fromkeys(EVENT_TYPES, float("nan"))},
    {"recency_days": dict.fromkeys(EVENT_TYPES, -1.0)},
    {"cutoff": CUTOFF + timedelta(days=1)},
    {"window_start": CUTOFF}, {"customer_id": True},
])
def test_invalid_feature_schema_rejected_in_both_fit_and_inference(changes):
    good = synthetic_snapshot([1])
    bad = replace(good, rows=(replace(good.rows[0], **changes),))
    with pytest.raises(ValueError):
        fit_preprocessor(bad)
    with pytest.raises(ValueError):
        fit_preprocessor(good).transform(bad)


def test_policy_mismatch_duplicates_empty_training_and_empty_inference():
    good = synthetic_snapshot([1])
    fitted = fit_preprocessor(good)
    with pytest.raises(ValueError, match="policy"):
        fitted.transform(synthetic_snapshot([1], policy=FeaturePolicy(lookback=timedelta(days=7))))
    duplicate = replace(good, rows=good.rows * 2)
    with pytest.raises(ValueError, match="duplicate"):
        fit_preprocessor(duplicate)
    with pytest.raises(ValueError, match="duplicate"):
        fitted.transform(duplicate)
    with pytest.raises(ValueError, match="must contain rows"):
        fit_preprocessor(synthetic_snapshot([]))
    assert fitted.transform(synthetic_snapshot([])).values == ()


def test_version_binds_policy_training_cutoff_and_parameters():
    baseline = fit_preprocessor(synthetic_snapshot([1]))
    later = fit_preprocessor(synthetic_snapshot([1], cutoff=CUTOFF + timedelta(days=1)))
    policy = fit_preprocessor(synthetic_snapshot([1], policy=FeaturePolicy(min_interactions=4)))
    assert len({baseline.version, later.version, policy.version}) == 3
