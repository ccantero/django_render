# Codex Agent System

This project uses a strict single-agent Codex workflow. `STANDARD` is the
mandatory default and safety baseline. Unless a task clearly satisfies every
condition of a narrower mode below, one agent MUST run Planner → Implementer →
Tester → Documentator in order before the task is complete.

## Task Mode Selection

Before reading, planning, or changing project files, classify the task into
exactly one mode and state that mode in the first user-facing update.

### `STANDARD`

This is the default mode and the required fallback. Use it for:

- implementation, bugfixes, refactors, and tests
- mixed documentation and code changes
- planning tasks that update repository artifacts
- any project-state change that does not fully qualify for `DOCUMENTATION`
- mixed requests that ask both to investigate and to implement or fix
- any task whose correct mode, scope, or final deliverable is uncertain

`STANDARD` mode uses the complete Planner → Implementer → Tester →
Documentator workflow and all existing enforcement in this file.

Before selecting any narrower mode, confirm that its full eligibility rules
are satisfied. If scope expands beyond those rules at any time, stop, state the
reclassification, complete the `STANDARD` required reading, and restart at the
Planner phase before making further changes. A narrower mode must never be
used merely to skip a `STANDARD` phase.

### `INVESTIGATION`

Use it only when the user requests analysis or diagnosis without project
changes. Typical work includes:

- root-cause analysis and incident review
- watchdog, audit, reconciliation, SQL, or log review
- production behavior or performance analysis
- architecture understanding and code comprehension
- operational diagnosis

Investigation goals are to establish facts, review evidence, identify
hypotheses, identify missing evidence, and answer the investigation question.

Required investigation order:

1. State `Task mode: INVESTIGATION`.
2. Review only documentation relevant to the question.
3. Review only relevant code paths.
4. Review the provided or discovered evidence.
5. Separate verified facts from hypotheses.
6. State missing evidence explicitly.
7. Stop after conclusions and optional recommendations.

Forbidden in `INVESTIGATION` mode:

- creating or editing project files
- patches or implementation
- test creation or behavior changes
- documentation, changelog, schema, or roadmap updates
- commits or other project-state mutation

Expected investigation output:

1. Documents reviewed
2. Code reviewed
3. Evidence reviewed
4. Facts
5. Hypotheses
6. Missing evidence
7. Conclusions
8. Optional recommendations

If an investigation shows that a change is needed, stop the investigation
before editing. Reclassify the follow-up as `STANDARD`, then begin the complete
required reading and Planner phase. Never drift silently from investigation
into implementation.

### `PLANNING`

Use it only when the user explicitly requests a plan, roadmap, prioritization,
architecture proposal, technical design, or implementation approach without
asking for repository changes.

Required planning order:

1. State `Task mode: PLANNING`.
2. Review documentation relevant to the proposed work.
3. Review relevant code when project facts are needed.
4. Separate current verified facts from proposed future changes.
5. Produce the requested plan, options, tradeoffs, risks, and recommendation.
6. Stop without changing project state.

Forbidden in `PLANNING` mode:

- creating or editing project files
- implementation, patches, tests, or schema changes
- documentation or changelog updates
- commits or other project-state mutation

If the user asks to persist the plan or begin implementation, reclassify the
task as `STANDARD` before editing.

### `DOCUMENTATION`

Use it only when the requested deliverable changes documentation or
documentation-governance files and does not change application behavior,
tests, runtime configuration, schema, contracts, logs, operator output, hooks,
skills, templates, or other protected workflow infrastructure.

`DOCUMENTATION` is a specialized full-workflow profile. It MUST run:

1. Planner phase
2. Implementer phase, limited to documentation edits
3. Tester phase, using documentation and governance validation
4. Documentator phase

TDD and a new behavior test are not required when no application behavior
changes. The Implementer phase must record that fact explicitly. The Tester
phase must still execute relevant link, reference, version-header, formatting,
hook, or docs-governance checks.

If documentation work requires or discovers any non-documentation change,
contract/schema semantic change, operator-output change, or protected workflow
change, reclassify it as `STANDARD` before continuing.

`AGENTS.md` and files under `.codex/hooks/`, `.codex/lib/`, and
`.codex/templates/` remain protected workflow infrastructure. Changes to them
always use `STANDARD`, even when their content is documentation-like.

If the correct mode is uncertain, use `STANDARD`. These modes are internal
single-agent workflows; they do not authorize sub-agents or delegation.

## Required Reading Order

In `STANDARD` and `DOCUMENTATION` modes, before planning or changing anything,
read these files in this order:

