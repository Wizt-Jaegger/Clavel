"""Versioned, algorithm-independent clustering boundary (no serving policy).

Callers supply explicit evidence validity and an immutable training snapshot ID.
Numeric imputation alone never establishes eligibility. Implementations fit only
the supplied training batch and keep assignment free of refitting or updates.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import final

from clavel.intelligence.clustering.preprocessing import PreprocessedSnapshot


CONTRACT_VERSION = "clustering-v1"


class Validity(StrEnum):
    VALID = "valid"
    UNKNOWN = "unknown"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("version, snapshot ID and column names must be nonempty strings")


def _tuple(value):
    if not isinstance(value, tuple):
        raise ValueError("contract collections must be immutable tuples")


def _ids(ids):
    _tuple(ids)
    if any(type(value) is not int or value <= 0 for value in ids):
        raise ValueError("customer IDs must be positive integers")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate customer IDs")


def _columns(columns):
    _tuple(columns)
    if not columns:
        raise ValueError("feature columns must not be empty")
    for column in columns:
        _text(column)
    if len(set(columns)) != len(columns):
        raise ValueError("duplicate feature columns")


@dataclass(frozen=True)
class ClusteringBatch:
    """One explicit evidence state per preprocessed row, in the same order."""

    features: PreprocessedSnapshot
    validity: tuple[Validity, ...]

    def __post_init__(self):
        if not isinstance(self.features, PreprocessedSnapshot):
            raise ValueError("preprocessed snapshot required")
        features = self.features
        _ids(features.customer_ids)
        _columns(features.columns)
        _text(features.preprocessing_version)
        _tuple(features.values)
        _tuple(self.validity)
        if not (len(features.customer_ids) == len(features.values) == len(self.validity)):
            raise ValueError("row, customer and validity counts must match")
        if any(not isinstance(flag, Validity) for flag in self.validity):
            raise ValueError("explicit evidence validity required")
        for row in features.values:
            _tuple(row)
            if len(row) != len(features.columns):
                raise ValueError("feature dimensions must match columns")
            for value in row:
                try:
                    finite = type(value) in (int, float) and isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("features must be finite numbers")


@dataclass(frozen=True)
class ModelLineage:
    """Model version binds parameters; snapshot ID binds training provenance.

    Versions/IDs are opaque identities supplied by the implementation/caller,
    not authentication or proof of live provenance. Segments are model-local.
    """

    algorithm_version: str
    model_version: str
    training_snapshot_id: str
    preprocessing_version: str
    columns: tuple[str, ...]
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self):
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("unsupported clustering contract version")
        for value in (self.algorithm_version, self.model_version,
                      self.training_snapshot_id, self.preprocessing_version):
            _text(value)
        _columns(self.columns)


@dataclass(frozen=True)
class Membership:
    customer_id: int
    segment_id: int | None
    validity: Validity

    def __post_init__(self):
        _ids((self.customer_id,))
        if not isinstance(self.validity, Validity):
            raise ValueError("explicit result validity required")
        if self.validity is Validity.VALID:
            if type(self.segment_id) is not int or self.segment_id < 0:
                raise ValueError("valid membership requires a nonnegative segment ID")
        elif self.segment_id is not None:
            raise ValueError("nonvalid membership cannot claim a segment")


@dataclass(frozen=True)
class ClusteringResult:
    lineage: ModelLineage
    memberships: tuple[Membership, ...]

    def __post_init__(self):
        if not isinstance(self.lineage, ModelLineage):
            raise ValueError("model lineage required")
        _tuple(self.memberships)
        if any(not isinstance(row, Membership) for row in self.memberships):
            raise ValueError("membership results required")
        _ids(tuple(row.customer_id for row in self.memberships))


class FittedClustering(ABC):
    """Immutable fitted state; assign must never train or mutate the model."""

    @property
    @abstractmethod
    def lineage(self) -> ModelLineage:
        """Identity of the exact fitted model and its training inputs."""

    @final
    def assign(self, batch: ClusteringBatch) -> ClusteringResult:
        if not isinstance(batch, ClusteringBatch):
            raise ValueError("clustering batch required")
        lineage = self.lineage
        if not isinstance(lineage, ModelLineage):
            raise ValueError("model lineage required")
        features = batch.features
        if (features.preprocessing_version != lineage.preprocessing_version
                or features.columns != lineage.columns):
            raise ValueError("incompatible preprocessing version or feature columns")
        eligible = tuple(i for i, flag in enumerate(batch.validity) if flag is Validity.VALID)
        selected = PreprocessedSnapshot(
            tuple(features.customer_ids[i] for i in eligible),
            tuple(features.values[i] for i in eligible),
            features.preprocessing_version, features.columns,
        )
        assigned = self._assign(selected) if eligible else ()
        # Validate backend output before restoring original row order/flags.
        result = ClusteringResult(lineage, assigned)
        if tuple(row.customer_id for row in result.memberships) != selected.customer_ids:
            raise ValueError("assignment must return each eligible customer in input order")
        if self.lineage != lineage:
            raise ValueError("assignment changed model lineage")
        rows = iter(result.memberships)
        return ClusteringResult(lineage, tuple(
            next(rows) if flag is Validity.VALID else Membership(customer_id, None, flag)
            for customer_id, flag in zip(features.customer_ids, batch.validity)
        ))

    @abstractmethod
    def _assign(self, features: PreprocessedSnapshot) -> tuple[Membership, ...]:
        """Assign eligible rows in order; unavailable output has no segment."""


class ClusteringAlgorithm(ABC):
    @property
    @abstractmethod
    def algorithm_version(self) -> str:
        """Version of the implementation and its fit semantics."""

    @final
    def fit(self, training: ClusteringBatch, *, training_snapshot_id: str) -> FittedClustering:
        _text(training_snapshot_id)
        if not isinstance(training, ClusteringBatch):
            raise ValueError("clustering batch required")
        if not training.features.customer_ids:
            raise ValueError("training must contain rows")
        if any(flag is not Validity.VALID for flag in training.validity):
            raise ValueError("training requires explicitly valid evidence for every row")
        _text(self.algorithm_version)
        model = self._fit(training.features, training_snapshot_id=training_snapshot_id)
        if not isinstance(model, FittedClustering) or not isinstance(model.lineage, ModelLineage):
            raise ValueError("fitted clustering model with lineage required")
        lineage = model.lineage
        if (lineage.algorithm_version != self.algorithm_version
                or lineage.training_snapshot_id != training_snapshot_id
                or lineage.preprocessing_version != training.features.preprocessing_version
                or lineage.columns != training.features.columns):
            raise ValueError("fitted model lineage does not match training inputs")
        return model

    @abstractmethod
    def _fit(self, training: PreprocessedSnapshot, *, training_snapshot_id: str) -> FittedClustering:
        """Fit only these rows; return a versioned model without serving changes."""
