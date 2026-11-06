# Contrato frontend/API propuesto — v1 draft.2

P0006, **Awaiting review**. This is a review proposal, including the proposed
contract diff below; it does not publish runtime business capabilities.
The machine-readable artifact is [clavel-v1.draft.json](openapi/clavel-v1.draft.json).
Its examples are hand-authored **synthetic** fixtures: they prove schema mechanics
only, never inventory freshness, compatibility, model quality or operational readiness.

Evidence baseline: `3cc9763f0f04d1e16d04b02a9d7b4900bc800a6d`.
The [API shell](../src/clavel/api/app.py) implements `/health`, which reports
process liveness. Its generated `/openapi.json` remains the runtime source of
truth. [Shared errors](../src/clavel/core/errors.py) and
[correlation IDs](../src/clavel/core/correlation.py) inform the proposed envelopes.
The [architecture](ARQUITECTURA.md) and [decision register](REGISTRO_DECISIONES.md)
identify A03–A10 as unresolved policy and semantics; this proposal does not close them.
The task specifies no particular Q01–Q12 gate. No live check is claimed.

## Proposed diff and availability

Add a separate OpenAPI 3.1 document with version `1.0.0-draft.2`, route prefix
`/v1` and stable `v1_*` operation IDs. Add the schemas, example payloads, role
requirements and validation evidence described here. All operations explicitly
carry `x-availability: design-time`; no business routes or runtime schemas change.
The `foundation` stage means an initial contract proposal, not an implementation
schedule or a delivered feature. `emi` explicitly reserves later work for Emi's
stage. Every row below is design-time only.

| Method and proposed path | Operation ID | Required role | Stage |
| --- | --- | --- | --- |
| GET `/v1/catalog` | `v1_list_catalog` | viewer | foundation |
| GET `/v1/inventory` | `v1_list_inventory` | viewer | foundation |
| GET `/v1/segments` | `v1_list_segments` | viewer | foundation |
| POST `/v1/recommendations/preview` | `v1_preview_recommendations` | viewer | foundation |
| POST `/v1/events` | `v1_ingest_event` | event_writer | foundation |
| GET `/v1/reports/dashboard` | `v1_get_dashboard` | analyst | emi |
| GET `/v1/reports/clustering-quality/{model_version}` | `v1_get_clustering_quality` | analyst | emi |
| GET `/v1/experiments` | `v1_list_experiments` | analyst | emi |
| GET `/v1/experiments/{experiment_id}/candidates` | `v1_list_candidates` | analyst | emi |
| GET `/v1/tuning/status` | `v1_get_tuning_status` | operator | emi |
| GET `/v1/tuning/limits` | `v1_get_tuning_limits` | operator | emi |
| POST `/v1/tuning/runs` | `v1_start_tuning` | operator | emi |
| GET `/v1/versions` | `v1_list_versions` | operator | emi |
| GET `/v1/rollbacks` | `v1_list_rollbacks` | operator | emi |
| POST `/v1/rollbacks` | `v1_rollback_bundle` | operator | emi |
| POST `/v1/recommendations/pause` | `v1_pause_recommendations` | operator | emi |
| POST `/v1/recommendations/enable` | `v1_enable_recommendations` | operator | emi |
| GET `/v1/reports/recommendation-activity` | `v1_list_recommendation_activity` | analyst | emi |

## Shared rules

Bearer authentication and roles are proposed requirements. Role lists mean all
listed roles are required; there is no implied role hierarchy. Missing/invalid
credentials yield 401; insufficient roles yield 403. The server must check roles
on every request, including pause/enable, tuning and rollback. UI button visibility
is not authorization. Issuer, claim mapping and scope restrictions await A03/A01.
The current API shell does not implement this authentication scheme.

List responses have `items` and `page: {limit, next_cursor}`. Default limit is 20,
allowed range 1–100. `next_cursor: null` ends traversal; empty collections return
200 with `items: []`. Cursors are opaque and bound to operation, filters and a
stable snapshot. Invalid or expired cursors yield 400. Proposed stable ordering:
catalog/inventory by item ID, segments by segment ID, and histories/activity by
descending creation/occurrence time with ascending ID as tie breaker. Candidate
history uses candidate ID. Cursor lifetime and storage remain implementation work.

`X-Request-ID` accepts 1–64 ASCII letters, digits, dots, underscores or hyphens.
Missing, repeated or invalid values are replaced by generated IDs. Every proposed
response echoes that header; error and unavailable bodies also contain it.
Dates use RFC 3339 with an offset; identifiers in these fixtures are invented.
Unknown values are explicit `null` or enumerated unknown states, never fabricated zeroes.

Errors retain the current shell's redacted `{error: {code, message}, request_id}`
shape. Proposed mappings: 400 `bad_request`, 404 `not_found`, 422
`validation_error`, 500 `internal_error`; 401/403/409 use the shell's `http_error`
and fixed `Request failed` message. Clients use HTTP status as well as the code.
No exception detail, credential, raw event payload or personal data belongs in an error.
503 uses a separate typed `{state: unavailable, reason, retryable, request_id}`
body. Reasons distinguish not implemented, missing active bundle/segment, version
mismatch, dependency failure and `recommendations_paused` for paused previews.
The current runtime returns 404 for these
unimplemented business paths; 503 examples describe a future handler, not today's behavior.

## Domain semantics and review examples

