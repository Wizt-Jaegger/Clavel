"""Reusable contract checks with an invented threshold implementation.

All rows/versions are synthetic. This proves boundary mechanics, not BIRCH
quality, calibrated eligibility, provider availability or live acceptance.
"""

from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from statistics import fmean

import pytest

from clavel.intelligence.clustering.contracts import (
    CONTRACT_VERSION, ClusteringAlgorithm, ClusteringBatch, ClusteringResult,
    FittedClustering, Membership, ModelLineage, Validity,
)
from clavel.intelligence.clustering.preprocessing import (
    PreprocessedSnapshot, fit_preprocessor,
)
from clavel.intelligence.clustering.snapshots import extract_snapshot


def synthetic_batch(values=(1.0, 3.0), *, validity=None):
    features = PreprocessedSnapshot(
        tuple(range(1, len(values) + 1)), tuple((value,) for value in values),
        "synthetic-preprocessing-v1", ("synthetic.value",),
    )
    return ClusteringBatch(features, validity if validity is not None
                           else (Validity.VALID,) * len(values))


@dataclass(frozen=True)
class SyntheticModel(FittedClustering):
    """Test double only; no clustering quality claim."""

    _lineage: ModelLineage
    threshold: float

    @property
    def lineage(self):
        return self._lineage

    def _assign(self, features):
        return tuple(Membership(customer_id, int(row[0] >= self.threshold), Validity.VALID)
                     for customer_id, row in zip(features.customer_ids, features.values))


class SyntheticAlgorithm(ClusteringAlgorithm):
    @property
    def algorithm_version(self):
        return "synthetic-threshold-v1"

    def _fit(self, training, *, training_snapshot_id):
        threshold = fmean(row[0] for row in training.values)
        identity = sha256(repr((training, training_snapshot_id, threshold)).encode()).hexdigest()
        lineage = ModelLineage(self.algorithm_version, f"synthetic-model:{identity}",
                               training_snapshot_id, training.preprocessing_version,
                               training.columns)
        return SyntheticModel(lineage, threshold)


@pytest.fixture
def algorithm():
    """Future implementations can run this suite with their own factory."""
    return SyntheticAlgorithm()


class ClusteringContractSuite:
    """Algorithm-independent assertions, reused by supplying an algorithm fixture."""

    def test_fit_records_exact_lineage_and_assignment_preserves_it(self, algorithm):
        training = synthetic_batch()
        model = algorithm.fit(training, training_snapshot_id="synthetic-training-001")
        lineage = model.lineage
        assert lineage.contract_version == CONTRACT_VERSION
        assert lineage.algorithm_version == algorithm.algorithm_version
        assert lineage.model_version
        assert lineage.training_snapshot_id == "synthetic-training-001"
        assert lineage.preprocessing_version == training.features.preprocessing_version
        assert lineage.columns == training.features.columns
        inference = synthetic_batch((100.0, -5.0))
        original_training, original_inference = repr(training), repr(inference)
        first = model.assign(inference)
        assert model.assign(inference) == first
        assert first.lineage == model.lineage == lineage
        assert tuple(row.customer_id for row in first.memberships) == inference.features.customer_ids
        assert repr(training) == original_training
        assert repr(inference) == original_inference

    def test_nonvalid_evidence_keeps_its_state_and_has_no_segment(self, algorithm):
        model = algorithm.fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")
        flags = (Validity.UNKNOWN, Validity.VALID, Validity.INSUFFICIENT, Validity.UNAVAILABLE)
        result = model.assign(synthetic_batch((0.0, 4.0, 2.0, 7.0), validity=flags))
        assert tuple(row.customer_id for row in result.memberships) == (1, 2, 3, 4)
        for row, flag in zip(result.memberships, flags):
            if flag is not Validity.VALID:
                assert row.validity is flag
                assert row.segment_id is None

    def test_empty_inference_and_unknown_only_inference(self, algorithm):
        model = algorithm.fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")
        assert model.assign(synthetic_batch(())).memberships == ()
        result = model.assign(synthetic_batch((0.0,), validity=(Validity.UNKNOWN,)))
        assert result.memberships == (Membership(1, None, Validity.UNKNOWN),)

    @pytest.mark.parametrize("flag", [Validity.UNKNOWN, Validity.INSUFFICIENT, Validity.UNAVAILABLE])
    def test_training_rejects_nonvalid_evidence(self, algorithm, flag):
        with pytest.raises(ValueError, match="valid evidence"):
            algorithm.fit(synthetic_batch(validity=(Validity.VALID, flag)),
                          training_snapshot_id="synthetic-training-001")

    def test_empty_training_and_missing_snapshot_identity_rejected(self, algorithm):
        with pytest.raises(ValueError, match="contain rows"):
            algorithm.fit(synthetic_batch(()), training_snapshot_id="synthetic-training-001")
        for identity in (None, "", " "):
            with pytest.raises(ValueError):
                algorithm.fit(synthetic_batch(), training_snapshot_id=identity)

    @pytest.mark.parametrize("changes", [
        {"preprocessing_version": "synthetic-preprocessing-v2"},
        {"columns": ("synthetic.other",)},
    ])
    def test_incompatible_inference_rejected(self, algorithm, changes):
        batch = synthetic_batch()
        model = algorithm.fit(batch, training_snapshot_id="synthetic-training-001")
        with pytest.raises(ValueError, match="incompatible"):
            model.assign(replace(batch, features=replace(batch.features, **changes)))


