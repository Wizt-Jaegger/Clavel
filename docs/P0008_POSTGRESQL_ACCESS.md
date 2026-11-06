# P0008 PostgreSQL access and review evidence

Status: Awaiting review. Independent Codex review owns acceptance.

## Proposed additive runtime contract

Before implementation: the runtime OpenAPI paths contain only `/health`.
After implementation: add `GET /ready`; retain the process-only `/health`.
The design-time `/v1` draft is unchanged.

| Operation | HTTP | JSON example (synthetic) |
| --- | --- | --- |
| GET /health | 200 | `{"status":"ok"}` |
| GET /ready, PostgreSQL responds to SELECT 1 | 200 | `{"status":"ok"}` |
| GET /ready, PostgreSQL connection/query fails | 503 | `{"error":{"code":"database_unavailable","message":"Database unavailable"},"request_id":"synthetic-ready-1"}` |

`/ready` declares the existing HealthResponse on 200 and ErrorResponse on
503/500. The shared ErrorCode enum gains `database_unavailable`, so generated
clients must regenerate if they exhaustively match this enum. Both responses
retain X-Request-ID correlation. No database details cross the HTTP boundary.

Migration impact: no schema/data migration and no new dependency. Existing
liveness probes keep `/health`; deployment readiness probes may adopt `/ready`.
A database outage does not prevent app startup or the liveness response.
Connectivity is checked per readiness request, not cached as verified.
This proposal and examples precede the implementation; implementation and
runtime schema assertions will be presented to the independent reviewer.

## Session and transaction boundaries

`Database(settings)` stores a SecretStr and opens no connection. Startup and
`/health` do not contact PostgreSQL. `app.state.database.session()` opens one
connection and transaction per unit of work: commit on normal exit, rollback
on an escaping exception, and unconditional close, including failed commit.
Concurrent sessions never share a connection. Callers must let errors escape
the block and must not commit midway through the unit of work.

Connections use a 3-second connect timeout and a 3-second statement timeout.
A multi-host DSN can multiply connection attempts; these are per-attempt and
per-statement limits, not a total request deadline. `/ready` runs synchronous
I/O in FastAPI's worker thread pool, executes SELECT 1 on a fresh session,
and returns a redacted 503 on psycopg errors. No connection pool is introduced;
there are no persistent database resources to dispose at app shutdown.

## Validation evidence

Validated on postgres (PostgreSQL) 17.11, Python 3.13.15, psycopg 3.3.8.

```sh
.venv/bin/python -m pytest -q tests/test_database.py tests/test_api_shell.py tests/test_openapi_contract.py tests/test_settings.py tests/test_project_smoke.py
git diff --check
```

Result: **315 passed, zero skipped**, with one Starlette/httpx deprecation
warning. Diff whitespace check passed. No dependency changes were needed.

- Synthetic doubles: lazy startup/liveness, repeated failed probes, recovery,
  error redaction/correlation, worker-thread execution, runtime schema.
- Actual disposable local PostgreSQL with synthetic role/data, Unix socket
  only: connectivity, SELECT 1 readiness, effective statement timeout,
  committed writes visible to a fresh session, rollback after application
  failure and SQL failure, rollback/close after deferred-constraint commit
  failure, and concurrent connection isolation.
- Actual psycopg against a nonexistent local Unix socket: unavailable-database
  exception, readiness 503, liveness 200.

The first targeted run found a connection leak on a deferred-constraint
COMMIT failure (301 passed, 1 failed). Explicit finally-close fixed it; the
regression passed in the final run. The test fixture stops its PostgreSQL
cluster in finally. PostgreSQL integration tests skip explicitly when native
initdb/pg_ctl or a non-root user are unavailable; skips cannot satisfy the
connectivity/rollback acceptance check.

These results prove local mechanics with synthetic data, not deployment,
production credentials, business data, or live provider acceptance. No live
provider decision is required by this task. Open item: independent Codex
review of this implementation, proposal and evidence; acceptance remains
with the reviewer/orchestrator. `log/STATUS.md` remains orchestrator-owned.