1. `README.md`
2. `PLAN.md`
3. `docs/PROJECT_STATE.md`
4. `docs/ARCHITECTURE.md`
5. `docs/DATA_CONTRACT.md`

If any file is missing, stop and report failure before making project changes.

In `INVESTIGATION` and `PLANNING` modes, review only the documents directly
relevant to the question. The full reading list is not required because those
modes cannot change project state. If either task is reclassified to
`STANDARD`, complete the full reading list in order before planning or changing
anything.

## Mandatory Single-Agent Workflow

In `STANDARD` mode, the only valid order is:

1. Planner phase
2. Implementer phase
3. Tester phase
4. Documentator phase

No `STANDARD` phase can be skipped, reordered, merged, delegated to a separate
sub-agent, or treated as optional. If any phase is missing, stop and report
failure.

`INVESTIGATION` mode follows its read-only order above and does not run
Implementer, Tester, or Documentator phases because it is forbidden from
changing project state.

`PLANNING` mode follows its read-only order above and stops after producing the
plan.

`DOCUMENTATION` mode follows the same four mandatory phases as `STANDARD`, with
implementation and testing constrained to documentation work.

## Global Rules

- Do not overwrite useful existing content.
- Extend existing files when possible.
- Do not invent architecture.
- Do not add dependencies unless the Planner phase explicitly scopes them and the user approves.
- Do not modify application code unless strictly required by the planned task.
- Only document what actually exists.
- Inspect the Django project before writing docs.
- Preserve unrelated user changes in the worktree.
- Treat documentation, runtime logs, schema snapshots, and changelog entries as operational artifacts, not cosmetic files.
- Prefer generated facts over guessed facts for schema and DER documentation.
- When documentation versions, schema versions, or runtime log versions disagree, report the mismatch instead of assuming the local docs are current.
- Do not add, rename, or change the semantics of KPIs or operational diagnostics without reviewing `docs/KPI_REGISTRY.md`.
- If a change introduces a metric, renames an existing metric, changes a formula, changes source of truth, changes status, changes text/JSON output, or adds dashboard, Telegram, audit, healthcheck, or operator visibility, then update `docs/KPI_REGISTRY.md` or record explicit evidence: `reviewed, no update needed`.
- BUY capacity, Capital Velocity, Slot Efficiency, Trapped Capital, Churn/Re-entry, Dust/Residuals, Exit Quality, Performance/PnL, and Accounting/Reconciliation metrics must pass through the KPI Registry.

## Skill Routing

Use the versioned skills as single-agent phase guidance, not as loose notes.
Skills provide reusable governance context; they do not orchestrate separate
agents or replace the required Planner → Implementer → Tester → Documentator
phase order. Hooks and self-checks provide consistency evidence, but human
review remains required for protected workflow infrastructure changes.

| Change area | Required route |
| --- | --- |
| Read-only root-cause, incident, audit, log, SQL, performance, architecture, or operational analysis | `INVESTIGATION` mode; stop before any project change |
| Read-only roadmap, prioritization, architecture proposal, technical design, or implementation plan | `PLANNING` mode; stop before any project change |
| Planning any project task | Planner phase + `.codex/skills/planning.md` |
| Application behavior, public interface, data handling, settings, or operator-output changes | Implementer phase + `.codex/skills/tdd.md` |
| Test validation, broader suite selection, logging/schema/docs-governance validation | Tester phase + `.codex/skills/tdd.md` when behavior changed |
| Documentation, changelog, version headers, project-state or governance changes | Documentator phase + `.codex/skills/documentation.md` |
| Analytics, KPI, audit reports, dashboard metrics, healthcheck details, Telegram diagnostics, alerts, logs, or CLI output | `.codex/skills/observability_governance.md` + Documentator phase |
| DB semantics, shared table interpretation, `managed = False` model changes, healthcheck payload semantics, or bot/dashboard read-model assumptions | `.codex/skills/observability_governance.md` for contract/version review + Documentator phase |
| Trading behavior, BUY/SELL logic, accounting mutation, reconciliation, or safety-sensitive strategy changes | Planner + Implementer + Tester phases, with TDD and strategy/safety review evidence |
| Documentation-only changes outside protected workflow infrastructure | `DOCUMENTATION` mode with all four phases; use `.codex/skills/documentation.md` and documentation validation |
| Protected workflow infrastructure changes, including `AGENTS.md` | `STANDARD` mode with a separate plan, explicit approval, diff summary, validation, and manual review |

Current versioned skills:

