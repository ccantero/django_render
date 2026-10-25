---
doc_id: disposable-postgresql-testing
doc_version: 1.0.0
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-10-18
source_repo: django_render
---

# Disposable PostgreSQL Testing

## Purpose

Use this runbook to validate Django changes that depend on real PostgreSQL
behavior. The current harness was added for Passkey/WebAuthn validation, where
SQLite cannot establish that PostgreSQL row locks permit exactly one concurrent
consumer of a one-time proof or challenge, nor that a database-backed rate
limit preserves every concurrent attempt.

SQLite remains useful for fast unit and application-flow tests. It is not
evidence that PostgreSQL transaction, locking, schema-search-path, sequence,
or concurrent-consumption behavior is correct. PostgreSQL validation is
mandatory when a change affects those properties, PostgreSQL-specific test
setup, migrations, or the affected concurrency controls.

The implementation is in:

- `scripts/run_passkey_postgres_disposable_test.sh`
- `django_render/postgres_test_settings.py`
- `tests/test_passkey_postgres_concurrency.py`
- `tests/test_postgres_test_isolation.py`

## Two Separate Environments

### ChatGPT Work Cloud / restricted agent environment

This environment is suitable for repository inspection, documentation and code
editing, static checks, and tests that its local capabilities support. It may
also support SQLite tests and Git/GitHub operations. It must verify those
capabilities per session.

It may not have Docker-daemon permission, a usable PostgreSQL service, or the
privilege transitions required by PostgreSQL/container initialization. A
restricted agent must not request Docker-group membership, use `sudo`, alter
Docker or PostgreSQL configuration, or substitute another database target. If
the disposable environment cannot run, report that PostgreSQL validation is
unavailable; do not claim skipped tests passed.

### Authorized disposable PostgreSQL environment

An authorized operator runs the existing harness on a host with Docker access.
That host creates a new PostgreSQL 16 container, volume, role, databases, and
test schemas for one run, then removes only resources labelled as owned by the
same run. It is not production, staging, Supabase, or an existing bot database.

The two environments cooperate through source control and auditable command
output. Work Cloud does not automatically obtain authority to use the operator
environment.

## Prerequisites

Required on the authorized host:

- Docker CLI and permission to use its daemon.
- `openssl` and a Bash-compatible shell.
- An executable Python interpreter with this repository's application and test
  requirements installed. The default is `<repo>/.venv/bin/python`; an
  absolute `PYTHON_BIN` override is supported.
- The repository checkout containing the harness and its PostgreSQL test
  settings.

The harness pulls `postgres:16`; the observed historical operator run reported
PostgreSQL 16.15. The script does not install Python dependencies, run `pip
check`, or run `pip-audit`; perform those separately when dependency validation
is in scope.

Do not provide or source production `.env` files. Before invocation,
`DATABASE_URL`, `SUPABASE_DATABASE_URL`, and `PASSKEY_TEST_DATABASE_URL` must
be absent. The harness rejects them if inherited from the caller.

## Quick Start

From the repository root, using an already prepared absolute Python path:

```bash
env -u DATABASE_URL -u SUPABASE_DATABASE_URL -u PASSKEY_TEST_DATABASE_URL \
  PYTHON_BIN=/absolute/path/to/python \
  bash scripts/run_passkey_postgres_disposable_test.sh
```

To use the default repository virtual environment, omit `PYTHON_BIN`:

```bash
env -u DATABASE_URL -u SUPABASE_DATABASE_URL -u PASSKEY_TEST_DATABASE_URL \
  bash scripts/run_passkey_postgres_disposable_test.sh
```

`PYTHON_BIN` must be an executable absolute path. Do not replace the command
with ad-hoc Docker, `psql`, or database commands: the harness contains the
target guards, test-template preparation, and cleanup verification needed for
this workflow.

## Execution Lifecycle

1. **Preflight.** The script requires `docker` and `openssl`, selects the
   default or overridden interpreter, rejects relative/non-executable
   interpreters, and rejects inherited database-target variables.
2. **Disposable startup.** It derives a random UUID token and creates a
   uniquely named PostgreSQL 16 container and volume. PostgreSQL is published
   only as `127.0.0.1::<random-port>` and waits for Docker health checks.
3. **Database initialization.** Inside that new container only, it creates the
   non-superuser `passkey_test` login role with `CREATEDB`, one disposable base
   database, and one run-owned template database. The role owns both. The
   databases receive the Django-owned `django` schema; the template also gets
   a disposable `bot` schema for test fixtures.
