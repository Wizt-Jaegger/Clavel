# Clavel

Clavel is planned as a Python/FastAPI modular monolith with PostgreSQL,
pytest, BIRCH clustering, and segment-level popularity recommendations.
This checkout establishes the repository operating rules; application setup
and business features belong to later tasks.

## Start contributing

1. Read [AGENTS.md](AGENTS.md) before making changes.
2. Select the assigned task in [INDEX.md](INDEX.md), then read its task file.
3. Check its prerequisites in [log/STATUS.md](log/STATUS.md). Every prerequisite
   must be Accepted by a reviewer before dependent work starts.
4. Follow the branch, scope, validation, and append-only logging rules in
   AGENTS.md. Record work in [log/CODEX_LOG.md](log/CODEX_LOG.md).
5. Submit the validated commit as Awaiting review. A reviewer records acceptance
   with their name, the reviewed SHA, and date in STATUS.md.

The task implementer owns scoped edits, evidence, and the handoff. The reviewer
owns acceptance; implementing a task does not authorize self-acceptance.

## Planning source

The initial planning kit is read-only at
`/home/alonso/Documents/clavel-codex-kit`. Only P0001 is imported here.
For a future task, read only its INDEX.md row, task file, prerequisite statuses,
and any required template from that kit, then import the assigned task's row
and task file. Record its local status without changing the source kit.
The source status file contains duplicate rows; use one canonical local row
per imported task and preserve reviewer evidence. Conflicting prerequisite
statuses require a blocker, not inferred acceptance.

## Bootstrap verification

Run the contribution checks from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_repository_rules.py' -v
```

These standard-library checks validate the contribution entry point, task links,
operating rules, and canonical P0001 status. They do not validate application
behavior. P0001 also runs these checks from a clean export of the P0001 files to
verify that the committed files are sufficient for a fresh checkout.
