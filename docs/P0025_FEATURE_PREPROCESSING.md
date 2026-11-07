# P0025 feature preprocessing evidence

Status: Awaiting review. Acceptance belongs to the independent Codex reviewer
and orchestrator. No human signature is required. Evidence below is synthetic;
it establishes mechanics only, with no live provider or clustering-quality claim.

## Scope and use

Implementation: `src/clavel/intelligence/clustering/preprocessing.py`.
Input is the existing `FeatureSnapshot`, with `behavioral-v1` rows and a single
consistent cutoff, window and `FeaturePolicy`.

```python
from clavel.intelligence.clustering.preprocessing import (
    FittedPreprocessor, fit_preprocessor,
)

# training_snapshot contains only the caller's training partition.
fitted = fit_preprocessor(training_snapshot)
training_matrix = fitted.transform(training_snapshot)
artifact_json = fitted.to_json()

# Reload the same artifact for validation or inference; do not refit here.
loaded = FittedPreprocessor.from_json(artifact_json)
inference_matrix = loaded.transform(inference_snapshot)
assert inference_matrix.preprocessing_version == training_matrix.preprocessing_version
```

The caller owns the training/validation split. No customer ID or timestamp enters
the numeric matrix. Output preserves input row order and carries customer IDs
separately. Empty training is rejected; empty inference returns an empty matrix.

The 12 numeric columns are frequency and recency in `EVENT_TYPES` order
(`exposure`, `click`, `add_to_cart`, `purchase`, `return`), then interaction count
and active days. Twelve corresponding `missing.<column>` indicators follow.
Product affinities need a separate vocabulary definition and are not selected;
the cold-start label is not used as a numeric feature or eligibility decision.

Each median uses observed training values only. After median imputation, training
values determine the mean and population standard deviation. Inference applies
`(imputed_value - training_mean) / training_scale` without changing parameters.
An entirely missing column uses median/mean zero; a constant column uses scale
one. A missing indicator of one always accompanies an imputed input, including
absence first encountered at inference. Original snapshots remain unchanged.
Imputation does not establish verified history or eligibility.

The immutable JSON artifact contains ordered input columns, format version,
training cutoff/row count, feature policy, medians, means and scales. Its SHA-256
identity changes with those contents, and is included in every output matrix.
Reload validates the schema and identity; the digest is not authentication.
Inference rejects incompatible definitions/policies, inconsistent row windows,
missing/extra selected columns, duplicate customers, negative/nonfinite values
and invalid types (including booleans). No REST/OpenAPI migration is introduced.

## Validation for independent review

Command (project-local environment):

```sh
.venv/bin/python -m pytest -q tests/test_feature_preprocessing.py tests/test_feature_snapshots.py tests/test_behavioral_features.py
```

Result: **91 passed, 0 failed**. `git diff --check` also passed.

- Missingness: observed zero, partial/missing history, all-missing and constant
  columns, and new missing inference values retain explicit indicators.
- Train-only fit: synthetic `[1, 3, None]` yields median/mean 2 and population
  scale `sqrt(2/3)`; held-out 101 transforms with those exact statistics. Inference
  leaves serialized parameters unchanged.
- Versioning: JSON round trip reproduces transforms; reordered training rows
  retain identity; changed parameters, cutoff or policy change identity.
- Invalid schema: both fit and inference fail closed for incompatible feature
  definitions, columns, types, timestamps, duplicates and policies. Corrupt,
  malformed and unsupported artifacts are rejected.

No task-specific live gate or missing input was identified. `log/STATUS.md` is
owned by the orchestrator and was not edited by this task.