- `.codex/skills/planning.md`
- `.codex/skills/tdd.md`
- `.codex/skills/documentation.md`
- `.codex/skills/observability_governance.md`

Deprecated sub-agent prompts have been moved to `.codex/legacy/subagents/`
for review only. They are not active workflow inputs and must not be used to
spawn or coordinate multiple agents.

## Protected Workflow Infrastructure

Files under `.codex/hooks/`, `.codex/lib/`, `.codex/templates/`, and `AGENTS.md` are protected workflow infrastructure.

Codex must not modify them unless the user explicitly asks for workflow-infrastructure changes.

Any change to these files requires:

1. explicit user approval,
2. a separate plan,
3. a diff summary,
4. manual review before commit.

Rules:

- Do not modify protected workflow infrastructure during normal feature, bugfix, docs, or refactor tasks.
- If protected workflow infrastructure changes are requested, keep them isolated from unrelated application changes.
- The final report must clearly list every protected file changed.
- Pre-commit must block protected workflow infrastructure changes unless `ALLOW_WORKFLOW_INFRA_CHANGE=1` is set.
- Using `ALLOW_WORKFLOW_INFRA_CHANGE=1` is allowed only after manual review.
- Hook evidence should stay compact. The enforced common evidence fields are
  `phases_completed`, `impact`, `tests_executed`, and `pending_issues`.
  Additional evidence is conditional on behavior, documentation/workflow,
  schema, contract, KPI, observability, or logging impact.
- Codex must generate workflow evidence for significant changes before commit.
  The default local evidence path is `.codex/workflow-evidence.md`; it is
  ignored by Git to avoid turning daily task evidence into protected
  infrastructure churn. Use `CODEX_WORKFLOW_EVIDENCE=/tmp/<task>.md` when a
  task-specific or disposable evidence file is clearer.
- For large or ambiguous changes, Codex must either confirm the intended
  evidence scope before commit or write provisional evidence and ask for
  review. High-risk changes must include tests, failing-test proof when
  behavior changed, docs/changelog handling, data-contract sync when relevant,
  logging/observability evidence when relevant, and pending issues. Small
  low-risk changes may use minimal evidence or explicit `not_applicable`
  justifications.

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

For `STANDARD` and `DOCUMENTATION` modes, the Planner phase must run first and
must not write code.

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

- Planner phase did not run first.
- Planner phase wrote code or changed app behavior.
- Any required Planner phase output section is missing.
- The Planner phase skips project inspection when project facts are needed.
- The Planner phase ignores a possible contract, log, changelog, or schema/DER impact.

If any Planner phase failure occurs, stop and report failure.

## Implementer Enforcement

For `STANDARD` mode, the Implementer phase uses TDD hard mode for application
behavior changes. In `DOCUMENTATION` mode, the Implementer may edit only
documentation and must explicitly record that application behavior did not
change.

The TDD order below applies when application behavior changes:

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

If any Implementer phase failure occurs, stop and report failure.

For documentation-only or governance-only changes, the Implementer phase must explicitly record that no application behavior changed and that no new behavior test was created.

## Tester Enforcement

For `STANDARD` and `DOCUMENTATION` modes, the Tester phase must run after
implementation.

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

If any Tester phase failure occurs, stop and report failure.

## Documentator Enforcement

For `STANDARD` and `DOCUMENTATION` modes, the Documentator phase must always
review:

- `README.md`
- `PLAN.md`
- `docs/DATA_CONTRACT.md`
- `docs/PROJECT_STATE.md`
- `docs/DESIGN.md`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md` when present or when the task should introduce it
- `docs/db/*` when schema, DER, index, constraint, or DB contract facts changed

The Documentator phase must update at least one file when behavior, workflow, project state, contracts, setup, logging, schema, DER, or architecture changes. If nothing changed, the Documentator phase must explicitly justify why no documentation update was required.

Failure conditions:

- Any required documentation file was not reviewed.
- No documentation file was updated after a meaningful change.
- No explicit justification is provided for leaving docs unchanged.
- Documentation invents architecture or behavior not present in the project.
- A contract/schema/logging change lacks changelog coverage or an explicit reason for deferring it.
- Documentation version headers are stale after touched files changed.

If any Documentator phase failure occurs, stop and report failure.

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

Every `STANDARD` and `DOCUMENTATION` task must report:

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

Every `INVESTIGATION` task must report the investigation output defined under
Task Mode Selection. It must also confirm that no project files were changed.

Every `PLANNING` task must report the current facts reviewed, options,
tradeoffs, risks, and recommended plan. It must also confirm that no project
files were changed.
