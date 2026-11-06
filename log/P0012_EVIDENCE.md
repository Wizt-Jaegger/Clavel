# P0012 inventory schema evidence

Status: Awaiting review. Acceptance belongs to the independent Codex reviewer
and orchestrator. Prerequisite P0011 was already verified Accepted by the caller.

## Storage behavior

- Migration `0003_inventory_schema` follows `0002_catalog_schema`; metadata is
  registered through `clavel.database.inventory` in the Alembic environment.
- One inventory observation per catalog SKU, protected by a primary/foreign key.
  `sellable_stock` is a nullable, nonnegative integer count. Missing rows and NULL
  stock mean unknown; zero is an explicitly observed zero. There is no stock default.
- `source_version` is a required nonnegative integer, and `observed_at` is a
  required finite timestamp with time zone. Observation time has no default.
- A database trigger requires a strictly greater version and nonregressing
  observation time on every update, including `ON CONFLICT DO UPDATE`. Replays
  and stale updates raise `23514` with constraint `inventory_update_fresh` and
  preserve the previous row. SKU identity cannot be reassigned by an update.
- Concurrent upserts serialize at the row; an older writer cannot replace a
  newer committed observation. Downgrade removes the table/function and preserves
  catalog records; re-upgrade restores both constraints and the trigger.

## Validation

Command (project-local environment, existing synthetic PostgreSQL service):

```sh
CLAVEL_REQUIRE_POSTGRES=1 CLAVEL_MIGRATION_TEST_URL='postgresql://synthetic_p0012@localhost:55412/postgres?host=/tmp/clavel-p0012-review-yu3u2ss7/socket' .venv/bin/python -m pytest -q tests/integration/test_inventory_schema.py tests/integration/test_catalog_schema.py tests/integration/test_migrations.py
```

Current attempt result: **53 passed in 41.63s**, zero failures and zero skips. PostgreSQL 17.11
is a real disposable local server; every record is synthetic. These checks prove
storage and transaction mechanics, never live provider stock or eligibility.

Coverage includes negative inserts/updates, unknown/zero/positive transitions,
timezone round trips, required metadata, infinite timestamps, invalid versions,
foreign keys, duplicate rows, unchanged state after rejection, stale raw SQL and
upserts, concurrent writers, SQLAlchemy/migration parity, upgrade/downgrade/upgrade,
catalog regression checks and migration failure rollback.

## Assumptions and limits

The local storage contract assumes one authoritative stream per SKU with ordered
integer versions. It does not establish a vendor's version format, version reset
policy, protocol or authentication. No live provider decision is required by P0012;
provider integrations remain outside this task. Observation age, source verification
and eligibility must be evaluated by consumers; stored stock is never an assertion
of present eligibility. Downgrade discards inventory observations, so retain/export
them before an operational rollback if needed. No OpenAPI contract was changed.

No required P0012 checks remain blocked. Next step: independent automated review
of the task commit, followed by orchestrator-managed status updates.

## Prior rejection and independent reproduction

The first attempt was reverted because the reviewer could not reproduce the
Done when checks: no PostgreSQL service was running, and its instructions prohibited
creating files. This attempt keeps an existing disposable service and a migrated,
seeded database available through review. The prior rejection is not an output
format problem, and no acceptance verdict is asserted here.

The server listens only on a local Unix socket (no TCP listener). Its synthetic
role uses local trust authentication, with no real credentials or provider data.
The dedicated `synthetic_p0012_review` database already contains schema revision
`0003_inventory_schema` and SKU `SYNTHETIC-P0012-REVIEW`, stock 5, version 10,
observed at `2026-01-01T00:00:00Z`. It is separate from test databases, which the
suite creates and drops. No server initialization or migrations are needed by
the reviewer. This runtime service persists until explicitly stopped or host
restart; the committed code and tests do not depend on this particular path.

Suggested independent command, which creates no filesystem files (`-B`) and
rolls back every probe change; the reviewer may adapt it or issue direct SQL:

```sh
.venv/bin/python -B - <<'PY'
import psycopg
url = 'postgresql://synthetic_p0012@localhost:55412/synthetic_p0012_review?host=/tmp/clavel-p0012-review-yu3u2ss7/socket'
with psycopg.connect(url, connect_timeout=3) as c:
    assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003_inventory_schema",)
    sku_id = c.execute("SELECT id FROM skus WHERE sku = 'SYNTHETIC-P0012-REVIEW'").fetchone()[0]
    def current():
        return c.execute("SELECT sellable_stock, source_version, observed_at FROM inventory WHERE sku_id = %s", (sku_id,)).fetchone()
    original = current()
    assert original[:2] == (5, 10)
    c.rollback()
    cases = [
        (-1, 11, "2026-01-01T00:00:01Z", "inventory_stock_nonnegative"),
        (99, 9, "2026-01-01T00:00:01Z", "inventory_update_fresh"),
        (99, 10, "2026-01-01T00:00:00Z", "inventory_update_fresh"),
        (99, 11, "2025-12-31T23:59:59Z", "inventory_update_fresh"),
    ]
    for stock, version, observed, constraint in cases:
        try:
            c.execute("UPDATE inventory SET sellable_stock=%s, source_version=%s, observed_at=%s WHERE sku_id=%s", (stock, version, observed, sku_id))
        except psycopg.errors.CheckViolation as error:
            assert error.diag.constraint_name == constraint
        else:
            c.rollback()
            raise AssertionError("Invalid observation was accepted")
        c.rollback()
        assert current() == original
        c.rollback()
    for stock in (0, 7, None):
        c.execute("UPDATE inventory SET sellable_stock=%s, source_version=11 WHERE sku_id=%s", (stock, sku_id))
        assert current()[:2] == (stock, 11)
        c.rollback()
    assert current() == original
    c.rollback()
print("PASS: negative stock, stale/replayed versions and regressing time rejected; zero/positive/unknown preserved; all probe changes rolled back")
PY
```

Implementation-side result: the probe passed, with four rejected invalid updates,
three valid zero/positive/unknown updates rolled back, and the seed unchanged.
The independent reviewer must still run and assess the checks itself against the
exact task commit SHA. No human signature is required; status is Awaiting review.

After independent review, the orchestrator can stop and remove the disposable
service (not before the reviewer has reproduced the checks):

```sh
pg_ctl -D /tmp/clavel-p0012-review-yu3u2ss7/data -m fast -w stop
rm -r -- /tmp/clavel-p0012-review-yu3u2ss7
```
