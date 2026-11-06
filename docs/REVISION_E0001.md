# E0001 · Independent architecture and contract review

**Accepted by Emi on 2026-11-06 (UTC).** Emi approved the E0001 review of the source revision below. The findings and their closure criteria remain documented for CP0.

Reviewed source `8a031e9da7dabe3369349b62bd277089c85f1f4d` (P0006 Accepted row
prefix `8a031e9`, supplied by the task). The local and origin
`accepted/P0006` tag lookups returned no match. Acceptance commit
`7bf88d21231b33ef29b608e25a7cda9c0158b4e9` changes only the activity log and
status. The reviewed artifact is the pinned source. Reproduce with
`git ls-tree -r <reviewed-sha> -- docs/openapi` and
`git show <reviewed-sha>:<path>` for each source linked below.

The comparison uses the E0001 brief and the project constraints available in
[AGENTS.md](../AGENTS.md). The original master prompt was outside the permitted
inputs, so direct traceability to it remains open for the human reviewer.

| Area | Severity and disposition | Evidence and closure |
| --- | --- | --- |
| Responsibility | Design aligns with the available constraints. Named accountability and transaction ownership are open. | API orchestration, catalog eligibility, data preparation, BIRCH assignment, segment scoring and bundle serving have distinct owners and boundary-owned writes. A01/A02 require named maintainers, reviewer authority and a failure walkthrough for publication and rollback before activation. [Architecture](ARQUITECTURA.md#proposed-monolith-boundaries), [decision register](REGISTRO_DECISIONES.md#open-questions-owners-and-closure-evidence) |
| Trust boundary | High. Gate preview and event intake on approved caller and data scope. | Bearer auth and operation roles describe the draft. Preview accepts opaque caller-supplied segment, model and compatibility context IDs. Event intake accepts segment/model IDs that can affect popularity. Under A01/A03/A04/A10, the API and Data maintainers must verify token issuer and claims, authorize each referenced object/context, and verify or derive event attribution from authorized sources. Exercise missing/invalid credentials, wrong role, out-of-scope IDs, and spoofed or conflicting events before activation. [Shared rules](CONTRATO_FRONTEND_API.md#shared-rules), [OpenAPI](openapi/clavel-v1.draft.json) |
| Contract · eligibility and limits | High for eligibility, medium for limits. Keep as design-time pending runtime checks. | `Recommendation` rejects explicit stale stock and unknown compatibility. A synthetic old observation with `in_stock` still validates. A 51-item `Preview` also validates despite the request maximum of 50. Under A05/A07/A09, require authoritative freshness, compatibility, version consistency and request-limit enforcement with runtime cases. The API maintainer can propose `maxItems: 50` in a subsequent draft with over-limit examples and a migration note for mock clients. The requested limit still needs runtime enforcement. [Domain semantics](CONTRATO_FRONTEND_API.md#domain-semantics-and-review-examples), [OpenAPI](openapi/clavel-v1.draft.json) |
| Contract · serving and control | High. Require authorization and atomic transition evidence before activating control routes. | The draft distinguishes 200 empty from typed 503 unavailable, gives pause precedence, and specifies conflict handling for stale expected revisions or bundle versions. A02/A09/A10 must demonstrate authorized pause/enable, cache behavior, concurrent stale writes and atomic rollback of compatible versions. A01 must name the promotion reviewer. Require evidence that starting tuning cannot promote and that approval binds to the exact candidate and report. [Contract](CONTRATO_FRONTEND_API.md#domain-semantics-and-review-examples), [architecture](ARQUITECTURA.md#tuning-flow-walkthrough) |

The pinned OpenAPI inventory contains one document with 18 design-time
operations. `openapi_spec_validator` passed. The focused
[contract](../tests/test_openapi_contract.py) and [API shell](../tests/test_api_shell.py)
suite passed 293 tests with one Starlette deprecation warning. Independent
synthetic probes reproduced the eligibility and limit behavior above.
Schema and shell checks provide fixture and local evidence only. Live access
control, catalog freshness, and model or operational outcomes remain unverified.

The human reviewer can sign the review record against the pinned revision
after checking the outstanding master-prompt traceability. Each runtime risk
above has an owner or decision reference and explicit closure evidence.
