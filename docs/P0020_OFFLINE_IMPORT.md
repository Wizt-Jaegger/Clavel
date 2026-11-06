# P0020 offline canonical import

Status: Awaiting review. Evidence below uses hand-authored synthetic inputs and
disposable native PostgreSQL, not a provider feed. Q01/Q02 production-feed
verification remains Blocked until the required provider decisions and inputs
are available. Independent Codex review determines acceptance.

## Run

Install the project in `.venv` and apply migrations to the intended PostgreSQL
database first. Set `DATABASE_URL` in the process environment through your local
configuration mechanism; never put credentials in arguments, reports or commits.
The command reads environment settings only, ignoring `.env` and `.env.shared`.

```sh
.venv/bin/python scripts/import_canonical.py synthetic.jsonl --dry-run
.venv/bin/python scripts/import_canonical.py synthetic.jsonl
# Equivalent installed-package entry point:
.venv/bin/python -m clavel.data.offline_import synthetic.jsonl
```

Input is UTF-8 JSONL: one canonical v1 object per physical line, using the
[P0019 contract](../src/clavel/data/README.md). Both sale and return rows are
supported. Exact JSON decimal numbers and decimal strings retain precision.
Blank lines, duplicate JSON keys, nonfinite numbers, out-of-range JSON numeric
exponents, malformed JSON, unsupported versions and empty files are rejected.
Files are buffered in memory; operators
must bound their size and split large inputs at complete-order boundaries.

Hand-authored synthetic example, with no vendor provenance:

```jsonl
{"contract_version":"v1","record_type":"sale","source_system":"synthetic-pos","source_order_id":"synthetic-order","source_line_id":"synthetic-line","sku":"SYNTHETIC-SKU","sold_at":"2026-01-01T12:00:00Z","currency":"MXN","quantity":"10","unit_price":"12.3456"}
{"contract_version":"v1","record_type":"return","source_system":"synthetic-pos","source_order_id":"synthetic-order","source_line_id":"synthetic-refund-line","source_return_id":"synthetic-refund","sale_source_line_id":"synthetic-line","quantity":"4","returned_at":"2026-01-02T12:00:00Z"}
```

An SKU with that exact code must already exist. A supplied `customer_ref` must
resolve to an existing opaque customer reference; unresolved references fail.
Omitted customer/cost remain NULL, distinct from known zero cost. The importer
creates no customers, sessions, catalog records or stock observations and infers
no demographics, compatibility or recommendation eligibility. Source systems
are explicit operator-supplied namespaces, not verified provider identities.

## Atomicity and reruns

One file is one batch and one database transaction. Every physical row is
validated before opening a connection. Sale rows are grouped by
`(source_system, source_order_id)` and must agree on normalized time, currency
and customer reference. Duplicate sale line keys and duplicate return/line keys
within the file fail, including identical duplicates. The operator must supply
the complete line set for each order; the importer cannot prove upstream
completeness for a newly seen order.

All sales are written before linked returns, irrespective of input row order.
Existing repository savepoints and PostgreSQL constraints enforce immutable
headers/line sets, source-scoped sale links and cumulative return limits. Any
validation, resolution, replay, constraint or database error rolls back the
entire file, including earlier orders. Runtime reports stop at the first failed
group; the whole file remains uncommitted. No cross-file atomicity is promised.

Replaying the same complete orders and returns is a successful no-op on stored
records. Normalized currency/time spellings and line ordering may differ. A
changed immutable payload, missing/extra order line or relinked return rejects
the entire file. Returns can be imported incrementally against existing sales.
After a failure, correct the complete file and rerun it; after an uncertain
connection/commit outcome, replay the exact file to reconcile safely. Concurrent
deadlock/serialization errors return an unavailable report; retry the complete
batch rather than a suffix. No automatic retry changes the intended input.

`--dry-run` executes the same repository writes and constraints, then rolls back
before success is reported. It requires write privileges and takes normal
transaction locks. No imported table rows persist; PostgreSQL sequences can
advance during dry runs, failed attempts and replays, so ID gaps are expected.
Use disposable infrastructure for synthetic checks. A successful dry run checks
the database at that time and does not reserve state for a later import.

## Reports

Stdout contains one JSON report; redirect it to a separate file if needed.
Never redirect onto the input file. Exit codes: `0` imported/dry run, `1` rejected
batch, `2` configuration/database unavailable (also argparse usage errors).

`row_count` is the number of physical lines read; `processed_rows` is the number
processed on success, including replays, and zero on failure. It is not a count
of newly inserted records. Warnings such as `unknown_cost` do not reject a batch.
Diagnostics contain only 1-based physical row positions, allowlisted field names,
fixed codes and severity; position `0` identifies a batch-level failure. A
repository group failure reports all positions in that group rather than
guessing which member caused it. Raw values, unknown field names, exception
messages, SQL and connection details are never included. For example:

```json
{"status":"rejected","row_count":1,"processed_rows":0,"diagnostics":[{"row_number":1,"field":"quantity","code":"invalid_value","severity":"error"}]}
```

## Reviewer evidence

```sh
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q tests/integration/test_offline_import.py tests/test_import_validation.py tests/test_repository_rules.py
```

Validation result: **247 passed, 7 subtests passed, 0 failed, 0 skipped** (21.32s). PostgreSQL was
mandatory via `CLAVEL_REQUIRE_POSTGRES=1`; no skipped check counts as evidence.

The rejected attempt's numeric-exponent failure was reproduced before the fix
(one failing CLI test). Eight regression cases now cover positive and negative
numbers with out-of-range positive and negative exponents, in import and dry-run
modes. Each returns exit code 1, a positional `invalid_json` JSON diagnostic,
empty stderr and no persisted batch rows; input values remain redacted.

`test_cli_dry_run_import_replay_and_bad_row_on_postgres` runs the actual command
against a disposable migrated PostgreSQL database: dry run leaves no rows,
valid input imports, reordered replay preserves every stored row, and a bad
second row returns a redacted rejection with no database changes. Additional
cases check complete-order replay, late-group rollback in both modes, unknown
SKU/customer/sale resolution, return limits, namespace isolation, NULL versus
zero, exact numeric JSON tokens and safe errors. The driver-failure injection
case is explicitly test-double evidence for error handling; PostgreSQL constraint
and CLI lifecycle cases use the real disposable database. No production feed,
provider authentication or live Q01/Q02 acceptance is claimed.
