# P0016 review evidence

Status: Awaiting review. Independent Codex review remains pending.

Implementation: `src/clavel/database/repositories.py`.
Tests: `tests/integration/test_repositories.py`.

- Catalog reads cover categories, SKUs and typed hardware attributes. Upserts
  retain identity on natural-key conflicts and replace supplied values atomically.
- Stock reads distinguish missing observations, unknown quantities, zero and
  positive quantities. Upserts retain source versions and observation times.
  Duplicate/replayed versions and regressions fail through the existing trigger.
- Repositories share a caller-owned `Database.session()` transaction. Failed
  catalog or stock writes roll back the entire unit of work, across repositories.
- Concurrent initial inserts and updates retain the newest stock version.
  Equal-version writers allow exactly one commit. Catalog concurrent writes
  retain one identity and consistent attribute values.
- Collection-specific, validated cursors use immutable IDs. Tests cover updates,
  inserts, deletion of the cursor boundary, replay, empty pages and exact limits.
  A repeatable-read traversal proves snapshot behavior across concurrent writes.

Validation (project-local virtual environment, PostgreSQL required; no skips):

```text
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest tests/integration/test_repositories.py -q --tb=short
20 passed
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest tests/test_database.py tests/integration/test_catalog_schema.py tests/integration/test_inventory_schema.py -q --tb=short
60 passed, 1 existing dependency deprecation warning (Starlette/httpx)
```

Evidence uses synthetic records, disposable local PostgreSQL and existing unit
test doubles. It proves storage mechanics only. No live-provider evidence or
eligibility/freshness claim is made. READ COMMITTED pages are not snapshots;
late commits behind a cursor are not replayed. Catalog metadata has no source
version and uses last-writer-wins semantics. No task-specific live gate or
missing input was encountered. API contracts and database migrations are unchanged.
