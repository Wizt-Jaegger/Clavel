# P0013 sales and return schema

Status: Awaiting review. Acceptance belongs to the independent Codex reviewer
and orchestrator; no human signature or live provider acceptance is claimed.

## Storage contract

- `sales_orders`: unique `(source_system, source_order_id)`, an optional customer
  link, an explicit finite `sold_at` instant and required currency. Identifiers
  are case-sensitive, opaque, nonempty and have no surrounding spaces; they
  must not contain personal data. Missing customer attribution stays NULL.
- `sales_lines`: unique `(order_id, source_line_id)`, a required catalog SKU,
  positive quantity, nonnegative unit price and nullable nonnegative unit cost.
  A composite foreign key enforces the order's source namespace. NULL cost is
  unknown; zero cost is known zero. No cost, currency or attribution is inferred.
- `sales_returns`: unique `(source_system, source_return_id, source_line_id)`,
  a required sale-line link in the same source namespace, positive quantity
  and an explicit finite `returned_at` instant. Several return lines may link
  to one sale line, but their cumulative quantity cannot exceed that sale.
  SKU, currency and original unit amounts are reached through the linked sale;
  no independent currency conversion or refund/tax amount is modeled here.

These are local canonical storage choices, not a vendor protocol. Currency
requires three uppercase ASCII letters; this validates syntax only, not ISO
membership or provider support. Callers must supply timezone-aware source times.
There is no default source ID, currency, cost or observation time. Unknown required
inputs must be resolved before insertion, never replaced with invented values.

## Decimal and return safeguards

Amounts use PostgreSQL `NUMERIC`, with checks requiring at most four fractional
places and `0 <= amount < 1000000000000000` (up to 19 significant digits).
Quantities use `NUMERIC`, with at most six fractional places and
`0 < quantity < 1000000000000`. NaN, infinities, negative amounts and out-of-range
or excess-precision values fail constraints rather than being rounded by a
`NUMERIC(p,s)` cast. Pass Python `Decimal` values, not binary floats. Calculated
line totals are not stored or rounded by this schema.

Return INSERT/UPDATE/DELETE triggers write the parent sale line's unchanged
non-key unit-price column before checking the sum. This serializes return
writers with each other and with sale quantity updates while allowing foreign
key key-share locks. Under REPEATABLE READ/SERIALIZABLE a stale concurrent writer
must retry its entire transaction after a serialization failure. Sale quantity
cannot be reduced below already returned quantity. Return links are immutable;
correcting a link requires a transactional delete and reinsert. Foreign keys
block deletion of referenced sales, SKUs and customers; nothing cascades away.
Direct SQL is guarded, not just future repositories. Use Alembic migrations;
`metadata.create_all()` does not install the procedural safeguards.

## Migration and review evidence

Revision `0005_sales_return_schema` follows `0004_customer_session_schema`.
Upgrade adds only the three sales tables, constraints, index and trigger functions;
existing catalog, inventory and customer/session rows are preserved. Downgrade
removes these sales objects and **deletes all sales and returns data**; back up
those records before an intentional rollback. Re-upgrade creates empty sales
tables. No REST/OpenAPI contract changes are included.

All test records and infrastructure are synthetic/disposable. Native PostgreSQL
tests establish storage mechanics, not live integration or provider mapping.
The focused suite covers duplicate order/line/return IDs, source namespace and
foreign keys, exact decimal round trips, NULL versus zero cost, malformed inputs,
partial and excessive returns, mutation/deletion behavior, concurrent returns
and sale reduction at READ COMMITTED/REPEATABLE READ/SERIALIZABLE, metadata parity,
and upgrade/downgrade/re-upgrade with prior data preservation.

Validation on 2026-11-06, using the project-local `.venv` and
`CLAVEL_REQUIRE_POSTGRES=1`:

- `python -m pytest tests/integration/test_sales_return_schema.py -q`:
  **55 passed**, zero failures/skips.
- `python -m pytest tests/integration/test_migrations.py tests/integration/test_catalog_schema.py tests/integration/test_inventory_schema.py tests/integration/test_customer_session_schema.py -q`:
  **82 passed, 1 failed** initially. The sole failure was an existing catalog
  migration assertion listing the old tables; its expectation now includes the
  three new sales tables.
- `python -m pytest tests/integration/test_catalog_schema.py::test_catalog_upgrade_downgrade_upgrade -q`:
  **1 passed** after that correction. No unresolved test failures or skips.
- `git diff --check`: passed.

Exact commands and results are recorded in `log/CODEX_LOG.md`. No task-specific
live gate is listed in P0013. Vendor mappings remain outside this task's scope.
