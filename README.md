# Clavel

Clavel is planned as a Python/FastAPI modular monolith with PostgreSQL,
pytest, BIRCH clustering, and segment-level popularity recommendations.
This checkout establishes the repository operating rules and Python project
setup. Business features belong to later tasks.

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

## Python setup and tests

Use Python 3.13.x (the supported minor version is recorded in `.python-version`
and enforced by `requires-python` in `pyproject.toml`). Keep environments local
to the project. Future Python minor versions require an explicit policy update
and validation; use the latest available 3.13 patch release.

From a fresh checkout:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Runtime dependencies provide FastAPI and the PostgreSQL driver, psycopg with its
binary distribution. The `dev` extra adds pytest and the Uvicorn development
server. Dependency ranges are bounded in `pyproject.toml`; exact resolutions
may vary between installations.

Production code belongs under `src/clavel/`; tests belong under `tests/` in
`test_*.py` files. Pytest uses importlib mode so the smoke test exercises the
installed package. The smoke test imports the package and runtime libraries
without starting a server or connecting to a database. These checks establish
installation mechanics only; application behavior is covered by later tasks.
