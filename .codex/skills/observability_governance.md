# Observability and Documentation Governance Skill

## When To Use

Use this skill whenever a task touches or may touch:

- logs
- CLI output
- Telegram messages
- alerts
- healthcheck payloads
- operator reports
- documentation versioning
- changelog entries
- shared data contracts
- database schema, indexes, constraints, DER, or schema snapshots

This skill is additive to planning, TDD, testing, and documentation. It does not replace the mandatory planner → implementer → tester → documentator workflow.

## Goals

- Make stale documentation detectable.
- Make runtime evidence self-describing.
- Keep bot/dashboard shared contracts synchronized.
- Keep operator-facing logs and docs useful for ChatGPT-assisted troubleshooting.
- Prevent schema and column ambiguity by maintaining generated or verified DB documentation.

## Required Checks

1. Version context:
   - app/runtime version
   - schema version
   - data contract version
   - docs version
   - strategy version when trading behavior is involved
   - run id for runtime events
2. Documentation freshness:
   - compare runtime/log versions against local doc headers when available
   - flag stale docs instead of assuming they are current
3. Changelog:
   - create/update `docs/CHANGELOG.md` for operator-relevant changes
4. Schema/DER:
   - create/update `docs/db/*` artifacts when schema or DB contract changes
5. Contract synchronization:
   - verify bot and dashboard `DATA_CONTRACT.md` copies when shared semantics change

## Recommended Log Context

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

## Recommended Changelog Entry

```md
## YYYY-MM-DD - Short title

Type: behavior | contract | schema | docs | logging | operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- ...

Summary:
- ...

Operator impact:
- ...

Validation:
- ...
```

## Hard Stops

Stop if:

- a schema/contract change is made without documentation impact analysis
- a logging/operator-output change removes useful context without justification
- generated DER/schema files are claimed without being generated
- paired bot/dashboard contract sync is required but ignored
- stale docs are detected and not reported
