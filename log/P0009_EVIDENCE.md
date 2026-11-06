# P0009 migration workflow evidence

Status: Awaiting review. Independent Codex review owns acceptance.
Base: `b51440dbaec8ef76e00a2eba03854097a1b03707`; branch: `main`.
P0008 prerequisite was verified Accepted by the orchestrator, as supplied in the
assignment. No provider decision gate applies to this task.

## Implementation

- Alembic history/configuration uses Clavel settings and the psycopg dialect;
  connection credentials are absent from committed configuration.
- Initial revision is an empty baseline, preserving later domain-schema scope.
- Revision template supports explicit upgrade/downgrade; PostgreSQL DDL and
  version changes run in a transaction. Startup does not apply migrations.
- CI provisions PostgreSQL 17, installs into `.venv`, and requires disposable
  database integration tests; absent PostgreSQL cannot produce a skipped success.
- Migration usage and downgrade/data-loss limits: `migrations/README.md`.

## Observed local validation

Environment: Python 3.13.15; PostgreSQL 17.11; Alembic 1.20.1;
SQLAlchemy 2.1.8. All roles, databases, credentials and values were synthetic.
These are real local PostgreSQL executions, not test doubles or live provider
acceptance. Every temporary cluster was stopped. The TCP harness directory was
removed; pytest manages its own temporary cluster directories.

| Check | Command / configuration | Result |
| --- | --- | --- |
| Install | `.venv/bin/python -m pip install -e '.[dev]'` | Passed |
| Migration + relevant regression | `CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest tests/integration tests/test_database.py tests/test_project_smoke.py -q --tb=short` | 12 passed, zero skips; existing Starlette/httpx deprecation warning |
| CI connection path | `.venv/bin/python -m pytest tests/integration -q --tb=short`, with required mode and `CLAVEL_MIGRATION_TEST_URL` set to a temporary TCP server using SCRAM authentication | 2 passed, zero skips |
| Dependencies | `.venv/bin/python -m pip check` | No broken requirements |
| Version graph | `.venv/bin/python -m alembic heads` | Single head: `0001_migration_baseline` |
| Whitespace | `git diff --check` | Passed |

The integration checks assert empty-database upgrade, idempotent repeated
upgrade, downgrade to base and re-upgrade; a generated synthetic revision's
actual table/data creation and removal; and rollback of both DDL and version
state after an expected division-by-zero failure. CI-URL mode creates and drops
a uniquely named database without migrating its administrative database.

The first run had two fixture-URL failures (10 other checks passed). The fixture
now replaces only the database URL path, retaining Unix socket query options;
the successful runs above followed that correction. Full event history is in
`log/CODEX_LOG.md`.

## Review handoff

No known open implementation blockers. Hosted GitHub Actions was not executed
from this workspace; the same integration entry point passed locally with the
CI connection mode and PostgreSQL major version. No production/provider behavior
or business-data quality was evaluated. The pre-existing orchestrator changes
to `log/STATUS.md` were left untouched and are excluded from the task commit.
Next step: independent Codex reviewer checks the committed diff and evidence.