Catalog preserves `unknown` compatibility. Inventory distinguishes `in_stock`,
`out_of_stock`, `unknown`, and `stale`, with nullable observation/source evidence.
Preview accepts segment/model versions, an opaque compatibility context and limit
1–50. It returns a matching model/score/bundle tuple and eligible items only.
Each item requires verified compatibility, in-stock status, an observation time and
inventory source version. Freshness policy remains A05: a timestamp alone does not
prove freshness. Until a reviewed policy and evidence exist, the service must
exclude the item. Unknown/stale stock and unknown compatibility cannot qualify.
Rank descending by score with ascending item ID for ties (proposed A07/A09).
A valid bundle with no eligible items returns 200 `state: empty` and
`empty_reason: no_eligible_items`. Missing segment/bundle or incompatible versions
return 503 rather than an invented fallback.

Event intake proposes minimal versioned aggregate context: event ID/type,
item/segment/model IDs, timestamp and `schema_version: v1`. No raw user or device
identifiers are accepted. A 202 receipt acknowledges intake only; it does not
promise a refreshed popularity score. Same event ID and identical content returns
202 with `duplicate: true`; conflicting content returns 409. Retention, deduplication
window, allowed sources and identity/privacy rules await A04/A10.

Dashboard metrics expose availability, sample count and nullable value. Zero means
measured zero; unavailable means `value: null` with a reason. Clustering quality
exposes silhouette and Davies–Bouldin availability by model version; no invented
threshold certifies a model. Experiment/candidate histories retain dataset and
model identity, state and metrics. All metric definitions, windows and quality
acceptance criteria await A04/A08. The synthetic `0.25` is not quality evidence.

Tuning exposes status, proposed limits and a queued run receipt. Draft ceilings
are 100 candidates, 3600 seconds and one concurrent run; these are review choices,
not measured system capacity. Deployment may impose tighter limits; requests above
the effective advertised limits return 422, concurrent-run conflicts return 409.
Starting tuning cannot implicitly promote a candidate. Version history identifies
atomic model/score bundles. Rollback names expected current and target bundle
versions; stale state yields 409, and the whole compatible bundle changes together.
Pause/enable require `expected_revision` and a reason; stale revisions yield 409.
Enable also requires an active compatible bundle, otherwise 503. While paused,
`POST /v1/recommendations/preview` returns HTTP 503 with `state: unavailable`,
`reason: recommendations_paused`, `retryable: false` and the correlated `request_id`.
The pause takes precedence over serving previews even with a valid bundle and
eligible items: no cached recommendations or 200 empty response may bypass it.
`retryable: false` means automatic retries cannot lift an operator pause; a
successful role-checked enable action is required before previews may resume.
Reporting/history reads remain available under their own availability rules.
Durable audit, concurrency and atomicity remain A10 implementation requirements.
Recommendation activity records aggregate served/empty/unavailable outcomes without
personal identifiers. Access/retention and reporting windows require review.

Examples live beside each request/response schema in the JSON artifact. For example,
the preview empty response is:

```json
{"state":"empty","segment_id":"synthetic-segment-1","bundle":{"bundle_version":"synthetic-bundle-1","model_version":"synthetic-model-1","score_version":"synthetic-score-1"},"items":[],"empty_reason":"no_eligible_items"}
```

The paused preview 503 response is (also echo `X-Request-ID: synthetic-request-1`):

```json
{"state":"unavailable","reason":"recommendations_paused","retryable":false,"request_id":"synthetic-request-1"}
```

The common error example is:

```json
{"error":{"code":"validation_error","message":"Request validation failed"},"request_id":"synthetic-request-1"}
```

## Change process, migration impact and evidence

API maintainer proposes a schema/operation diff with updated happy, empty, error
and unavailable examples plus a client migration impact statement. The relevant
domain/operations owner and designated frontend/API reviewer review role and
availability changes before runtime implementation. The reviewer records name,
reviewed SHA and date; only the reviewer sets Accepted. A01 still needs named owners.

Keep operation IDs stable within a major version. Removing/renaming fields,
tightening validation, changing meaning, roles, pagination or error behavior, and
adding response enum values require a compatibility assessment; incompatible
changes use a new major route/document version with a published migration and
deprecation plan. Even additive fields must account for strict client validators.
Draft revisions increment the draft version and require renewed example validation.

Draft.2 adds `recommendations_paused` to the unavailable reason enum and a dedicated
preview 503 response/example, enforcing `retryable: false` for that reason.
Draft.1 mock clients with exhaustive reason handling or strict schemas must add
this reason, show the paused state, and avoid automatic retries until an operator
enables recommendations. Operation IDs and successful payloads are unchanged.

Migration impact now: none for existing runtime callers; `/health` and its runtime
OpenAPI remain unchanged. Frontend work may build mocks from this labelled draft,
but must keep business controls unavailable until reviewed implementation exists.
Future activation requires an approved mapping from draft to actual endpoints,
authentication/role checks, live availability evidence and client integration tests.
No database migration, deployment, production endpoint or model activation occurs here.

Validate with the project-local environment after installing `.[dev]`:

```sh
.venv/bin/python -m openapi_spec_validator docs/openapi/clavel-v1.draft.json
.venv/bin/python -m pytest tests/test_openapi_contract.py tests/test_api_shell.py
```

[Contract tests](../tests/test_openapi_contract.py) lint the document, validate all
embedded requests/responses against their schemas, require happy/empty/error
coverage, reject unsafe eligibility and fabricated metric values, and check that
the proposed routes remain absent from the runtime API. Test results and source
revision are recorded in [CODEX_LOG.md](../log/CODEX_LOG.md).
