# Documentation Skill

## When To Use

Use this skill after the tester role for every task. Documentation review is mandatory even when no documentation change appears necessary.

## Steps

1. Review all required documentation files:
   - `README.md`
   - `PLAN.md`
   - `docs/DATA_CONTRACT.md`
   - `docs/PROJECT_STATE.md`
   - `docs/DESIGN.md`
   - `docs/ARCHITECTURE.md`
   - `docs/CHANGELOG.md` when present or when the task should introduce it
   - `docs/db/*` when schema, DER, index, constraint, or DB contract facts changed
2. Compare the completed change against documented setup, architecture, data contracts, behavior, logging, schema, project state, and plan.
3. Update at least one file when the task changes behavior, workflow, setup, architecture, data contracts, logging, schema/DER, or project state.
4. Add or update a `docs/CHANGELOG.md` entry for operator-relevant behavior, contract, schema, logging, documentation-governance, or workflow changes.
5. Add or update lightweight version headers in touched core documentation files when practical.
6. If no docs changed, write an explicit justification in the final report.
7. Document only verified project facts.

## Version Header

When touching a core documentation file, prefer this header:

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

- Increment `doc_version` when the file content changes.
- Do not invent runtime or schema versions.
- Use `unknown` plus a follow-up when no reliable source exists.
- If a runtime log indicates a newer version than the docs, call out stale docs.

## Changelog Entry Template

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

## DER / Schema Documentation

For schema-impacting work, prefer generated artifacts:

- `docs/db/DER.md`
- `docs/db/schema_snapshot.sql`
- `docs/db/schema_columns.csv`
- `docs/db/schema_indexes.csv`
- `docs/db/schema_constraints.csv`
- `docs/db/schema_diff_<YYYYMMDD>.md`

If generation is not possible, document why and add a follow-up.

## Failure Conditions

- A required documentation file was not reviewed.
- A meaningful change happened and no documentation was updated.
- No-change justification is missing.
- Documentation describes unimplemented behavior as implemented.
- Documentation introduces invented architecture, dependencies, services, or data flows.
- Contract/schema/logging changes omit changelog coverage without explicit justification.
- Touched versioned docs have stale or missing version metadata without justification.

On failure, stop and report the missing documentation action.