class TestSyntheticClusteringContract(ClusteringContractSuite):
    pass


def test_synthetic_assignment_uses_training_only_and_model_is_immutable(algorithm):
    model = algorithm.fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")
    inference = synthetic_batch((-100.0, 100.0))
    assert tuple(row.segment_id for row in model.assign(inference).memberships) == (0, 1)
    assert model.threshold == 2.0
    with pytest.raises(FrozenInstanceError):
        model.threshold = 0.0
    with pytest.raises(FrozenInstanceError):
        model.lineage.model_version = "changed"
    changed = algorithm.fit(synthetic_batch((1.0, 5.0)),
                            training_snapshot_id="synthetic-training-002")
    assert changed.lineage.model_version != model.lineage.model_version


@pytest.mark.parametrize("changes", [
    {"customer_ids": (1, 1)}, {"customer_ids": (True, 2)},
    {"customer_ids": (0, 2)}, {"customer_ids": [1, 2]},
    {"values": ((1.0,),)}, {"values": ((1.0, 2.0), (3.0, 4.0))},
    {"values": ([1.0], [3.0])}, {"values": [[1.0], [3.0]]},
    {"values": ((None,), (3.0,))}, {"values": ((True,), (3.0,))},
    {"values": ((float("nan"),), (3.0,))},
    {"values": ((float("inf"),), (3.0,))},
    {"values": ((10 ** 1000,), (3.0,))},
    {"columns": ()}, {"columns": ("",)}, {"columns": ["synthetic.value"]},
    {"columns": ("same", "same")}, {"preprocessing_version": ""},
])
def test_malformed_input_fails_at_boundary(changes):
    batch = synthetic_batch()
    with pytest.raises(ValueError):
        replace(batch, features=replace(batch.features, **changes))


@pytest.mark.parametrize("flags", [(), ("valid", "valid"), (True, False),
                                   [Validity.VALID, Validity.VALID]])
def test_validity_cannot_be_omitted_coerced_or_mutable(flags):
    with pytest.raises(ValueError):
        synthetic_batch(validity=flags)


@pytest.mark.parametrize("segment,flag", [
    (None, Validity.VALID), (-1, Validity.VALID), (True, Validity.VALID),
    (1.0, Validity.VALID), (1, Validity.UNKNOWN), (0, Validity.INSUFFICIENT),
    (1, Validity.UNAVAILABLE), (None, "unknown"),
])
def test_inconsistent_membership_rejected(segment, flag):
    with pytest.raises(ValueError):
        Membership(1, segment, flag)


@pytest.mark.parametrize("changes", [
    {"contract_version": "clustering-v2"}, {"model_version": ""},
    {"algorithm_version": None}, {"training_snapshot_id": " "},
    {"preprocessing_version": ""}, {"columns": ("x", "x")},
])
def test_unsupported_or_incomplete_lineage_rejected(algorithm, changes):
    model = algorithm.fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")
    with pytest.raises(ValueError):
        replace(model.lineage, **changes)


