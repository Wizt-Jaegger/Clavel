# AGENTS.md — Clavel (Codex rules, read once per session)

Stack: Python, FastAPI, PostgreSQL, pytest, REST, modular monolith. BIRCH clustering, segment-level popularity recommendations. Details: CONTEXT.md (read only if the task needs it).

## Token and context discipline
1. Per session read ONLY: this file, INDEX.md row for the task, `tasks/<ID>.md`. Do not open other tasks, the full backlog or the original docs.
2. Check prerequisites in INDEX.md against `log/STATUS.md`. If one is not Accepted, write a blocker and stop.
3. Explore the repo with targeted `rg`/`ls`/`sed -n` ranges. Never `cat` large files or print full test/command output; show the last ~30 lines or failures only.
4. One task per session. Work and commit directly on `main` (no task branches). Do not touch unrelated files. No refactors outside scope.
5. Replies stay short: changed paths, commands + result, SHA, next step. No restating the prompt.
6. Paths in tasks are references: discover real paths first. Empty tree is OK only for bootstrap tasks.
7. Python env: use a project-local `.venv` (`uv venv` or `python -m venv`), install dependencies there, and run tests as `.venv/bin/python -m pytest`. Never rely on a global pytest.

## Work rules
- Smallest relevant test suite plus the task's "Done when" check. Commit only after validation, with the message in the task file.
- Fixtures must be marked synthetic/provenance. Synthetic results prove mechanics only.
- Decision gates (Q01–Q12) block only the live slice named in the task. Do fixture/doc work, record the live check as Blocked.
- Contract (OpenAPI) changes: propose diff + examples + migration impact; do not edit silently.
- Never put secrets or raw personal data in code, logs, commits or prompts. Only `.env.example` with fake values.
- Unknown/stale stock or unknown compatibility is never treated as verified/eligible. Preserve unknown states.
- Status vocabulary: Pending, In progress, Blocked, Awaiting review, Changes requested, Accepted. You may set at most Awaiting review; only the reviewer sets Accepted (record reviewer, SHA, date).

## MANDATORY LOGGING (every action, no exceptions)
Maintain append-only `log/CODEX_LOG.md` (never rewrite or delete past lines; commit it with the task).
- Immediately before work: `START <ID> | <UTC ISO time> | branch | base SHA`.
- One line per event, written right after it happens, format:
  `<UTC time> | <ID> | <TYPE> | <detail>`
  TYPE = READ (files opened), CMD (exact command + exit code + 1-line result), EDIT (path + purpose), TEST (command + pass/fail counts), DECISION (what + why), ASSUMPTION, SKIP (check skipped + reason), BLOCKER, ERROR, COMMIT (SHA + message).
- Log failed attempts and retries, not only successes.
- Close with `END <ID> | status | final SHA | open items | next step`.
- Update the task row in `log/STATUS.md` (status, branch/SHA, tests, blocker, next step).
- Helper: `log/log.sh <ID> <TYPE> "<detail>"` appends a correctly formatted line.
- Log actions and stated rationale only; never secrets or raw personal data.
- If you did not log it, it did not happen: before ending the session, check the log covers every command run and file edited.

## Templates (read only when the task is that type)
- Review a task: templates/REVIEW.md
- Handoff (P0045/P0046, E0003/E0004): templates/HANDOFF.md
- Checkpoint (P0007, P0022, P0044): templates/CHECKPOINT.md
- Blocker: templates/BLOCKER.md (also append a BLOCKER line to the log)

# AGENTS.md — Clavel, Emi's tasks (Codex rules, read once per session)

Stack: Python, FastAPI, PostgreSQL, pytest, REST, modular monolith. Emi's scope: independent review, tuning workflow (local Ollama/Qwen + Jeff approval), governance, metrics, security, release. Details: CONTEXT.md (read only if the task needs it).

## Token and context discipline
1. Per session read ONLY: this file, the task's INDEX.md row, `tasks/<ID>.md`. Do not open other tasks, the full backlog or the original docs.
2. Check prerequisites in INDEX.md against `log/STATUS.md` (P-/M-tasks of other owners are listed there or in `log/EXTERNAL_ACCEPTED.txt`). If one is not Accepted, write a blocker and stop.
3. Explore the repo with targeted `rg`/`ls`/`sed -n` ranges. Never `cat` large files or print full test/command output; show the last ~30 lines or failures only.
4. One task per session. Work and commit directly on `main` (no task branches). Do not touch unrelated files. No refactors outside scope.
5. Replies stay short: changed paths, commands + result, SHA, next step. No restating the prompt.
6. Paths in tasks are references: discover real paths first.
7. Python env: use the project-local `.venv`; run tests as `.venv/bin/python -m pytest`. Never rely on a global pytest.

## Work rules
- Before changing backend code (E0005 onward), verify that E0004 is Accepted and records the accepted P0046 SHA; if not, report the blocker. E0001–E0004 are review/preparation only: no backend implementation.
- Smallest relevant test suite plus the task's "Done when" check. Commit only after validation, with the message in the task file.
- Label evidence: fixture/synthetic/test-double vs live. Never present synthetic or double-based results as live acceptance.
- Decision gates (Q01–Q12) block only the live slice named in the task. Do fixture/doc work, record the live check as Blocked. Never invent Jeff's provider protocol, auth or the Qwen tag: unknown stays blocked.
- Qwen only proposes allowlisted, bounded deltas; it gets no execution capability. Promotion, pause and rollback use transactions/compare-and-swap; decisions bind to the exact candidate and report. Rejection or provider failure keeps the active version serving.
- Contract (OpenAPI) changes: propose diff + examples + migration impact for Manu's review; do not edit silently.
- Never put secrets, credentials, endpoints with tokens or raw personal data in code, logs, commits, prompts or evidence. Redact outputs.
- Preserve unknown/unavailable states in APIs; unavailable ratios differ from zero counts.
- Status vocabulary: Pending, In progress, Blocked, Awaiting review, Changes requested, Accepted. Codex may set at most Awaiting review; only the reviewer sets Accepted. Tasks marked human gate end in Awaiting review for the person to sign.
- In automated mode `log/STATUS.md` is managed by the orchestrator: do not edit it.

## MANDATORY LOGGING (every action, no exceptions)
Maintain append-only `log/CODEX_LOG.md` (never rewrite or delete past lines; commit it with the task).
- Immediately before work: `START <ID> | <UTC ISO time> | base SHA`.
- One line per event, right after it happens: `<UTC time> | <ID> | <TYPE> | <detail>`
  TYPE = READ, CMD (exact command + exit code + 1-line result), EDIT (path + purpose), TEST (command + pass/fail counts), DECISION (what + why), ASSUMPTION, SKIP (check + reason), BLOCKER, ERROR, COMMIT (SHA + message).
- Log failed attempts and retries, not only successes.
- Close with `END <ID> | status | final SHA | open items | next step`.
- Helper: `log/log.sh <ID> <TYPE> "<detail>"`.
- Log actions and stated rationale only; never secrets or raw personal data.
- Before ending, check the log covers every command run and file edited.

## Templates (read only when the task is that type)
- Review a task: templates/REVIEW.md
- Handoff (E0003/E0004): templates/HANDOFF.md
- Checkpoint (E0019, E0036, E0043): templates/CHECKPOINT.md
- Blocker: templates/BLOCKER.md (also append a BLOCKER line to the log)
