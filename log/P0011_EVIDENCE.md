# P0011 catalog schema evidence

Status: Awaiting review. Independent Codex review and orchestrator acceptance remain pending.
Prerequisite acceptance was verified by the orchestrator before this session.

## Schema and unknowns

- `categories`: generated bigint key, unique nonempty case-sensitive code, nonblank name.
- `skus`: generated bigint key, globally unique nonempty case-sensitive SKU, nonblank
  name, optional category foreign key. Codes reject surrounding spaces.
- `hardware_attributes`: one row per SKU and attribute name, with a required kind
  (`text`, `number`, `boolean`, `unknown`) and exactly the matching typed value.
  Text must be nonblank; numbers must be finite. Optional nonempty units apply
  to numeric or unknown attributes. Foreign keys reject orphan records.
- A null category, absent attribute, or explicit `unknown` attribute remains unknown.
  Unknown values have all three value columns null; a unit may still be known.
  Numeric zero and boolean false remain known values, distinct from unknown.
- Synthetic examples: `length / number / 12.50 / mm`, `coated / boolean / false`,
  `diameter / unknown / null / mm`. These demonstrate storage mechanics only.
- Metadata lives in `src/clavel/database/catalog.py` and is registered with Alembic.
  Hardware attribute vocabulary, domain ranges, conversion, stock, and compatibility
  decisions are outside this schema task. No REST/OpenAPI contract changed.

## Migration impact

`0002_catalog_schema` follows `0001_migration_baseline` and creates three tables;
there is no existing catalog data to backfill. Repeated upgrades are idempotent.
Downgrade to baseline removes attributes, SKUs, then categories and therefore
discards catalog data. Only disposable synthetic databases were migrated here.

## Validation

`.venv/bin/python -m pytest tests/integration/test_catalog_schema.py tests/integration/test_migrations.py -q`

Result: **33 passed in 27.09s**, no skips. Native ephemeral PostgreSQL, synthetic
roles and records; neither SQLite nor database doubles. This is not live provider,
production catalog, attribute coverage, or compatibility evidence.

Coverage includes global SKU uniqueness across categories; malformed attribute
kinds, missing/mixed values, invalid numeric input, NaN/infinities, invalid units
and names; orphan and duplicate attributes; null category and explicit unknowns;
zero/false round trips; Alembic metadata comparison; catalog migration cycling;
baseline migration mechanics and transactional rollback of failed generated DDL.

`git diff --check` passed. No required live decision or missing input blocks P0011.
`log/STATUS.md` is orchestrator-managed and was left untouched.
