# P0018 reviewer evidence

Status: Awaiting review. Acceptance belongs to the independent Codex reviewer
and orchestrator. Prerequisite acceptance was verified by the orchestrator before
this session. Base: `a6bb093ebbd9484e368945c85d1e576ae8a92f32`; branch: `main`.

All business data and caller verification assertions in the tests are synthetic.
Tests exercise real disposable PostgreSQL, not a database double. They establish
persistence mechanics only; no live provider, identity, channel or trust policy
has been verified. P0018 has no required live slice or outstanding input gate.

## Behavior and boundaries

- `RecommendationRepository.record_generation` atomically persists a whole
  response, including an empty response. It creates zero events/exposures.
  Request UUID replays must match the header and complete result set; input item
  order and equivalent timezone offsets do not alter identity.
- `record_verified_event(..., verified=True)` persists one explicit exposure,
  click, add_to_cart, purchase or return. Exact UUID replays are no-ops; changed
  payloads or linkage raise `RecommendationConflict`. Repeated observations with
  distinct event UUIDs remain distinct. Original receipt times must be retained
  for replay. No preceding lifecycle state is inferred.
- Verification is a trusted caller assertion, not an authentication mechanism.
  False/unknown assertions fail. Provider authentication must happen before this
  repository is called; an untrusted client flag must never authorize the call.
  Composite foreign keys enforce customer/request/generated-SKU linkage.
- Savepoints prevent partial writes when exceptions are caught, and methods
  never commit the caller's transaction. Serialization/deadlock retries belong
  at the outer transaction boundary. No sales accounting, stock, compatibility,
  identity inference, provider integration or OpenAPI changes are included.

## Migration

`0007_recommendation_returns` follows the accepted `0006` schema and expands only
the recommendation event type check. Existing events survive downgrade/upgrade
when no return events exist. Return rows block downgrade transactionally rather
than being deleted; the schema revision, constraint and evidence remain intact.
There is no automatic data deletion or transformation for downgrade.

## Validation

Required regression command (PostgreSQL required; skips cannot satisfy it):

```sh
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q \
  tests/integration/test_recommendation_repository.py \
  tests/integration/test_recommendation_telemetry.py \
  tests/integration/test_migrations.py
```

Result: **110 passed, 0 failed, 0 skipped in 87.52 seconds**, using the project
`.venv` and native disposable PostgreSQL.

Coverage includes exact and conflicting replay after reconnect, forged and
cross-subject linkage, ungenerated SKUs, empty requests, unresolved sessions,
independent event types, unknown verification, invalid identifiers/timestamps,
partial-write rollback, caller transaction rollback, concurrent replay/conflict,
metadata consistency and migration upgrade/downgrade/failure atomicity.

The initial repository run reported 46 passed / 2 failed. Concurrent generation
exposed the schema's second unique index outside a primary-key-targeted conflict
handler. Untargeted `ON CONFLICT DO NOTHING`, followed by full payload comparison,
resolves both unique constraints. This failure and the validation rerun are
recorded in `CODEX_LOG.md`.

Source whitespace is checked strictly. Four newly appended audit-command lines
contain trailing empty-output delimiters; they are retained under the append-only
log rule. The logger now emits `no output` for empty summaries. The complete diff
also passes with only blank-at-EOL checking disabled; log additions are checked
for zero deletions. The orchestrator-owned `log/STATUS.md` is not edited or staged.

Next step: independent review of the committed implementation and this evidence;
the orchestrator records the review outcome. No human signature is requested.