4. **Guarded Django configuration.** The harness starts Django with an empty
   environment (`env -i`), `DJANGO_SKIP_ENV_FILE=1`,
   `django_render.postgres_test_settings`, generated database passwords, a
   synthetic key, and synthetic test-only settings. The settings module accepts
   only loopback PostgreSQL URLs, the `passkey_test` role, a random
   `test_passkey_validation_<12 hex>` database name, a matching random template
   and Django test database name, and a `.test` host. It sets search path to
   `django,public`; bot fixture tables remain schema-qualified.
5. **Fresh migrations.** The harness runs `manage.py migrate --noinput` using
   the guarded settings.
6. **Migration consistency.** It runs
   `manage.py makemigrations --check --dry-run`. This is an independent stage;
   failure does not prevent later nonterminal validation stages.
7. **Deployment security check.** It runs `manage.py check --deploy --fail-level
   WARNING` with `DEBUG=False`, HTTPS-only synthetic Passkey origin settings,
   and secure-cookie/proxy settings from the test settings module.
8. **PostgreSQL concurrency tests.** It runs each of the three cases in
   `tests/test_passkey_postgres_concurrency.py` alone, then all three together,
   then all three again. It parses JUnit XML and requires exactly the expected
   count with zero skips, failures, and errors.
9. **Full suite.** It runs `pytest -q -rs -o addopts=''`, deliberately
   overriding the repository's speed-oriented `--reuse-db --nomigrations`
   defaults so this validation uses migrations and does not reuse a test
   database.
10. **Cleanup verification.** It verifies Django removed its named test
    database. Its exit trap then removes the uniquely named container and
    volume only after matching the per-run ownership label, removes its
    temporary directory, prints stage results, and verifies removal.

## What the Concurrency Tests Prove

The PostgreSQL-only `TransactionTestCase` suite uses independent connections,
a barrier, and concurrent workers. It verifies:

- only one consumer can consume the same password-plus-enrollment proof pair;
- only one consumer can consume the same enrollment WebAuthn step-up challenge;
- a concurrent rate-limit window accepts only its configured number of
  attempts and records that exact count.

The tests are decorated to skip outside PostgreSQL. The harness makes such a
skip a failure by inspecting the JUnit result, so a successful harness
concurrency stage is evidence that the PostgreSQL tests actually ran.

## Safety Controls

### Enforced by the repository

- Caller-supplied database URLs for `DATABASE_URL`, `SUPABASE_DATABASE_URL`,
  and `PASSKEY_TEST_DATABASE_URL` cause immediate failure.
- The test settings reject non-loopback hosts, non-PostgreSQL schemes, an
  unexpected role, database/template/test-name patterns, and non-`.test`
  hosts before a Django database connection is configured.
- The harness creates random passwords without printing them and does not load
  a `.env` file.
- Docker port publication is explicitly loopback-only.
- The ordinary test role is not a superuser. Its `CREATEDB` privilege is used
  for Django's disposable test-database lifecycle.
- The cleanup trap runs on both success and failure. It refuses to remove a
  container or volume whose ownership label does not match this run.
- PostgreSQL fixture cleanup includes the disposable cross-schema dust-review
  tables in Django's flush set without `TRUNCATE ... CASCADE`, disabling
  constraints, changing bot-table ownership, or touching external bot tables.

### Required operator discipline

- Run only from an authorized local development host; never point it at a
  shared or production database.
- Do not export real credentials for this run and do not override the guarded
  settings module.
- Review the final stage lines and cleanup verification, including after a
  failing test run.
- Keep a copy of the resulting log with the commit SHA and interpreter/package
  inventory when using it as merge evidence.

## Dependency Preflight (Outside the Harness)

Use the same interpreter intended for the harness. The following are separate
commands, not stages the script performs:

```bash
/absolute/path/to/python -m pip check
/absolute/path/to/python -m pip_audit --requirement requirements.txt
/absolute/path/to/python -m pip freeze
```

`pip_audit` must be installed in that isolated environment for the second
command. The repository intentionally has no lockfile, so record the resolved
package inventory and Python version; deployment resolution still requires its
own verification.

## Failure Handling and Interpretation

The harness prints `VALIDATION_STAGE_<name> = PASS`, `FAIL`, or `NOT_RUN` for
database initialization, migrations, migration consistency, security checks,
PostgreSQL concurrency, the full suite, and Django test-database cleanup. It
also prints `VALIDATION_OVERALL` and
`DISPOSABLE_RESOURCE_CLEANUP_VERIFIED` from its exit trap.

