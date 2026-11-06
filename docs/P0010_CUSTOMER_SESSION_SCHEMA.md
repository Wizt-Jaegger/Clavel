# P0010 customer and session schema

Status: Awaiting review. Evidence uses disposable PostgreSQL and synthetic opaque
references only; it establishes schema mechanics, not live identity correctness.

`customers` is a subject registry: a unique, case-sensitive `opaque_ref`, explicit
`subject_kind` (`registered` or `anonymous`), and `created_at`/`last_activity_at`.
Both kinds persist independently of sessions. References must be upstream-issued
opaque tokens, never names, email addresses, phone numbers, or inferred traits.
The schema cannot determine whether arbitrary text contains personal data;
ingestion must enforce the opaque-reference contract.

`sessions` has a unique opaque reference, nullable `customer_id`, and
`started_at`/`last_activity_at`. A session without a resolved subject remains
unlinked. Multiple sessions may reference the same anonymous or registered
subject. Missing subject IDs fail a foreign key check; deleting a linked subject
is restricted. References are unique within their own table, including across
customer kinds. Internal generated IDs are local keys, not upstream identities.

Activity is explicit, finite PostgreSQL `TIMESTAMPTZ`, with last activity at or
after creation/start. No receipt-time defaults invent observed activity. Supply
timezone-aware timestamps and select UTC at the connection/display boundary;
PostgreSQL normalizes offsets to the same instant. Naive input validation belongs
to the future ingestion layer. No demographics or vendor integrations are added.

Separate policy decision: **anonymous-to-known linkage — Pending**. Independent
policy review must define authoritative evidence, authorization, merge/conflict
handling, historical attribution, and retention before implementing linkage or
kind conversion. This migration adds storage capacity only; it performs no
linking, promotion, inference, or historical rewriting. Existing registered and
anonymous subjects remain independent until an approved policy is implemented.
No live provider decision is required for this schema-only task.

Migration `0004_customer_session_schema` follows `0003_inventory_schema` and adds
two empty tables; existing catalog/inventory data is unaffected. Downgrade drops
sessions before customers and destroys their data. No REST/OpenAPI changes.

Reviewer checks: run the project-venv customer/session and migration integration
tests with `CLAVEL_REQUIRE_POSTGRES=1`; they exercise uniqueness, foreign keys,
anonymous persistence after reconnect, UTC offsets, invalid activity, metadata
parity, and upgrade/downgrade/upgrade preserving earlier synthetic catalog data.

Validation: `CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest
tests/integration/test_customer_session_schema.py tests/integration/test_migrations.py
tests/integration/test_catalog_schema.py tests/integration/test_inventory_schema.py -q`
— **83 passed, 0 failed, 0 skipped** (67.74 seconds). The uniqueness, invalid-link,
and anonymous-persistence done checks passed. Earlier catalog/inventory schema
regressions passed in the same run. `git diff --check` also passed. No live
identity/provider behavior or linkage policy acceptance is claimed.
