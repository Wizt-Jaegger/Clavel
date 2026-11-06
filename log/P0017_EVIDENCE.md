# P0017 review evidence

Status: Awaiting review. Base: `ef48ebc82e27f484fdb31c02f4c0a7e083ff0baa` on `main`.
Prerequisites were verified Accepted by the orchestrator. No task-specific live
provider gate applies. Independent reviewer/orchestrator acceptance is pending;
no human signature is required.

## Implementation

- `src/clavel/database/sales_repository.py`: `SalesRepository.record_order`
  stores a complete order and its lines using source IDs. An identical replay
  returns the existing order ID. A changed header, line payload or complete line
  set raises `SalesConflict`. Input line ordering is immaterial.
- `record_returns` resolves original sale lines by source system, source order
  ID and source sale-line ID. It atomically writes an incremental return-line
  batch. Each source return ID/return-line ID pair is immutable, including the
  original sale link, and exact replays return existing row IDs in input order.
  Missing and cross-source sale references raise `UnknownSale`.
- Each call uses a savepoint inside the caller's transaction, including when
  the connection starts idle. Caught failures leave no partial order or batch.
  Calls do not commit; multiple calls share the caller's unit of work.
- Parent sale lines are locked in ID order before writing returns. Existing
  migrated PostgreSQL constraints/triggers enforce exact numeric precision,
  foreign keys and cumulative return limits. Serialization/deadlock failures
  must be retried at the caller's whole transaction boundary.
- Missing customer/cost values remain NULL; exact amounts require Decimal.
  No schema, migration or REST/OpenAPI changes.

## Validation

All evidence below uses synthetic records on locally provisioned disposable
PostgreSQL with real migrations and transactions. It proves repository
mechanics only, not live feed quality or provider acceptance.

```text
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q tests/integration/test_sales_repository.py
27 passed in 20.28s (initial implementation)

CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q tests/integration/test_sales_repository.py tests/integration/test_sales_return_schema.py tests/test_database.py
93 passed, 1 warning in 60.43s (final implementation; no skips)
```

The final suite includes 29 repository cases: exact replays after reconnect,
changed payloads and links, source scoping, partial order/batch failure,
cumulative over-return, caller rollback, invalid inputs, competing identical
and conflicting orders, concurrent return replay/over-return, and multi-sale
return batches supplied in opposite orders. Existing schema and database
transaction tests also pass. The warning is a dependency deprecation from
FastAPI/Starlette test client usage.

Open implementation blockers: none. Next: independent Codex review and
orchestrator status update. `log/STATUS.md` was not edited by this task.