@pytest.mark.parametrize("change", [
    {"training_snapshot_id": "wrong-snapshot"},
    {"preprocessing_version": "wrong-preprocessor"},
    {"columns": ("wrong-column",)}, {"algorithm_version": "wrong-algorithm"},
])
def test_backend_cannot_return_mismatched_training_lineage(change):
    class WrongLineage(SyntheticAlgorithm):
        def _fit(self, training, *, training_snapshot_id):
            model = super()._fit(training, training_snapshot_id=training_snapshot_id)
            return replace(model, _lineage=replace(model.lineage, **change))

    with pytest.raises(ValueError, match="lineage does not match"):
        WrongLineage().fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")


@pytest.mark.parametrize("ids", [(2, 1), (1,), (1, 1), (1, 999)])
def test_backend_cannot_reorder_drop_duplicate_or_invent_customers(algorithm, ids):
    class WrongRows(SyntheticModel):
        def _assign(self, features):
            return tuple(Membership(customer_id, 0, Validity.VALID) for customer_id in ids)

    model = algorithm.fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")
    with pytest.raises(ValueError):
        WrongRows(model.lineage, model.threshold).assign(synthetic_batch())


def test_backend_unavailable_stays_unavailable_and_failure_is_not_success(algorithm):
    class Unavailable(SyntheticModel):
        def _assign(self, features):
            return tuple(Membership(customer_id, None, Validity.UNAVAILABLE)
                         for customer_id in features.customer_ids)

    class Failed(SyntheticModel):
        def _assign(self, features):
            raise RuntimeError("synthetic backend failure")

    model = algorithm.fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")
    unavailable = Unavailable(model.lineage, model.threshold).assign(synthetic_batch())
    assert all(row.segment_id is None and row.validity is Validity.UNAVAILABLE
               for row in unavailable.memberships)
    failed = Failed(model.lineage, model.threshold)
    assert failed.assign(synthetic_batch((0.0,), validity=(Validity.UNKNOWN,))).memberships == (
        Membership(1, None, Validity.UNKNOWN),)
    with pytest.raises(RuntimeError, match="synthetic backend failure"):
        failed.assign(synthetic_batch())


def test_result_requires_lineage_immutable_rows_and_unique_customers(algorithm):
    model = algorithm.fit(synthetic_batch(), training_snapshot_id="synthetic-training-001")
    row = Membership(1, 0, Validity.VALID)
    for lineage, rows in ((None, (row,)), (model.lineage, [row]),
                          (model.lineage, (row, row)), (model.lineage, (None,))):
        with pytest.raises(ValueError):
            ClusteringResult(lineage, rows)
    result = ClusteringResult(model.lineage, (row,))
    with pytest.raises(FrozenInstanceError):
        result.memberships = ()


def test_existing_preprocessor_integrates_without_promoting_unknowns(algorithm):
    # Explicit invented complete rows are not needed to demonstrate transport:
    # preprocessing unknown history yields finite imputed numbers, still unknown.
    snapshot = extract_snapshot([], customer_ids=(1, 2),
                                cutoff=datetime(2026, 4, 1, tzinfo=timezone.utc))
    preprocessor = fit_preprocessor(snapshot)
    features = preprocessor.transform(snapshot)
    unknown = ClusteringBatch(features, (Validity.UNKNOWN,) * 2)
    with pytest.raises(ValueError, match="valid evidence"):
        algorithm.fit(unknown, training_snapshot_id="synthetic-unknown-history")
    # Invented eligible numeric training uses the exact upstream column/version shape.
    training = ClusteringBatch(replace(features, values=tuple(
        (float(i),) * len(features.columns) for i in (1, 3))), (Validity.VALID,) * 2)
    model = algorithm.fit(training, training_snapshot_id="synthetic-numeric-training")
    result = model.assign(unknown)
    assert result.lineage.preprocessing_version == preprocessor.version
    assert result.memberships == tuple(Membership(i, None, Validity.UNKNOWN) for i in (1, 2))
