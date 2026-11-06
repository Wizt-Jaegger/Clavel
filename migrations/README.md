# PostgreSQL migrations

Install the project and dev dependencies into `.venv` as described in the root
README. Run commands from the repository root. Alembic uses Clavel's validated
`DATABASE_URL` setting (environment overrides `.env`, then `.env.shared`). Keep
real credentials in the environment or ignored local files, never in commands,
migration files, or `alembic.ini`. Migrations run explicitly, outside app startup.

```sh
.venv/bin/python -m alembic current
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic downgrade -1
.venv/bin/python -m alembic upgrade head
```

The initial revision establishes version history without domain tables. An
empty database upgraded to head contains only `alembic_version`. Downgrading
to `base` leaves that table empty; upgrading again restores the recorded head.
PostgreSQL DDL and revision updates share a transaction: a failed migration
rolls both back. Take a backup and assess data loss before a production downgrade;
reversing schema changes cannot restore data dropped by a revision.

Create a new revision after the current head:

```sh
.venv/bin/python -m alembic revision -m "describe schema change"
.venv/bin/python -m alembic heads
```

Fill in both `upgrade()` and `downgrade()` using Alembic operations or explicit
SQL. Use a single linear history. Review generated SQL and test the revision on
PostgreSQL before committing. Automatic model generation is not configured:
the application currently uses psycopg without ORM metadata. Never edit an
already applied revision. Add a new revision to correct it.

## Disposable integration checks

```sh
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest tests/integration -q
```

Locally these tests start a temporary native PostgreSQL cluster using
`initdb`/`pg_ctl`, trust authentication on a private Unix socket, no TCP listener,
and a synthetic role. They create and drop one uniquely named test database per
test. No application `.env` database is contacted. Without native binaries (or
under root), checks skip unless `CLAVEL_REQUIRE_POSTGRES=1`, which fails instead.

CI sets `CLAVEL_MIGRATION_TEST_URL` to its disposable PostgreSQL service. For
other environments set this variable only to a dedicated synthetic PostgreSQL
instance whose role may create databases. Each check still creates a fresh
database and removes it afterward. The CI job requires PostgreSQL and cannot
succeed by skipping these checks.

Evidence covers a baseline round trip, an additional generated synthetic
revision with real DDL and data, and transactional failure recovery. All data
and credentials are synthetic. This validates migration mechanics on PostgreSQL,
not a live provider, production schema, or business-data acceptance.
