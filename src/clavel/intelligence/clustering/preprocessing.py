"""Train-only numeric transforms for behavioral-v1 snapshots.

Missing indicators accompany imputed values; imputation never asserts observed
history. Affinity vocabularies and cold-start eligibility are separate concerns.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from math import isfinite
from statistics import fmean, median, pstdev

from clavel.intelligence.clustering.features import (
    EVENT_TYPES, FeaturePolicy, _positive_id, _utc,
)
from clavel.intelligence.clustering.snapshots import FeatureSnapshot


FORMAT = "behavioral-preprocessing-v1"
COLUMNS = tuple(f"{group}.{kind}" for group in ("frequency", "recency_days")
                for kind in EVENT_TYPES) + ("interaction_count", "active_days")
OUTPUT_COLUMNS = COLUMNS + tuple(f"missing.{name}" for name in COLUMNS)


def _number(value, *, count=False):
    if value is None:
        return None
    if type(value) not in ((int,) if count else (int, float)):
        raise ValueError("invalid numeric feature schema")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("numeric features must be finite and nonnegative") from exc
    if not isfinite(number) or number < 0:
        raise ValueError("numeric features must be finite and nonnegative")
    return number


def _matrix(snapshot: FeatureSnapshot, policy: FeaturePolicy):
    if snapshot.policy != policy:
        raise ValueError("incompatible feature policy")
    cutoff = _utc(snapshot.cutoff)
    seen = set()
    matrix = []
    for row in snapshot.rows:
        _positive_id(row.customer_id)
        if row.customer_id in seen:
            raise ValueError("duplicate customer in feature snapshot")
        seen.add(row.customer_id)
        if (row.definition_version != "behavioral-v1" or row.policy != policy
                or _utc(row.cutoff) != cutoff
                or _utc(row.window_start) != cutoff - policy.lookback):
            raise ValueError("incompatible feature snapshot schema")
        values = []
        for group in ("frequency", "recency_days"):
            mapping = getattr(row, group)
            if not isinstance(mapping, dict) or set(mapping) != set(EVENT_TYPES):
                raise ValueError("invalid feature columns")
            values.extend(_number(mapping[kind], count=group == "frequency")
                          for kind in EVENT_TYPES)
        values.extend((_number(row.interaction_count, count=True),
                       _number(row.active_days, count=True)))
        matrix.append(tuple(values))
    return tuple(matrix)


@dataclass(frozen=True)
class PreprocessedSnapshot:
    customer_ids: tuple[int, ...]
    values: tuple[tuple[float, ...], ...]
    preprocessing_version: str
    columns: tuple[str, ...] = OUTPUT_COLUMNS


@dataclass(frozen=True)
class FittedPreprocessor:
    """Immutable, serializable parameters; inference has no fitting operation."""

    training_cutoff: datetime
    training_rows: int
    policy: FeaturePolicy
    medians: tuple[float, ...]
    centers: tuple[float, ...]
    scales: tuple[float, ...]

    def __post_init__(self):
        object.__setattr__(self, "training_cutoff", _utc(self.training_cutoff))
        _positive_id(self.training_rows)
        if not isinstance(self.policy, FeaturePolicy):
            raise ValueError("invalid preprocessing policy")
        for name in ("medians", "centers", "scales"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) != len(COLUMNS):
                raise ValueError("invalid preprocessing parameter dimensions")
            for value in values:
                number = _number(value)
                if number is None or (name == "scales" and number == 0):
                    raise ValueError("invalid preprocessing parameters")

    def _payload(self):
        return dict(format=FORMAT, columns=COLUMNS,
                    training_cutoff=self.training_cutoff.isoformat(),
                    training_rows=self.training_rows,
                    policy=dict(lookback_microseconds=self.policy.lookback // timedelta(microseconds=1),
                                min_interactions=self.policy.min_interactions,
                                min_active_days=self.policy.min_active_days),
                    medians=self.medians, centers=self.centers, scales=self.scales)

    @property
    def version(self):
        payload = json.dumps(self._payload(), sort_keys=True, separators=(",", ":"),
                             allow_nan=False)
        return f"{FORMAT}:{sha256(payload.encode()).hexdigest()}"

    def to_json(self):
        return json.dumps(self._payload() | {"version": self.version}, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, document: str):
        """Reject altered/unsupported artifacts; digest is identity, not auth."""
        try:
            payload = json.loads(document)
            if (set(payload) != {"format", "columns", "training_cutoff", "training_rows",
                                 "policy", "medians", "centers", "scales", "version"}
                    or payload["format"] != FORMAT or payload["columns"] != list(COLUMNS)):
                raise ValueError("invalid preprocessing artifact schema")
            policy = payload["policy"]
            if (set(policy) != {"lookback_microseconds", "min_interactions", "min_active_days"}
                    or type(policy["lookback_microseconds"]) is not int):
                raise ValueError("invalid preprocessing policy schema")
            result = cls(
                datetime.fromisoformat(payload["training_cutoff"]), payload["training_rows"],
                FeaturePolicy(timedelta(microseconds=policy["lookback_microseconds"]),
                              policy["min_interactions"], policy["min_active_days"]),
                *(tuple(payload[name]) for name in ("medians", "centers", "scales")),
            )
            if result.version != payload["version"]:
                raise ValueError("preprocessing artifact version mismatch")
            return result
        except (TypeError, KeyError, OverflowError, AttributeError) as exc:
            raise ValueError("invalid preprocessing artifact schema") from exc

    def transform(self, snapshot: FeatureSnapshot) -> PreprocessedSnapshot:
        matrix = _matrix(snapshot, self.policy)
        transformed = []
        for row in matrix:
            values = tuple(((self.medians[i] if value is None else value) - self.centers[i])
                           / self.scales[i] for i, value in enumerate(row))
            if not all(isfinite(value) for value in values):
                raise ValueError("nonfinite transformed feature")
            transformed.append(values + tuple(float(value is None) for value in row))
        return PreprocessedSnapshot(tuple(row.customer_id for row in snapshot.rows),
                                    tuple(transformed), self.version)


def fit_preprocessor(training: FeatureSnapshot) -> FittedPreprocessor:
    """Fit medians, then mean/population std after imputation, on training only.

    An entirely missing column imputes 0; a constant column uses scale 1. Every
    column always has a missing indicator, including columns complete at fit.
    """
    matrix = _matrix(training, training.policy)
    if not matrix:
        raise ValueError("training snapshot must contain rows")
    medians, centers, scales = [], [], []
    for column in zip(*matrix):
        observed = [value for value in column if value is not None]
        fill = float(median(observed)) if observed else 0.0
        filled = [fill if value is None else value for value in column]
        medians.append(fill)
        centers.append(fmean(filled))
        scales.append(pstdev(filled) or 1.0)
    return FittedPreprocessor(training.cutoff, len(matrix), training.policy,
                              tuple(medians), tuple(centers), tuple(scales))
