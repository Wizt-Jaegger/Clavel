# P0015 customer and session repository evidence

Status: Awaiting review. Acceptance belongs to the independent Codex reviewer
and orchestrator. No human signature is required.

Implementation: `src/clavel/database/customer_sessions.py`, using the existing
PostgreSQL schema and caller-owned `Database.session()` transactions. No schema,
OpenAPI, provider integration or demographic model changes.

## Identity rules

- `CustomerRepository.resolve(ref)` and `SessionRepository.resolve(ref)` return
  the matching immutable record or `None`. Unknown lookup performs no writes.
- References are case-sensitive opaque tokens supplied by a trusted caller.
  They are never normalized or used to infer subject kind. Do not supply raw
  personal data. Customer and session references occupy separate namespaces.
- `CustomerRepository.resolve_or_create` requires explicit `subject_kind`
  (`anonymous` or `registered`) and a timezone-aware `observed_at`.
  Repeating a reference preserves its ID and kind. A different kind raises
  `IdentityConflict`; there is no anonymous promotion or merge.
- `SessionRepository.resolve_or_create` requires an opaque session reference and
  timezone-aware `observed_at`. New sessions are unlinked by default. An explicit
  `customer_id` must reference an existing subject. The caller is responsible for
  authorization and authoritative identity input; the repository does not verify
  identity with a provider.
- Ownership is fixed at creation. Repeated resolution must supply the same
  `customer_id`, including `None`. Linking an existing unlinked session,
  unlinking or reassigning a session raises `IdentityConflict`. Use lookup to
  retrieve an existing session when its owner is unknown to the caller.
- Distinct session references stay distinct, including unlinked sessions.
  Anonymous subjects are never grouped across sessions by inferred identity.
- Replays preserve the first stored creation/start time and advance activity
  with the greatest observed instant. Older events cannot regress activity.
  Atomic PostgreSQL conflict guards serialize competing creations; incompatible
  writers cannot overwrite kind or ownership.
- Repositories reject autocommit connections and never commit or close them.
  Let exceptions escape `Database.session()` to roll back the complete unit of
  work. Historical attribution and later identity linking need a separate policy.

## Synthetic example

```python
from datetime import datetime, timezone
from clavel.database.customer_sessions import CustomerRepository, SessionRepository

when = datetime(2026, 1, 1, tzinfo=timezone.utc)
with database.session() as connection:
    subject = CustomerRepository(connection).resolve_or_create(
        "synthetic-subject-1", subject_kind="anonymous", observed_at=when,
    )
    session = SessionRepository(connection).resolve_or_create(
        "synthetic-session-1", customer_id=subject.id, observed_at=when,
    )
```

## Validation for independent review

All identities, timestamps and records are synthetic. Tests ran against actual
local, disposable PostgreSQL databases migrated to head; these results prove
repository mechanics only. They provide no live identity/provider acceptance.
`CLAVEL_REQUIRE_POSTGRES=1` makes unavailable PostgreSQL fail rather than skip.

| Command | Result |
| --- | --- |
| `CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q tests/integration/test_customer_session_repositories.py` | 28 passed; no failures or skips |
| `CLAVEL_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -q tests/integration/test_customer_session_schema.py tests/integration/test_repositories.py tests/test_database.py` | 59 passed; no failures or skips; one Starlette/httpx deprecation warning |

New tests cover repeat resolution after reconnect, unknown lookups without
creation, separation of anonymous subjects and unlinked sessions, explicit
ownership, forbidden promotion/link changes, missing foreign keys, rollback,
activity replay and timezone offsets, invalid inputs, case-sensitive literal
references, and concurrent matching/conflicting customer/session creation.

No task-specific decision gate or live input is required for this repository
slice. Review the immutable-link policy, transaction behavior and synthetic test
evidence before assigning acceptance; `log/STATUS.md` remains orchestrator-owned.
