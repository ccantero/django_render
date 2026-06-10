---
doc_id: changelog
doc_version: 1.1.5
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-06-10
source_repo: django_render
---

# Changelog

## 2026-06-10 - Render Python Runtime Pin

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/CHANGELOG.md
- docs/PROJECT_STATE.md

Summary:
- Documented that Django 5.2 requires Python 3.10 or newer and that Render
  native Python deployments should use the repository `.python-version` file.
- Recorded the Render precedence caveat: a service-level `PYTHON_VERSION`
  environment variable overrides `.python-version` and can keep deployments on
  an incompatible old Python runtime.
- Updated stale README stack text from the previous Django 3.2 reference to the
  current Django 5.2 LTS dependency line.

Operator impact:
- Render deploys should stop failing with `No matching distribution found for
  Django<5.3,>=5.2` after the compatible Python runtime pin is committed and no
  older `PYTHON_VERSION` override remains configured.

Validation:
- Verified local `python3 --version` reports Python 3.13.7.
- Verified `.python-version` is present locally with `3.12.9`, which is
  compatible with Django 5.2.
- Verified no application behavior, logging, data contract, or schema changed.

## 2026-06-09 - Telegram BUY Status Material PnL

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Extended Telegram `/buy_status` material exposure rows with display-only
  unrealized PnL in USDT and percent, computed only from `bot.portfolio`
  projection fields already used by the BUY-status exposure view.
- Kept BUY capacity semantics unchanged: effective positions, material/dust/
  unknown counts, and remaining capacity were not recalculated.
- Kept dust PnL out of the message and preserved the existing material row cap
  for mobile message size.
- Updated local dependencies to the Django 5.2 LTS line and declared
  `pytest`/`pytest-django` in `requirements.txt` so tests run under Python
  3.13.

Operator impact:
- Operators can now see approximate current PnL beside each displayed material
  position in `/buy_status`.
- Rows with missing, invalid, or non-positive `entry_price` show
  `PnL unavailable` rather than a misleading zero.

Validation:
- Added failing formatter/test expectations before the final implementation.
- Ran focused Telegram BUY-status test.
- Ran `core/tests.py`.
- Ran full pytest suite: 208 passed, 1 Django 6.0 deprecation warning from DRF
  format suffix registration.

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
