# Synthetic fixtures (P0021)

Generate a bundle locally, using the project environment:

```sh
.venv/bin/python scripts/generate_fixtures.py --seed 21 --output /tmp/clavel-synthetic.json
```

The output path's parent must exist; existing files are never overwritten.
Optional `--skus` (default 12, minimum 5), `--subjects` (8, minimum 4), and
`--sales` (24, minimum 3) control size. The Python API is
`clavel.data.synthetic_fixtures.generate_fixtures`, with keyword-only parameters
of the same names. `serialize_fixtures` produces sorted JSON with a final newline.
Identical parameters and generator version in the same supported Python runtime
produce identical bytes. The generator uses a private seeded RNG and fixed UTC
times; it reads no environment, network, provider dataset or wall clock.

`fixture_version: v1` describes this offline bundle, not an HTTP contract.
`provenance.synthetic: true` and `provenance.scope: all nested records` mark
every category, SKU, inventory observation, subject, sale, return and scenario.
Keep provenance with any extracted records. All references have a `synthetic-`
prefix and sale/return `source_system` is `synthetic-p0021`. Values are invented;
no demographics, personal data or provider mapping is inferred.

Collections and links:

| Collection | Identity and references |
| --- | --- |
| `categories` | `code` |
| `catalog` | `sku`; `category_code` references categories; typed unknown compatibility |
| `inventory` | `sku` references catalog; stock, source version, observation time |
| `subjects` | `opaque_ref`; explicit anonymous or registered kind and UTC activity |
| `sales` | Canonical v1; `(source_system, source_order_id, source_line_id)`; catalog SKU and nullable subject reference |
| `returns` | Canonical v1; `(source_system, source_return_id, source_line_id)`; original sale source/order/line |
| `cold_start` | Catalog SKU and both subject kinds reserved without purchases |

Sale quantities and amounts are exact decimal strings. Missing customer and cost
remain null; known zero cost is a separate case. Returns occur after their sale,
including two partial returns against one sale; cumulative quantities never
exceed sold quantities. Each order contains one line. `sales + returns` can be
checked with the existing `validate_rows` function. The bundle itself is JSON,
not the canonical importer's JSONL input; it does not write or seed a database.
Database fixtures need to create categories, SKUs and subjects before importing
the extracted sale/return rows, retaining this provenance alongside them.

Inventory includes positive, zero, null, stale-positive (30 days before the
fixed `as_of`) and absent observations. These are synthetic scenario states
relative to `as_of`, not current availability. No freshness policy or eligibility
is inferred. Unknown compatibility stays unknown for every SKU. Cold-start
lists guarantee at least one new SKU and one subject of each kind; other subjects
or SKUs may also lack sales. These data do not model representative populations,
vendor behavior or business intelligence.

Reviewer command:

```sh
.venv/bin/python -m pytest -q tests/test_synthetic_fixtures.py tests/test_import_validation.py
```

Validation on 2026-11-06: **221 passed**, including 17 generator checks and
204 existing canonical validation checks. Generator evidence includes minimum,
default and larger bundles, odd subject counts, positive/negative/zero seeds,
cross-process byte equality with different hash seeds, foreign-reference and
cumulative-return checks, cold starts and CLI failure handling. No PostgreSQL or
live provider was used for this fixture-only task.

Evidence is synthetic mechanics only. Live representativeness remains Blocked
on Q03/Q04/Q08 and real source inputs; no live acceptance is claimed. Task state
is Awaiting review after validation; the independent reviewer and orchestrator
resolve acceptance automatically.
