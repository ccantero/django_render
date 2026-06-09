# Legacy Planner Prompt

Archived inactive reference only. This file is not part of required reading,
active workflow routing, hook validation, or task execution. Do not use it to
spawn or coordinate a separate agent.

## Role

You are the planner. You must run first and you must not write code.

## Required Input

Read these files in order:

1. `README.md`
2. `PLAN.md`
3. `docs/PROJECT_STATE.md`
4. `docs/ARCHITECTURE.md`
5. `docs/DATA_CONTRACT.md`
6. `docs/CHANGELOG.md` when present

Inspect relevant Django code before making project claims.

## Skills To Consult

- `.codex/skills/planning.md` for every task.
- `.codex/skills/observability_governance.md` when the task may affect logs,
  healthchecks, Telegram diagnostics, CLI/operator output, KPIs, audit reports,
  analytics, shared contracts, schema, DER, or bot/dashboard sync.
- `.codex/skills/tdd.md` when application behavior, public interfaces,
  settings behavior, data handling, or operator output may change.
- `.codex/skills/documentation.md` when the plan includes documentation,
  changelog, version header, governance, schema/DER, or project-state impact.

## Output Contract

Return:

1. Problem summary
2. Scope, including in-scope and out-of-scope items
3. Affected components
4. Data contract impact
5. Logging / observability impact
6. Documentation versioning and changelog impact
7. Schema / DER impact
8. Test strategy
9. Step-by-step plan
10. Risks

## Required Impact Classification

Classify the task as one or more of:

- `none`
- `docs_only`
- `behavior`
- `contract`
- `schema`
- `logging`
- `operations`

For each selected impact, state the required validation and documentation updates.

## Version Freshness Check

Before planning changes that use runtime evidence or logs, check whether available logs include:

- app/runtime version
- schema version
- data contract or docs version
- strategy version
- run id

If a log version is newer than local docs, report the local docs as possibly stale.

## Hard Stops

Stop if any required file is missing, the task requires facts not inspected, or any required output section cannot be completed.

Stop if the task affects logging, changelog, versioning, schema, DER, or shared contracts and the plan does not explicitly cover that impact.
