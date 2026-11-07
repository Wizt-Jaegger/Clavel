# P0024 — As-of feature extraction

Status: Awaiting review. Base: `8b7bf97e8032d201a9951c42fc8eed5f2257b3b8`.
Prerequisite P0023 was verified Accepted by the orchestrator. Independent Codex
review is pending; this record does not assert acceptance.

## Implementation

`src/clavel/intelligence/clustering/snapshots.py` provides `extract_snapshot` over
the existing `behavioral-v1` definition. Callers supply verified telemetry,
customer IDs, an aware cutoff, optional explicit history coverage, and a policy.
It materializes one row per distinct requested customer in ascending ID order,
normalizes cutoff to UTC, consumes input iterables once, and retains no input
collections. Feature/SKU ordering is deterministic. Conflicting coverage and
visible event UUID payloads fail closed; exact retries collapse.

Each row uses the existing interval `[cutoff - lookback, cutoff)` and requires
`recorded_at < cutoff`. Thus future occurrences and late-arriving observations
cannot contribute to the earlier snapshot. Returns remain separate observations
and never erase an earlier purchase. Missing/partial coverage stays unknown;
explicitly complete empty history yields known zero frequencies.

The inputs are recommendation telemetry, including purchase and return events.
They are not accounting sales/returns. The accounting schema has no receipt
timestamps and cannot establish historical availability, so this implementation
does not infer or import accounting coverage. This is a pure extraction API,
with no persistence, provider calls, tuning, or OpenAPI/schema changes.

Example (all inputs synthetic):

```python
result = extract_snapshot(
    verified_events,
    customer_ids=[2, 1, 2],
    cutoff=cutoff,
    coverage=complete_history_at_cutoff,
)
assert tuple(row.customer_id for row in result.rows) == (1, 2)
```

## Validation evidence

All observations and coverage in the tests are invented test doubles. These
results demonstrate local mechanics only, with no live-provider acceptance.

- Baseline: `.venv/bin/python -m pytest tests/test_behavioral_features.py -q`
  — 36 passed.
- Task validation: `.venv/bin/python -m pytest tests/test_behavioral_features.py tests/test_feature_snapshots.py -q`
  — 56 passed (36 existing, 20 new), no failures or skips.
- Done-when evidence: input permutations and one-shot iterables produce identical
  dataclass values and serialized ordering. Purchases and returns at/after cutoff
  are excluded independently for both occurrence and receipt timestamps. A return
  appears only at a later eligible cutoff without changing the earlier purchase.
- Additional coverage: customer isolation; complete/partial/missing history;
  policy lookback bounds; timezone normalization; invalid IDs/cutoffs; empty
  cohorts; duplicate/conflicting coverage/events; caller collection mutation.

No task-specific live decision gate or missing input blocks this telemetry slice.
Next step: independent Codex reviewer checks the committed diff and evidence;
the orchestrator manages `log/STATUS.md` and acceptance.
