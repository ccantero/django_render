---
doc_id: changelog
doc_version: 1.1.3
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-05-25
source_repo: django_render
---

# Changelog

## 2026-05-25 - BUY Re-entry Cooldown Diagnostics Rendering

Type: contract
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Updated Telegram `/buy_status` and the dashboard BUY/Cooldown card to render
  extended bot-persisted cooldown diagnostics from latest healthcheck details.
- Added null-safe and Decimal-safe display for latest SELL operation, symbol,
  executed timestamp, nullable reason, reason source, realized PnL, cooldown
  type, classification source, elapsed minutes, and remaining minutes.
- Preserved legacy payload compatibility for `latest_sell_timestamp`,
  `cooldown_type = sell`, and `cooldown_type = generic_sell`.
- Normalized legacy `cooldown_type = sell` and bot-side
  `cooldown_type = generic_sell` to the same operator label, `recent sell`,
  so old and new payloads render compatibly.

Operator impact:
- BUY cooldown pages no longer show ambiguous `N/A` when the bot persisted
  usable cooldown context.
- Django remains a read-only observer and does not infer cooldowns or write to
  bot-owned trading tables.

Validation:
- Added failing tests first for full metadata, partial/null metadata, legacy
  payload compatibility, classification rendering, and dashboard fallback
  behavior.
- Added final review tests for `generic_sell` compatibility and stable
  realized-PnL formatting across null, zero, positive, negative, Decimal-string,
  scientific-notation, and invalid values.
- Ran `.venv/bin/python -m pytest core/tests.py`.
- Verified `docs/DATA_CONTRACT.md` is synchronized with
  `/home/cristhian/Dev/binanceBot/docs/DATA_CONTRACT.md`.

## 2026-05-25 - Codex Hook Symlink Execution Fix

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md

Summary:
- Fixed the Git pre-commit hook path resolution when `.git/hooks/pre-commit`
  is installed as a symlink to `.codex/hooks/pre-commit.sh`.
- Added self-check coverage for invoking the hook through the installed Git
  hook symlink.

Operator impact:
- Commits no longer fail before validation with a missing `.git/lib/common.sh`
  error.
- Protected workflow infrastructure changes still require manual review and
  `ALLOW_WORKFLOW_INFRA_CHANGE=1` when committing.

Validation:
- Reproduced the original missing helper-library failure before implementation.
- Ran hook syntax checks, `.codex/hooks/self-check.sh`, and the installed Git
  pre-commit hook after the fix.

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
