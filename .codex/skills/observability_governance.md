# Observability and Documentation Governance Skill

## When To Use

Use this skill whenever a task touches or may touch:

- logs
- CLI output
- Telegram messages
- alerts
- healthcheck payloads
- operator reports
- KPIs, diagnostics, helper metrics, aliases, or planned observability names
- analytics/audit/dashboard read models
- documentation versioning
- changelog entries
- shared data contracts
- database schema, indexes, constraints, DER, or schema snapshots

This skill is additive to the single-agent Planner, Implementer, Tester, and Documentator phases.
It provides guidance and review context; it does not orchestrate separate agents.

## Goals

- Make stale documentation detectable.
- Make runtime evidence self-describing.
- Keep bot/dashboard shared contracts synchronized.
- Keep operator-facing logs and docs useful for ChatGPT-assisted troubleshooting.
- Prevent schema and column ambiguity by maintaining generated or verified DB documentation.
- Prevent ad-hoc KPI names, duplicate metric semantics, and dashboard/report
  drift by using `docs/KPI_REGISTRY.md` as the canonical observability registry.

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
6. KPI Registry review:
   - review canonical name
   - review category: KPI, Diagnostic, Helper, Alias, Deprecated, or Planned
   - review status: implemented, partial, planned, alias, deprecated, or experimental
   - review formula
   - review source of truth
   - review current producer
   - review current consumers
   - review units
   - review null/unavailable behavior
   - review do-not-confuse-with guidance
   - do not create KPI or diagnostic output ad-hoc without registry review
   - if a metric resembles another metric, document the alias/canonical
     relationship or justify the semantic difference
7. KPI Registry synchronization:
   - verify the paired dashboard registry copy identified by
     `DASHBOARD_KPI_REGISTRY` when available and when KPI semantics changed
   - record an explicit follow-up when the dashboard copy is not available
   - do not move KPI definitions into a database table unless runtime
     rendering/configuration, editable UI, feature flags, or dynamic
     definition audit requirements exist

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
- KPI/diagnostic semantics change without `docs/KPI_REGISTRY.md` review or
  explicit evidence that no registry update was needed
- stale docs are detected and not reported
