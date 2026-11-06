# P0036 inventory REST evidence

Status: Awaiting review for local implementation. Production/live slice: Blocked.
Owner: Alonso; prepared 2026-11-06 on main, base
`9f0b5e1ffd20d61bba793a018075b37d31da182f`.
The independent Codex reviewer supplies the verdict for the implementation SHA;
the orchestrator manages status. No acceptance or human signature is claimed.

## Rejected-attempt correction

The recorded review rejected a real contract deviation: later pages could see
new stock despite the shared cursor's snapshot binding. This retry removes that
deviation, rather than changing reviewer output. The draft cursor parameter and
all shared schemas remain unchanged. A continuation is valid only when its
PostgreSQL snapshot matches the first page; a changed snapshot returns 400.

P0036 has no specific live gate and its Done when check is stale/unknown examples
against the contract. Synthetic contract/HTTP/database evidence below addresses
that check. It does not supply production credentials, a provider SLA or live
observations. The unavailable live slice remains explicitly Blocked below.

## Implemented behavior

GET /v1/inventory returns the existing InventoryPage shape: default limit 20,
maximum 100, items and page. item_id is the immutable database SKU ID serialized
as a string. Catalog enumeration includes SKUs with no observation as unknown,
with null timestamp/version. NULL quantities stay unknown and retain stored
evidence. Zero is out_of_stock. Positive stock requires an explicitly supplied
freshness policy and valid source observation to be in_stock; expired positive
stock is stale. Future observations or missing policy yield unknown. Versions,
including zero, are decimal strings. These states make no compatibility claim.
No inventory writes or recommendation route was added.

Reads reuse CatalogRepository and StockRepository inside a read-only,
repeatable-read PostgreSQL transaction. Each request reads at most 100 catalog
rows plus repository lookahead, and at most 100 observations. No transaction or
snapshot is retained after the request. Storage failures produce the existing
503 unavailable envelope with correlation ID and redacted details, never a
successful empty page.

Pagination preserves the existing snapshot binding. Opaque HMAC-authenticated
cursors bind inventory operation, limit, source snapshot, first evaluation time
and freshness policy. Cursors do not authorize access. An unchanged PostgreSQL
snapshot permits continuation; changes, including an in-flight writer committing,
return 400 so the client restarts. Freshness is evaluated at the first page's
clock value throughout a valid traversal. Tokens expire after five minutes from
the first page; this is an operational pagination lifetime, not a stock SLA.
The signing key is generated in memory per app instance and is never logged or
persisted. Restart/another worker invalidates tokens safely with 400. Unrelated
PostgreSQL commits can also invalidate a cursor. This conservative strategy
prioritizes consistent traversal over cursor longevity; no cached historical
stock or changed-snapshot continuation is promised.

Bearer authentication requires an injected trusted InventoryRuntime.verify_bearer
callable returning verified roles or None for invalid credentials. Missing,
malformed or invalid credentials return 401; verified callers without the
explicit viewer role get 403. The factory supplies no verifier or freshness SLA.
An unconfigured verifier produces nonretryable 503, a verifier failure retryable
503, and no database access occurs. No issuer, token format, claim mapping or
provider protocol is invented. No operator role hierarchy is assumed.

## Validation and provenance

All new credentials, rows, timestamps, clocks and five-minute stock freshness
policies are synthetic; HTTP verifier functions are test doubles. PostgreSQL
checks use a real disposable local database with synthetic data, never a live
provider. Production configuration and data are not read.

Command:

```sh
CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest tests/test_inventory_api.py tests/integration/test_inventory_api.py tests/test_openapi_contract.py tests/test_api_shell.py tests/test_inventory_eligibility.py -q
```

Result: **366 passed, zero failed, zero skipped** in 7.29 seconds; one installed
Starlette/httpx deprecation warning. Required PostgreSQL checks ran successfully. The checks validate actual stale/unknown HTTP
responses against the authored InventoryPage schema, along with missing/NULL/zero
stock, inclusive freshness boundary, future observations, unconfigured policy,
source timestamp/version preservation, empty pages, limit validation, auth/roles,
redaction and read-only repeatable-read transaction settings. Pagination tests
cover unchanged-snapshot traversal, stock/catalog commits, a writer active during
the first page, frozen freshness evaluation and changed/expired/tampered bindings.

The review-only JSON Patch is applied in memory, OpenAPI-linted and its synthetic
examples validated. Other operations and components are checked unchanged. A final assertion that
the inventory parameters remain unchanged passed with all 32 inventory unit
tests (zero failed/skipped, 0.97 seconds).

## Contract proposal and migration impact

The authored docs/openapi/clavel-v1.draft.json is unchanged. The review-only
p0036-inventory.proposal.json proposes inventory activation metadata, an explicit
behavior description and synthetic stale/unknown examples. It preserves the
existing shared cursor parameter and success/error schemas. Independent review
can evaluate the concrete diff; no contract-owner approval is claimed.

No database migration or response shape change. Clients treat IDs/cursors as
opaque strings and restart traversal on 400 for an invalid/expired/changed
snapshot. Length violations return 422 under existing bounds. Synthetic example
cursors are not usable credentials or runtime tokens. Runtime OpenAPI labels the
operation local-validation-only; this is not production activation evidence.

## Live blocker record

Task: P0036, Alonso, 2026-11-06, main; reviewed SHA supplied by commit/orchestrator.
Missing inputs: A03-approved bearer issuer/verification and role mapping, Q07
production freshness policy and timestamped/versioned provider observations.
The draft BearerAuth description records the outstanding authentication decision.
Last attempted checks: synthetic verifier and disposable PostgreSQL tests above;
no live request was attempted without approved inputs.

Fixture implementation and independent automated review can continue. Production
activation, live stale/unknown validation and downstream claims of verified live
availability must wait. Authentication and Q07 decision owners can unblock this
slice by supplying approved integration/roles, freshness policy and provider
observation evidence. Then rerun the HTTP checks with those inputs and bind live
review evidence to the exact SHA. No new pagination contract decision is needed:
the implementation now obeys the existing snapshot binding. Missing live inputs
are neither accepted nor represented as failed local mechanics.
