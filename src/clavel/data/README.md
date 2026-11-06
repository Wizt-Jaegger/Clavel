# Canonical fixture input v1 (P0019)

Status: Awaiting review. Evidence is synthetic; Q01/Q02 live vendor mapping is
Blocked pending provider decisions. These contracts add no HTTP endpoints,
OpenAPI changes, migrations or database writes.

Use `clavel.data.import_validation.validate_rows(iterable_of_dicts)`. The result
contains normalized `rows` with 1-based `row_number`, and `diagnostics` with
`row_number`, `field`, `code` and `severity`. `valid` means no row errors. Inspect
valid rows from a failed batch only as fixture evidence; do not import that
batch. An empty iterable is structurally valid and makes no completeness claim.

Every row requires explicit `contract_version: "v1"`, `record_type`,
`source_system`, `source_order_id`, `source_line_id` and `quantity`.

| Kind | Additional required fields | Optional fields |
| --- | --- | --- |
| `sale` | `sku`, `sold_at`, `currency`, `unit_price` | `unit_cost`, `customer_ref` |
| `return` | `source_return_id`, `sale_source_line_id`, `returned_at` | None |

For returns, `source_line_id` identifies the return line, and
`source_order_id`/`sale_source_line_id` identify the original sale. All identifiers
must be opaque, nonempty strings with no outer whitespace or Unicode control,
format or other category-C characters. Case is preserved; identifiers are never
converted from integers. The caller must supply references without personal data.

Timestamps accept aware Python datetimes or ISO strings with `T`, seconds,
optional 1–6 fractional digits and `Z` or `±HH:MM`. They normalize to UTC. Naive,
malformed, unknown `-00:00` offsets and UTC overflow fail. No timezone is inferred.

Currency accepts three ASCII letters, trims outer whitespace and uppercases.
This checks syntax only, not a currency registry or conversion. A return cannot
override the original sale's currency.

Amounts/quantities accept exact `Decimal`, integers (excluding booleans), or
plain decimal strings; strings may have outer whitespace and a leading sign.
Floats, exponent strings, separators and nonfinite values fail. Quantity must be
positive, below 10^12 and have at most six significant fractional places. Price
and cost must be nonnegative, below 10^15 and have at most four significant
fractional places. Insignificant trailing zeros are allowed; no rounding occurs.
Omitted/null cost stays `None` with an `unknown_cost` warning, distinct from zero.
Omitted/null customer remains `None`. Blank values do not mean unknown.

Synthetic example (hand-authored, no provider provenance):

```python
from clavel.data.import_validation import validate_rows

result = validate_rows([{
    "contract_version": "v1", "record_type": "sale",
    "source_system": "synthetic-pos", "source_order_id": "synthetic-order",
    "source_line_id": "synthetic-line", "sku": "SYNTHETIC-SKU",
    "sold_at": "2026-01-01T06:00:00-06:00", "currency": " mxn ",
    "quantity": "2.123456", "unit_price": "12.3456",
}])
assert result.valid
assert result.rows[0].value.currency == "MXN"
assert result.rows[0].value.unit_cost is None
assert result.diagnostics[0].code == "unknown_cost"
```

Unsupported/missing versions, unknown record kinds, missing required fields and
extra fields fail closed. Diagnostics expose only known contract field names and
fixed codes (`unsupported_version`, `invalid_record_type`, `invalid_row`,
`required`, `unexpected_field`, `invalid_value`, `unknown_cost`), never raw values
or unexpected field names. Breaking input changes require a new version and
explicit mapping; v1 is never silently reinterpreted.

This is row validation only. A future assembler/resolver must verify source
namespaces, SKU/customer existence, complete orders, consistent repeated headers,
duplicates/replays, sale links and cumulative return quantities in repository
transactions. Unknown identifiers are not proof of existence. No demographic,
stock, compatibility or recommendation eligibility conclusions follow.

Reviewer evidence: `.venv/bin/python -m pytest -q tests/test_import_validation.py`
exercises malformed timestamps/currency, missing cost versus zero, invalid
identifiers, exact numeric boundaries, return links, version handling, input
immutability, deterministic row positions and diagnostic redaction. All fixtures
are explicitly synthetic; no live importer was exercised or accepted.