- **PASS stage:** that stage's command and assertions completed successfully.
- **Skipped concurrency test:** unacceptable for this workflow; JUnit
  verification turns it into a failed concurrency stage.
- **Unavailable environment:** Docker, PostgreSQL initialization, required
  interpreter, or dependencies could not be used. This is not a pass; report
  it and do not bypass the harness.
- **FAIL stage:** retain its command output. Nonterminal failures allow later
  stages to run, while database-initialization or fresh-migration failures stop
  dependent stages.
- **Cleanup failure:** `DISPOSABLE_RESOURCE_CLEANUP_VERIFIED = NO` is a failed
  validation outcome requiring manual inspection of only the run-labelled
  resources.
- **Aggregate FAIL:** any required failed stage, a failing command, or failed
  cleanup makes the aggregate fail. Passing functional stages do not change
  that aggregate result.

### Known baseline migration drift

The harness recognizes output naming
`core/migrations/0005_manualcorrection_alter_dustsignalreview_options.py` and
labels it:

```text
MIGRATION_CONSISTENCY = PRE_EXISTING_ORIGIN_MAIN_DRIFT
```

This classification records a known historical drift independently found in
`origin/main`; it does **not** suppress the migration-consistency failure. The
stage remains `FAIL` and therefore the aggregate remains:

```text
VALIDATION_OVERALL = FAIL
```

Do not create that migration merely to turn this harness result green unless a
separately scoped migration-repair task establishes that it is correct.

## Troubleshooting

- **`docker is required` or daemon permission failure:** use an authorized
  Docker-capable host. Do not use `sudo`, change group membership, or alter
  Docker permissions as part of validation.
- **Forbidden database-variable failure:** start with the Quick Start `env -u`
  command. Do not substitute the inherited URL.
- **Interpreter failure:** provide an executable absolute `PYTHON_BIN` with
  the project and test requirements installed.
- **Database initialization failure:** retain the harness output. No migrations
  or tests should be reported as run if initialization failed.
- **Migration drift:** report its exact classification separately from test
  results; do not call the harness aggregate successful.
- **Concurrency failure or zero/skip mismatch:** treat it as a PostgreSQL
  correctness failure, not an invitation to mark the tests skipped.
- **Full-suite failure:** classify the underlying test failure independently;
  a successful concurrency stage does not make the full suite pass.
- **Cleanup failure:** inspect only names bearing the harness's UUID-derived
  name and ownership label; do not remove unrelated Docker resources.

## Historical Evidence (Example Only)

An authorized operator's final PR #2 validation was reported with PostgreSQL
16.15, Python 3.12.9, remediated dependencies, fresh migrations, deployment
security checks, individually/combined/repeated concurrency runs with zero
skips, test-database cleanup, and Docker-resource cleanup. A later handoff
reported 372 full-suite passes, 1 warning, and 33 subtests passed.

Available archived logs and handoffs do not agree on every warning count (one
archived final-review log reports 2 warnings). These are historical evidence,
not a new execution. Always report the actual command output from the current
run and keep the known baseline migration-drift result separate from functional
test results.

## Example Validation Report Template

```text
Commit: <git rev-parse HEAD>
Host/environment: <authorized disposable PostgreSQL host; not production>
Python: <absolute interpreter path and --version>
Resolved dependencies: <pip freeze artifact or hash>
PostgreSQL: <POSTGRES_VERSION output>

Commands:
  <pip check command, if run>
  <pip_audit command, if run>
  env -u DATABASE_URL -u SUPABASE_DATABASE_URL -u PASSKEY_TEST_DATABASE_URL \
    PYTHON_BIN=<absolute interpreter> \
    bash scripts/run_passkey_postgres_disposable_test.sh

Stages:
  database initialization: <PASS|FAIL|NOT_RUN>
  fresh migrations: <PASS|FAIL|NOT_RUN>
  migration consistency: <PASS|FAIL|PRE_EXISTING_ORIGIN_MAIN_DRIFT>
  deployment security checks: <PASS|FAIL|NOT_RUN>
  concurrency individual/combined/repeat: <counts, skips, warnings>
  full Django suite: <passed/failed/skipped/warnings/subtests>
  Django test-database cleanup: <YES|NO>
  Docker container/volume cleanup: <YES|NO>

Aggregate: <VALIDATION_OVERALL value>
Unverified items: <for example proxy configuration or real-device testing>
```

This template must not be filled with a prior run's values unless it explicitly
identifies that run's commit, environment, interpreter, and source log.
