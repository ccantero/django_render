# Codex Agent System

This project uses a strict, hard-enforcement Codex workflow. The workflow is mandatory for every task and every role must run in order.

## Required Reading Order

Before planning or changing anything, read these files in this order:

1. `README.md`
2. `PLAN.md`
3. `docs/PROJECT_STATE.md`
4. `docs/ARCHITECTURE.md`
5. `docs/DATA_CONTRACT.md`

If any file is missing, stop and report failure before making project changes.

## Mandatory Workflow

The only valid order is:

1. planner
2. implementer
3. tester
4. documentator

No step can be skipped, reordered, merged, or treated as optional. If any step is missing, stop and report failure.

## Global Rules

- Do not overwrite useful existing content.
- Extend existing files when possible.
- Do not invent architecture.
- Do not add dependencies unless the planner explicitly scopes them and the user approves.
- Do not modify application code unless strictly required by the planned task.
- Only document what actually exists.
- Inspect the Django project before writing docs.
- Preserve unrelated user changes in the worktree.
- Treat documentation, runtime logs, schema snapshots, and changelog entries as operational artifacts, not cosmetic files.
- Prefer generated facts over guessed facts for schema and DER documentation.
- When documentation versions, schema versions, or runtime log versions disagree, report the mismatch instead of assuming the local docs are current.

## Documentation Governance

Every meaningful task must classify its documentation impact:

- `none`: no behavior, workflow, setup, architecture, data contract, schema, logging, or operational state changed.
- `docs_only`: documentation or governance changed, but application behavior did not.
- `behavior`: runtime behavior, settings, user workflow, data handling, tests, or public interface changed.
- `contract`: bot-owned table semantics, shared DB interpretation, healthcheck payloads, logs consumed by operators, or dashboard read-model assumptions changed.
- `schema`: database tables, columns, constraints, indexes, migrations, DER, or schema snapshots changed.

For `behavior`, `contract`, or `schema` impact, update at least one documentation file and add or update an entry in `docs/CHANGELOG.md` when that file exists or is introduced by the task.

## Versioning Policy

All core documentation files should carry a lightweight version header when touched:

```yaml
---
doc_id: <stable-doc-id>
doc_version: <semver>
schema_version: <semver-or-unknown>
runtime_min_version: <app-version-or-unknown>
last_verified_at: <YYYY-MM-DD>
source_repo: <repo-name>
---
```

Rules:

- Increment `doc_version` when the document content changes.
- Increment or update `schema_version` only when the database contract/schema changed.
- Do not invent app versions. If the project has no version source yet, use `unknown` and add a follow-up.
- If runtime logs show a newer app/schema/docs version than the local documentation, flag stale documentation in the final report.
- If `docs/DATA_CONTRACT.md` changes in either the bot or dashboard repository, verify and update the paired copy in the same task or record a blocking follow-up.

## Logging Governance

When touching runtime logging, operational alerts, healthcheck payloads, Telegram diagnostics, or CLI output, require structured/versioned context.

Recommended log context keys:

```json
{
  "app_version": "unknown",
  "schema_version": "unknown",
  "data_contract_version": "unknown",
  "strategy_version": "unknown",
  "run_id": "...",
  "event": "...",
  "component": "..."
}
```

Rules:

- Do not remove existing useful log fields.
- Prefer additive structured fields over changing existing message text.
- Keep secrets out of logs.
- Logs used by operators or ChatGPT review must include enough version context to detect stale documentation.
- If a log line is intentionally unstructured because of a third-party limitation, document that exception.

## Changelog Policy

Use `docs/CHANGELOG.md` for operator-relevant changes. If the file does not exist and the task changes behavior, contracts, schema, logging, docs governance, or operational workflow, create it.

Recommended entry shape:

```md
## YYYY-MM-DD - Short title

Type: behavior | contract | schema | docs | logging | operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/DATA_CONTRACT.md

Summary:
- ...

Operator impact:
- ...

Validation:
- ...
```

Rules:

- Changelog entries must describe verified changes only.
- Do not duplicate entire `PLAN.md` sections; link or summarize.
- Include migration/schema/DER commands when applicable.
- Include known follow-ups when docs, schema snapshots, or paired repository docs could not be verified.

## DER and Schema Snapshot Policy

When database schema or contract semantics change, prefer adding or updating generated schema artifacts:

