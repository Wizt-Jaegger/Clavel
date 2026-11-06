# Clavel decision register

P0005 source revision: `f39db8418aa2bc902354c59970498eece336253e`.
Evidence is limited to the assigned kit task, its INDEX row, repository rules
and the source files linked below. No original planning documents or other
task files were consulted. See [architecture](ARQUITECTURA.md) for boundaries
and the recommendation and tuning walkthroughs.

“Recorded direction” means an explicit project instruction, not a new reviewer
acceptance. “Observed” means present in the source revision, not live-system
verification. “Proposed” requires review before implementation. Task acceptance
belongs to the reviewer; this register does not mark P0005 Accepted.

## Decisions and evidence

| ID | Classification | Decision / evidence | Consequence and limits |
| --- | --- | --- | --- |
| D01 | Recorded direction | Modular monolith with REST, from [AGENTS.md](../AGENTS.md) and [README.md](../README.md) | Keep logical boundaries inside the application; service extraction is not part of P0005. Interfaces and job execution remain A02. |
| D02 | Recorded direction; installation observed | Python, FastAPI, PostgreSQL, pytest; [pyproject.toml](../pyproject.toml) limits Python to 3.13 and declares FastAPI/psycopg/pytest | PostgreSQL is the intended persistence system. Driver installation and URL validation do not prove a database connection, schema or production readiness. |
| D03 | Recorded direction | BIRCH clustering and segment-level popularity, from [AGENTS.md](../AGENTS.md) | Use these as the algorithmic starting point. No clustering dependency, trained model, features, popularity formula or quality evidence exists in the inspected source; A04/A06/A07/A08 remain open. |
| D04 | Recorded constraint | Unknown/stale stock and unknown compatibility are never verified/eligible; [AGENTS.md](../AGENTS.md) | Preserve unknown states through preparation, filtering and response decisions. Popularity cannot override eligibility. Source authority and freshness semantics remain A05. |
| D05 | Recorded constraint; shell observed | Contract changes need a proposed diff, examples and migration impact; [AGENTS.md](../AGENTS.md). The [API factory](../src/clavel/api/app.py) supplies liveness and shared error handling | Documentation adds no endpoints or schema fields. `/health` is not database readiness. Future recommendation contracts remain A09. |
| D06 | Proposed | Boundary-owned writes, application orchestration, versioned model/assignment/score bundles and isolated tuning runs; rationale in [architecture](ARQUITECTURA.md) | Make recommendation lineage and tuning comparisons reviewable while retaining a monolith. Package layout, transactions, publication and runtime execution require A02/A07/A10 decisions; this document does not implement them. |

Settings behavior is observed in [settings.py](../src/clavel/core/settings.py):
startup validation, environment precedence and secret wrapping. These facts
support the infrastructure boundary, without choosing new operational policy.

## Open questions, owners and closure evidence

Owners below are explicit accountable roles for follow-up. They are provisional
role assignments because the permitted sources identify no named domain
owners. The task implementer owns documenting them; the project maintainer
owns confirming people and reviewer authority in A01. Each item remains open
until its closure evidence is reviewed. No answer is inferred from missing data.

| ID | Unresolved item | Accountable owner | Evidence needed to close | Affected flow |
| --- | --- | --- | --- | --- |
| A01 | Who fills each accountable role and who reviews architecture, contracts and model promotion? | Project maintainer | Named role assignments and designated reviewers, with acknowledgement; record source revision/date | Both |
| A02 | What are the module interfaces, storage ownership, transaction boundaries and offline/job execution mechanism? How are bundles activated consistently? | Application maintainer | Reviewed interface/dependency plan and failure/activation walkthrough; deployment decision belongs to later scope | Both |
| A03 | What caller identity, authorization and compatibility context may recommendation requests use? | API maintainer | Approved access rules and minimal request context, including missing/unauthorized cases; no raw personal data in examples | Recommendation |
| A04 | What data sources, provenance, features, event validation, preprocessing and training/evaluation split are allowed? | Data maintainer | Versioned data/feature definitions and leakage checks with synthetic fixtures labelled as such; live evidence separately identified | Both |
| A05 | Which sources establish stock and compatibility, when is stock stale, and how are unknown states represented? | Catalog maintainer | Source authority and freshness policy plus verified/unknown/stale and compatibility examples; unknown never qualifies | Recommendation and evaluation |
| A06 | Which BIRCH implementation/version and parameters, scaling, model serialization and unseen/missing-user assignment rules apply? | ML maintainer | Reproducible candidate configuration and assignment examples, with fixture mechanics distinguished from live evidence | Both |
| A07 | What events/window define segment popularity, how are ties handled, and how are model/assignment/score versions kept consistent? | Recommendations maintainer | Defined score semantics, refresh/version rules and mismatch/tie examples | Both |
| A08 | Which baseline, metrics, held-out protocol, acceptance limits and latency/resource budgets justify choosing a tuning candidate? | ML maintainer | Reviewed evaluation protocol and evidence requirements before selection; synthetic success alone is insufficient | Tuning |
| A09 | What are the public recommendation responses, ordering/limit rules and missing-segment, no-eligible-item or unavailable-bundle behavior? | API maintainer | Proposed OpenAPI diff, examples and migration impact; review before contract implementation | Recommendation |
| A10 | What are the retention/access, safe observability, recovery, promotion and rollback requirements? | Operations maintainer | Reviewed operational policy and rollback evidence tied to code, data and bundle versions, without secrets/raw personal data | Both |

## Walkthrough findings and review handoff

The [recommendation walkthrough](ARQUITECTURA.md#recommendation-flow-walkthrough)
connects request context → assignment → segment scores → eligibility → response.
Its synthetic example excludes unknown and stale candidates regardless of
popularity. Missing assignments, mismatched versions and empty eligible sets
remain explicit A06/A07/A09 decisions with owners.

The [tuning walkthrough](ARQUITECTURA.md#tuning-flow-walkthrough) connects
snapshot/split → configuration → training/aggregation → held-out comparison →
review/promotion. Its synthetic example leaves the winner undetermined without
A08 criteria, and assigns execution and rollback to A02/A10.

P0005 validation checks relative evidence links, decision/open-item references,
owner/closure coverage and both walkthroughs, plus the existing application
tests. This is documentation and source-consistency evidence only. Business
behavior, live source eligibility, model quality and production operations
are not validated by these checks. Follow-up work must record its own source
revision, examples, tests and reviewer evidence before closing an item.
