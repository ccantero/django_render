---
doc_id: changelog
doc_version: 1.1.0
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-05-21
source_repo: django_render
---

# Changelog

## 2026-05-21 - Capital Efficiency Documentation Merge

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Merged the downloaded 2026-05-21 Django documentation update fragments into
  the existing documentation without replacing richer current content.
- Moved historical/evolutionary notes toward changelog coverage and kept README
  focused on operator usage and boundary rules.
- Recorded planned trapped-capital analytics, capital-days / holding-efficiency
  metrics, and time-based exit dry-run observability as future read-only
  dashboard surfaces.
- Reaffirmed that Django should consume bot-owned or shared-contract analytics
  outputs instead of reconstructing accounting truth independently.

Operator impact:
- No application behavior changed.
- No database schema changed.
- No shared data-contract semantics changed.

Validation:
- Confirmed the incoming update set did not include a `DATA_CONTRACT.md`
  fragment.
- Confirmed the Django `docs/DATA_CONTRACT.md` copy remains byte-for-byte
  synchronized with `/home/cristhian/Dev/binanceBot/docs/DATA_CONTRACT.md`.
- Confirmed no generated DER/schema artifacts were needed because no schema or
  contract change occurred.

## 2026-05-20 - Documentation Governance Merge

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/DATA_CONTRACT.md

Summary:
- Merged the downloaded 2026-05-20 documentation-governance additions into the
  existing Django dashboard docs without replacing richer existing content.
- Added lightweight version headers to touched core documentation files.
- Recorded planned schema/DER visibility, docs freshness validation, and
  runtime/version logging governance as planned operational work.
- Verified that the Django `docs/DATA_CONTRACT.md` copy and the bot project
  `/home/cristhian/Dev/binanceBot/docs/DATA_CONTRACT.md` copy were identical at
  merge time.

Operator impact:
- No application behavior changed.
- No database schema changed.
- Operators now have changelog coverage for documentation-governance changes.

Validation:
- Confirmed the incoming `DJANGO_DATA_CONTRACT.md` governance content was
  already represented in the synchronized shared contract.
- Confirmed no generated DER/schema artifacts were created because no schema
  change occurred.
