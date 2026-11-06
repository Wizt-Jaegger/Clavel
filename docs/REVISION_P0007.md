# P0007 · CP0 contract review and foundation gate

Status: **Awaiting review**. Prepared on 2026-11-06 UTC for the independent
Codex reviewer and orchestrator. This record does not grant acceptance.

Reviewed source: `8166fbc0a3c535150e6b1e6998021f4eae7b98a2` on `main`.
All commands below ran from the repository root against that source, using
the existing project-local environment, Python 3.13.15. This task adds only
this evidence and append-only activity records; it changes no contract or
application behavior. The pre-existing orchestrator edit to
`log/STATUS.md` is excluded from the task commit.

## Accepted prerequisites and source identity

The orchestrator supplied Accepted prerequisites, corroborated by the
P0006 and E0001 rows in `log/STATUS.md` at execution time:

| Task | Full accepted source SHA | Source checked |
| --- | --- | --- |
| P0006 | `8a031e9da7dabe3369349b62bd277089c85f1f4d` | [Contract proposal](CONTRATO_FRONTEND_API.md), [OpenAPI and embedded fixtures](openapi/clavel-v1.draft.json), [contract tests](../tests/test_openapi_contract.py) |
| E0001 | `8c24f5caaf7dc729b12a1cccb482a6570d5eee69` | [Independent architecture review](REVISION_E0001.md), [architecture](ARQUITECTURA.md), [decision register](REGISTRO_DECISIONES.md) |

Both source commits are ancestors of the reviewed checkpoint SHA. The P0006
artifacts are byte-identical there; architecture and decision register are
also unchanged from E0001. E0001's review record differs only in its existing
acceptance heading; its findings and closure criteria are unchanged. A broad
comparison initially exited 1 for this heading difference; the scoped retry
passed. This is an explained document difference, not a failed validation.
The accepted source status governs older proposal prose saying Awaiting review.
No new human signature or M0002 acceptance is required for CP0.

## Criteria and observed evidence

Each row is pinned to the full reviewed source above. The preparer performed
these checks; the independent acceptance reviewer remains pending.

| CP0 criterion / task trace | Reproduction | Observed result and boundary |
| --- | --- | --- |
| Bootstrap and working instructions / P0007 | Read [AGENTS.md](../AGENTS.md), [README.md](../README.md), [pyproject.toml](../pyproject.toml); run bootstrap suite below | 16 tests and 6 subtests passed: repository rules, contribution links, installed package/dependencies, settings validation and precedence. No database connectivity claim. |
| Architecture / E0001, P0007 | Read the E0001 review, architecture boundaries and both walkthroughs, and A01–A10 owner/closure register; compare accepted sources below | Python/FastAPI/PostgreSQL modular monolith, BIRCH and segment popularity direction are explicit. Responsibilities, eligibility constraints, unknown states and versioned publication risks are documented. Business architecture remains proposed. |
| OpenAPI validity / P0006, P0007 | Standalone validator plus `test_openapi_lint` | Exit 0; OpenAPI 3.1 draft `1.0.0-draft.2` and component JSON schemas validate. 18 unique design-time operations; no business runtime routes published. |
| Fixture conformance / P0006, P0007 | `test_all_synthetic_request_and_response_examples` and coverage/provenance test | All 261 expanded cases validate: 6 request and 255 response examples, including 18 happy, 11 empty, 126 generic error and 91 unavailable response examples. References are counted per operation. |
| Success, empty and error states including 401/403 / P0006, P0007 | Contract/API suite below | Every operation has happy and error examples, including one 401 and one 403 each (18 of each). Collection/report empty examples, typed 503, pause semantics, unsafe eligibility and unavailable metrics are checked. |
| Runtime separation / P0006, P0007 | `test_draft_adds_no_runtime_routes_or_business_schema` and API-shell tests | Runtime OpenAPI exposes only `/health`; all 18 draft business requests return 404. Synthetic local shell exercises correlation, redacted errors and startup failure. It does not test real authentication or role enforcement. |
| Independent automatic review / P0007 | Orchestrator invokes a separate Codex reviewer against the resulting full evidence commit SHA | **Pending.** No reviewer output or exit code was supplied or produced by this preparation task. Acceptance requires the evidence described below. |

## Exact validation commands and results

