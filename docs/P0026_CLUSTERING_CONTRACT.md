# P0026 clustering interface

Status: Awaiting review. Evidence is synthetic/test-double only; no live
provider, clustering quality, tuned threshold or acceptance claim.

`src/clavel/intelligence/clustering/contracts.py` defines `clustering-v1`:

- `ClusteringAlgorithm.fit(batch, training_snapshot_id=...)` accepts a nonempty
  training batch with explicitly valid evidence, and returns `FittedClustering`.
  Implementations supply `_fit` and a versioned algorithm identity.
- `FittedClustering.assign(batch)` reuses the fitted state without refitting.
  Implementations supply `_assign` for eligible rows only, returning exactly one
  membership per eligible customer in input order. Empty inference is supported.
- `ClusteringBatch` carries the existing `PreprocessedSnapshot` plus one required
  `Validity` per row. Finite imputed numbers do not establish evidence validity.
  Callers derive validity from source evidence; this task adds no eligibility
  threshold or serving policy. Unknown, insufficient and unavailable inputs
  bypass the implementation and retain their flags with no segment.
- `ClusteringResult` retains immutable model lineage and ordered memberships.
  Only valid memberships carry a nonnegative integer segment ID (zero is valid).
  An implementation can return unavailable with no segment; exceptions propagate
  rather than becoming successful assignments. Segments are local to a model
  version, with no cross-version equivalence implied.

Lineage binds the contract, algorithm, model, training snapshot, preprocessing
version and ordered columns. The caller supplies an immutable training snapshot
identity; the implementation must version its exact fitted parameters. These
opaque identifiers are not authentication or evidence of live provenance.
Fit verifies the returned lineage against its inputs; assign rejects changed
preprocessing or column identity. Model implementations must keep fitted state
immutable; the boundary also checks lineage did not change during assignment.

Example: fit explicitly valid synthetic rows with values 1 and 3 and snapshot
ID `synthetic-training-001`; the test double learns threshold 2. Assigning a
valid row with value 100 returns segment 1. Assigning an unknown row with the
same number returns `segment_id=None, validity=unknown` under the same lineage.

The internal Python contract adds no REST/OpenAPI changes, dependencies,
persisted models or database migration. Future clustering implementations
subclass the interfaces and run `ClusteringContractSuite` with their own
`algorithm` fixture; the current test implementation is an invented threshold
double, not the production BIRCH algorithm. Tuning and LLM decisions are out of
scope. Consumers must use matching preprocessing versions and column order.

Review command (project-local environment):

```sh
.venv/bin/python -m pytest -q tests/test_clustering_contract.py tests/test_feature_preprocessing.py tests/test_feature_snapshots.py tests/test_behavioral_features.py
```

The suite covers fit/assign/result behavior, lineage mismatches, schema and
version rejection, row identity/order, invalid numbers, nonvalid evidence,
immutability, backend failures and transport from the existing preprocessor.
Validation: **148 passed**, including the reusable contract suite and upstream
feature/preprocessing tests, using Python 3.13.15 and pytest 9.2.0 in `.venv`.
The implementation commit and command results are recorded in `log/CODEX_LOG.md`.
No missing task inputs or required live provider decisions were found for this
internal contract. Acceptance belongs to the independent reviewer/orchestrator.
