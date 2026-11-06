# Clavel architecture

P0005 evidence baseline: `f39db8418aa2bc902354c59970498eece336253e` on
`main`. Repository links below refer to files inspected at that revision;
use `git show <baseline>:<path>` to reproduce the source. This document records
project direction and proposed boundaries, not implemented business behavior.
The task source is the read-only kit's `tasks/P0005.md`, with prerequisite
P0001 verified Accepted by the orchestrator. P0005 remains subject to review.

## Confirmed direction and current implementation

- [AGENTS.md](../AGENTS.md) specifies Python, FastAPI, PostgreSQL, pytest,
  REST, a modular monolith, BIRCH clustering and segment-level popularity.
- [pyproject.toml](../pyproject.toml) establishes Python 3.13 and dependencies
  for FastAPI, psycopg, settings and pytest. It does not install a clustering
  library. Database connectivity and BIRCH execution are not demonstrated.
- [The application factory](../src/clavel/api/app.py) implements `/health`,
  request correlation and error handling. Health is process liveness only.
- [Settings](../src/clavel/core/settings.py) validate a PostgreSQL URL at
  startup. Environment overrides `.env`, which overrides optional `.env.shared`.
- [README.md](../README.md) describes the bootstrap; business features belong
  to later tasks. No catalog, segmentation, recommendation or tuning module
  exists in the inspected source tree.

The accompanying [decision register](REGISTRO_DECISIONES.md) separates recorded
choices D01–D05 from proposed design D06 and assigns owners to open items A01–A10.
An owner is an accountable project role, not evidence of a named person's
approval. Assignment of people to those roles is itself tracked in A01.

## Proposed monolith boundaries

One application and one PostgreSQL system are the intended starting point.
The table defines logical responsibilities; new package paths, tables, jobs,
interfaces and execution modes require later implementation decisions (A02).

| Boundary | Owns | Permitted interaction | Accountable role |
| --- | --- | --- | --- |
| API / orchestration | REST validation, correlation, response mapping | Calls application operations; no clustering or ranking logic in routes | API maintainer |
| Core / configuration | Startup settings and common error semantics | Shared infrastructure only; no business decisions | Application maintainer |
| Catalog / eligibility | Item facts, stock freshness, compatibility and explicit unknown states | Supplies eligibility decisions and evidence to recommendations | Catalog maintainer |
| Data preparation | Provenance, feature definitions, event validation and snapshot construction | Supplies versioned inputs to segmentation and popularity | Data maintainer |
| Segmentation | BIRCH training, model version and assignment rules | Consumes prepared features; supplies segment identity and model version | ML maintainer |
| Segment popularity | Aggregate counts/scores within a defined segment and window | Consumes validated events and segment assignments; supplies versioned scores | Recommendations maintainer |
| Recommendations | Joins segment scores with eligible candidates, orders and limits results | Uses catalog and model/score outputs through application interfaces | Recommendations maintainer |
| Tuning / evaluation | Candidate configurations, evaluation evidence and promotion decision | Runs preparation, segmentation and scoring with isolated versioned inputs | ML maintainer |
| Persistence adapters | PostgreSQL access and transaction implementation | Implements boundary-owned storage operations | Application maintainer |

Proposed rule: a boundary owns its writes; another boundary requests an
operation instead of changing its tables directly. Dependency direction is
API → application operations → domain responsibilities → persistence adapters.
Core stays independent of business modules. No service split, queue, scheduler,
ORM, schema, migration framework or public recommendation endpoint is selected
here. Boundary interfaces and job execution remain A02; publication of new
OpenAPI contracts requires a diff, examples and migration impact (D05, A09).

## Recommendation flow walkthrough

1. The API validates a request and invokes recommendations. Request identity,
   authorization and compatibility context are unresolved (A03, API maintainer).
2. Data preparation supplies features with provenance; segmentation resolves
   an assignment tied to a model version. Feature definitions and treatment of
   missing/new users are unresolved (A04/A06, Data/ML maintainers). A missing
   assignment must remain explicit until a fallback is approved.
3. Segment popularity supplies scores for the corresponding segment and
   version. Event meaning, aggregation window, tie breaking and synchronization
   with assignments remain A07 (Recommendations maintainer).
4. Catalog evaluates candidates against stock freshness and compatibility.
   Unknown/stale stock or unknown compatibility never becomes verified or
   eligible. Source authority, freshness threshold and compatibility semantics
   remain A05 (Catalog maintainer); no numerical threshold is invented here.
5. Recommendations orders eligible candidates using the segment scores and
   returns the permitted result through the API. Incomplete evidence may leave
   no eligible items; the external empty/fallback response is A09 (API
   maintainer). A version mismatch is held unresolved rather than silently
   reusing scores with different segment meanings (A07).
6. Operational evidence must omit secrets and raw personal data. Aggregated
   monitoring, retention, access and recovery requirements remain A10
   (Operations maintainer).

Synthetic walkthrough only: suppose segment `synthetic-segment-1` and scores
share model version `synthetic-model-1`. Item `synthetic-A` has verified current
stock and verified compatibility; `synthetic-B` has unknown stock;
`synthetic-C` has unknown compatibility; `synthetic-D` has stale stock.
Only A can reach ranking. A higher popularity score cannot admit B, C or D.
If A also becomes unknown, there are no eligible candidates; A09 owns the
response decision. These invented identifiers describe mechanics only: no
model, database, stock source or recommendation quality has been verified.

## Tuning flow walkthrough

1. Data preparation identifies a provenance-labelled snapshot and a split
   that prevents evaluation data leaking into training. Features, permissions,
   retention and split policy remain A04/A10 (Data/Operations maintainers).
2. ML defines candidate BIRCH parameters and preprocessing. Library/version,
   thresholds, branching factor, scaling, persistence and assignment behavior
   remain A06 (ML maintainer). BIRCH is project direction, not evidence that
   any particular configuration works.
3. Each candidate trains on the training partition, creates segment
   assignments and computes popularity using the approved training inputs.
   Record snapshot, feature/preprocessing version, parameters, code revision,
   model version, score version and run identity together. A02/A07 own the
   execution and consistent publication mechanism.
4. Evaluate against the held-out partition and baseline with the same
   eligibility rules. Metrics, baseline, minimum evidence, acceptance limits
   and performance budgets remain A08 (ML maintainer). No optimality or quality
   claim follows from successful execution alone.
5. The designated reviewer examines the evidence before a candidate is
   promoted. Candidate isolation, atomic model/score activation and rollback
   remain A02/A10 (Application/Operations maintainers). Until those decisions
   are closed, this is a proposed flow rather than authorization to deploy.

Synthetic walkthrough only: compare `synthetic-run-A` and `synthetic-run-B`
on one invented snapshot and held-out split. Keep each model paired with its
own assignments and scores; do not compare a changed feature set as though
only BIRCH parameters changed. Missing A08 criteria leaves the winner
undetermined. This exercises the review reasoning, with no measured results
and no implication of live-data readiness.

## P0005 review boundary

Both walkthroughs trace inputs, decisions, outputs and unresolved ownership.
All A01–A10 closure evidence is recorded in the register. This task changes
documentation only: no OpenAPI contract, runtime code, schema, live experiment
or deployment. Live recommendation quality and tuning effectiveness remain
unverified and outside P0005's documentation acceptance check. The source kit
names no specific decision gate for P0005; no Q01–Q12 mapping is inferred.