```sh
.venv/bin/python --version
# Python 3.13.15; exit 0
.venv/bin/python -m openapi_spec_validator docs/openapi/clavel-v1.draft.json
# docs/openapi/clavel-v1.draft.json: OK; exit 0
.venv/bin/python -m pytest tests/test_openapi_contract.py tests/test_api_shell.py -q
# 293 passed, 1 warning; exit 0
.venv/bin/python -m pytest tests/test_repository_rules.py tests/test_project_smoke.py tests/test_settings.py -q
# 16 passed, 6 subtests passed; exit 0
```

The warning is Starlette's deprecation notice for its httpx TestClient
integration. It does not indicate a failing test. No additional test changes
were necessary for this documentation checkpoint.

Source comparisons (all exit 0; no diff):

```sh
git diff --exit-code 8a031e9 HEAD -- docs/openapi/clavel-v1.draft.json docs/CONTRATO_FRONTEND_API.md tests/test_openapi_contract.py
git diff --exit-code 8c24f5c HEAD -- docs/ARQUITECTURA.md docs/REGISTRO_DECISIONES.md
git merge-base --is-ancestor 8a031e9 HEAD
git merge-base --is-ancestor 8c24f5c HEAD
```

For later reproduction replace `HEAD` with the full reviewed checkpoint source
SHA above. The separate `git diff 8c24f5c HEAD -- docs/REVISION_E0001.md`
shows the acceptance-heading change described earlier. Exact commands,
expanded fixture inventory and execution events are in
[CODEX_LOG.md](../log/CODEX_LOG.md), under this P0007 session's START line.
Contract SHA-256:
`994513662545cee065cbed2a329082cc7702ffaa0de8c7fdf90b82b8cfd87160`.

## Provenance, limitations and retained gates

Fixtures are embedded in the OpenAPI document. Its `x-fixture-provenance`
identifies `kind: synthetic`, source `P0006 hand-authored draft`, and explicitly
limits evidence to schema/example mechanics. API-shell tests use synthetic
HTTP inputs, fake credentials and local settings without database connections.
These are local fixture/test-double results, with no live provider evidence.

E0001's retained findings are prerequisites for future runtime activation,
not evidence of implemented controls or CP0 live acceptance:

- A01/A03/A04/A10: API and Data maintainers must establish identity, roles,
  object/context scope and trustworthy event attribution. 401/403 fixture
  validation and a synthetic raised 403 prove no live authorization policy.
- A05/A07/A09: Catalog and API maintainers must enforce authoritative freshness,
  compatibility, version consistency and the requested response limit.
  The accepted draft still permits an old timestamp labelled in-stock and
  more than 50 response items at schema level. Those known schema limits
  require runtime enforcement before serving; synthetic validity never
  makes old stock eligible. A future `maxItems: 50` tightening needs its own
  proposed diff, examples and client migration assessment; it was not silently
  applied in this checkpoint.
- A02/A09/A10: Application and Operations maintainers must demonstrate
  authorized pause/enable, cache continuity, concurrency, atomic publication
  and rollback. Promotion review must bind to the exact candidate/report.
- A01–A10 retain the named-role, data, model, metric and operational decisions
  and closure evidence in the register. No provider protocol, live credential,
  freshness threshold, quality score or Q01–Q12 answer is invented here.

Live authorization, PostgreSQL integration, real stock/compatibility, model
quality, provider decisions and deployment remain unverified. They are outside
this checkpoint's design-time slice and remain gated in their relevant tasks.
E0001's legacy master-prompt traceability/signature prose does not add a CP0
human-signature requirement; the assigned P0007 scope uses only the permitted
inputs. No blocking defect was found in the tested CP0 fixture/schema slice;
this conclusion is submitted for independent review, not self-acceptance.

## Automatic review handoff

The orchestrator must give the independent Codex reviewer the full committed
P0007 evidence SHA, this record, the pinned sources and command results.
The reviewer must verify the retained risks are correctly scoped and rerun
the relevant checks. Any unresolved CP0 contract defect, failed check or
missing required input blocks acceptance.

The orchestrator must retain reviewer identity, exact reviewed commit SHA,
UTC date, command/exit code and stdout evidence. Only a reviewer process
exiting **0** whose final stdout line is exactly `VERDICT: ACCEPTED` permits
the orchestrator to record Accepted and continue to P0008. This preparation
contains no such verdict, does not alter `log/STATUS.md`, and requests no
human confirmation. Next step: independent automatic review of this commit.
