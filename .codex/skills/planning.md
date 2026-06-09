# Planning Skill

## When To Use

Use this skill first for every project task. It is mandatory before code, tests, documentation changes, or command execution that affects project state.

## Steps

1. Read the required project files in order:
   - `README.md`
   - `PLAN.md`
   - `docs/PROJECT_STATE.md`
   - `docs/ARCHITECTURE.md`
   - `docs/DATA_CONTRACT.md`
   - `docs/CHANGELOG.md` when present
2. Inspect the relevant Django code before describing architecture or behavior.
3. Classify the task impact:
   - `none`
   - `docs_only`
   - `behavior`
   - `contract`
   - `schema`
4. Check freshness signals:
   - runtime/app version if available
   - strategy version if available
   - schema version if available
   - data contract/doc version if available
   - migration or schema snapshot state if relevant
5. Produce the planner output:
   - Problem summary
   - Scope, with in-scope and out-of-scope work
   - Affected components
   - Data contract impact
   - Logging / observability impact
   - Documentation versioning and changelog impact
   - Schema / DER impact
   - Test strategy
   - Step-by-step plan
   - Risks
6. Continue to the Implementer phase only after every required section exists.

## Documentation Governance Planning

When a task may affect docs, logs, schema, or operator workflows, explicitly plan:

- which Markdown files must be touched
- whether `docs/CHANGELOG.md` should be created or updated
- whether documentation version headers must be added or incremented
- whether paired bot/dashboard contract files must be synchronized
- whether `docs/db/DER.md` or schema snapshot files must be generated or updated

## Logging Planning

When touching logs, CLI output, alerts, Telegram diagnostics, healthcheck payloads, or operator reports, explicitly plan whether the output must include:

- `app_version`
- `schema_version`
- `data_contract_version`
- `strategy_version`
- `run_id`
- stable event/reason fields

If any of these cannot be sourced from the project yet, plan a safe fallback such as `unknown` and a follow-up.

## Failure Conditions

- Planning is not the first phase.
- The planner writes code.
- Required files are missing and the task continues anyway.
- A required planner output section is missing.
- The plan invents architecture or behavior not found in the project.
- The plan ignores logging/versioning/changelog/schema impact when the task plausibly affects those areas.

On failure, stop and report the missing condition.