- `docs/db/DER.md`
- `docs/db/schema_snapshot.sql`
- `docs/db/schema_columns.csv`
- `docs/db/schema_indexes.csv`
- `docs/db/schema_constraints.csv`
- `docs/db/schema_diff_<YYYYMMDD>.md`

Rules:

- Generate schema facts from the database or migrations when possible.
- Mark snapshots with generation timestamp, source database, and command used.
- Do not hand-write a DER that claims to be generated unless it was generated.
- If the current database cannot be reached, update contract docs from code/migrations and record the missing generated snapshot as a follow-up.

## Planner Enforcement

The planner must run first and must not write code.

Planner output must include:

1. Problem summary
2. Scope, including in-scope and out-of-scope work
3. Affected components
4. Data contract impact
5. Logging / observability impact
6. Documentation versioning and changelog impact
7. Schema / DER impact
8. Test strategy
9. Step-by-step plan
10. Risks

Failure conditions:

- Planner did not run first.
- Planner wrote code or changed app behavior.
- Any required planner output section is missing.
- The planner skips project inspection when project facts are needed.
- The planner ignores a possible contract, log, changelog, or schema/DER impact.

If any planner failure occurs, stop and report failure.

## Implementer Enforcement

The implementer uses TDD hard mode for application behavior changes.

Required order:

1. Create a failing test.
2. Confirm the test fails for the expected reason.
3. Implement the minimal fix.
4. Re-run the test and confirm it passes.

Failure conditions:

- Implementation starts before the failing test exists.
- No test is created for an application behavior change.
- The test is not run before implementation.
- The initial failure is missing or fails for an unexpected reason.
- The implementation includes unrelated refactors.
- Runtime logging changes do not preserve existing useful context.
- Schema or contract changes omit the planned docs/changelog/schema snapshot work.

If any implementer failure occurs, stop and report failure.

For documentation-only or governance-only changes, the implementer must explicitly record that no application behavior changed and that no new behavior test was created.

## Tester Enforcement

The tester must run after implementation.

Tester duties:

- Validate target tests.
- Run a broader suite when shared logic, settings, models, URLs, templates, serializers, data contracts, logging contracts, schema snapshots, or documentation governance changed.
- Add edge-case tests when the planned behavior is under-tested.
- For logging changes, validate the expected structured fields or explicitly justify why this is not testable.
- For schema/DER changes, validate generation commands or record why they could not be run.
- Do not fix unrelated failures unless a new plan explicitly scopes that work.

Failure conditions:

- Tests were not executed.
- Target tests were skipped without justification.
- Broader tests were skipped after shared behavior changed.
- Logging/schema/docs governance validation was skipped without justification.
- Unrelated failures were silently fixed or hidden.

If any tester failure occurs, stop and report failure.

## Documentator Enforcement

The documentator must always review:

- `README.md`
- `PLAN.md`
- `docs/DATA_CONTRACT.md`
- `docs/PROJECT_STATE.md`
- `docs/DESIGN.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md` when present or when the task should introduce it
- `docs/db/*` when schema, DER, index, constraint, or DB contract facts changed

The documentator must update at least one file when behavior, workflow, project state, contracts, setup, logging, schema, DER, or architecture changes. If nothing changed, the documentator must explicitly justify why no documentation update was required.

Failure conditions:

- Any required documentation file was not reviewed.
- No documentation file was updated after a meaningful change.
- No explicit justification is provided for leaving docs unchanged.
- Documentation invents architecture or behavior not present in the project.
- A contract/schema/logging change lacks changelog coverage or an explicit reason for deferring it.
- Documentation version headers are stale after touched files changed.

If any documentator failure occurs, stop and report failure.

## Django Inspection Checklist

Before documenting or planning Django changes, inspect:

- apps
- models
- views and API views
- serializers
- urls
- settings
- tests
- templates and static files
- management commands
- DRF usage
- pytest or unittest usage
- Celery, Redis, PostgreSQL, SQLite, Docker, and environment variables

## Final Output Contract

Every task must report:

1. Planner output
2. Tests created and failing proof
3. Code changes
4. Tests executed
5. Docs updated
6. Documentation version/changelog result
7. Logging/observability result
8. Schema/DER result
9. Pending issues

If any enforcement rule failed, the final output must clearly say `FAILURE` and identify the missing or invalid step.
