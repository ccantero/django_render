---
doc_id: changelog
doc_version: 1.1.24
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-06-26
source_repo: django_render
---

# Changelog

## 2026-06-26 - Portfolio Status Performance Sections

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Reorganized the Telegram `/portfolio_status` text after `Total` into a
  `Performance` section with `Portfolio equity`, `Today's trading (UTC)`, and
  `Open positions` subsections.
- Renamed the realized line from `Realized today (UTC)` to
  `Realized closed trades` and the current unrealized line from `Unrealized`
  to `Unrealized now`.
- Preserved the existing accounting, open-position valuation, snapshot-backed
  24h/7d/30d equity changes, HTML formatting, and equity PNG chart behavior.

Operator impact:
- Operators can more easily see that 24h/7d/30d equity movement, current UTC
  closed-trade realization, and current open-position unrealized PnL are
  separate windows/snapshots and should not be summed.

Validation:
- Added failing formatter expectations first for the new `Performance`
  structure, replacement labels, old-label absence, 24h/7d/30d retention, and
  unavailable-state rendering.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-25 - Codex Task Mode Governance

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- AGENTS.md
- .codex/hooks/README.md
- docs/CHANGELOG.md

Summary:
- Compared the dashboard workflow instructions with the bot project workflow
  reference.
- Added explicit `STANDARD`, `INVESTIGATION`, `PLANNING`, and `DOCUMENTATION`
  task modes to `AGENTS.md`.
- Preserved `STANDARD` as the required fallback for implementation, mixed
  tasks, uncertain scope, and protected workflow infrastructure changes.
- Clarified that hook validation applies to project-state changes and that
  read-only modes must stop without mutating files.

Operator impact:
- Future Codex work can use narrower read-only modes for investigations or
  plans without weakening the protected workflow path for real changes.
- Protected workflow infrastructure changes still require explicit approval,
  separate planning, validation, diff summary, and manual review before commit.

Validation:
- Planned as a protected workflow infrastructure update.
- Confirmed no application behavior, runtime logging, schema, contract, KPI,
  or operator-output semantics changed.

## 2026-06-25 - Portfolio Status Equity Chart Readability

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Improved the Telegram `/portfolio_status` equity PNG by downsampling the
  visual 7-day series to a bounded bucketed set of points.
- Kept the last valid point in each time bucket and excluded chart-only equity
  jumps above 25% from the previously accepted visual point.
- Removed visible point markers and added a simple `Equity history` title with
  softer grid styling.

Operator impact:
- The Telegram chart should read as a cleaner equity curve on mobile while the
  Equity, Free USDT, Open value, PnL, Change, PnL context, and Top contributor
  text values remain unchanged.
- Snapshot source rules remain unchanged: only `source = "bot_cycle"` rows with
  valid positive `notes.portfolio_equity_usdt` can feed history, and
  `open_value_usdt` is still not a fallback.

Validation:
- Added failing chart tests first for source isolation, missing canonical
  equity rejection, bucketed max-point downsampling, last-point-per-bucket
  retention, chart-only outlier filtering, textual change preservation, and
  skipping PNG rendering when the visual series has fewer than two points.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-24 - Portfolio Status PnL Context Label

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md
- PLAN.md

Summary:
- Renamed the Telegram `/portfolio_status` section from `24h drivers` to
  `PnL context`.
- Preserved the existing `Realized:` and `Unrealized:` lines and their
  `none` versus `unavailable` behavior.
- Left historical per-symbol attribution for the snapshot-backed 24h equity
  delta out of scope as a separate follow-up.

Operator impact:
- Operators no longer see wording that implies the current UTC-day realized
  PnL and current unrealized contributor fully explain the 24h snapshot delta.

Validation:
- Added failing formatter expectations first for the new title, old-title
  absence, preserved realized/unrealized rows, preserved empty/unavailable
  states, and Change block separation.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-24 - Portfolio Status Driver Empty State

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md

Summary:
- Updated `/portfolio_status` realized 24h driver rendering to distinguish
  missing evidence from a successful empty contributor result.
- `realized_drivers is None` still renders `unavailable`; an empty list now
  renders `none`.

Operator impact:
- Operators can tell the difference between a read/evidence gap and a clean
  current UTC-day result with no realized driver to report.

Validation:
- Added focused failing tests first for `None`, empty list, contributor list,
  and existing section preservation.
- Focused Telegram Portfolio Status tests passed.

## 2026-06-24 - Portfolio Status 24h Drivers

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added a compact `24h drivers` section to Telegram `/portfolio_status`.
- Realized drivers use read-only `bot.trade_operations` day-window evidence
  and linked `bot.lot_closures` PnL grouped by symbol.
- Unrealized drivers use current open-lot PnL from `position_lots` plus
  `portfolio.current_price` as an approximate current contributor, not exact
  historical attribution.

Operator impact:
- Operators can see the main realized and current unrealized symbol driver
  near the existing 24h portfolio change without Binance calls, trading logic
  changes, bot-owned writes, or schema changes.
- Missing or incomplete evidence renders `unavailable` instead of invented
  attribution.

Validation:
- Added failing tests first for realized loss driver output, current
  unrealized worst-driver output, unavailable degradation, existing section
  preservation, UTC-day realized grouping, and read-only behavior.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-20 - Data Contract Copy Merge

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- DATA_CONTRACT.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md

Summary:
- Merged the root and `docs/` data-contract copies so both carry the same
  `portfolio_snapshots` contract text.
- Preserved bot-side physical-column and canonical metadata notes while keeping
  the current dashboard rule that Portfolio Status history reads only
  `source = "bot_cycle"` rows with valid `notes.portfolio_equity_usdt`.
- Removed stale paired-dashboard follow-up wording because the inspected Django
  reader already filters `bot_cycle` snapshots and avoids open-value fallback.

Operator impact:
- No runtime behavior, schema, logging, Telegram, dashboard output, or trading
  behavior changed.

Validation:
- Compared both contract copies before the merge.
- Inspected current `Snapshot` mapping and Portfolio Status snapshot reader for
  consistency with the merged wording.

## 2026-06-20 - Portfolio Status Bot-Cycle History

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Updated `/portfolio_status` historical change and chart reads to use only
  `bot.portfolio_snapshots` rows with `source = "bot_cycle"` and valid
  `notes.portfolio_equity_usdt`.
- Preserved rejection of missing/invalid canonical equity and
  `open_value_usdt` fallback behavior.
- Added the read-only Django model mapping for the existing
  `portfolio_snapshots.source` column; no migration or bot-owned write path was
  introduced.

Operator impact:
- Legacy or API-sync snapshots with `source = "portfolio_sync_from_api"` no
  longer influence 24h/7d/30d changes or the Telegram equity chart, preventing
  mixed-valuation history.
- Historical windows remain `unavailable` until enough valid bot-cycle
  snapshots exist in the configured tolerance windows.

Validation:
- Added focused failing tests first for bot-cycle acceptance, API-sync
  rejection, missing canonical equity rejection, no `open_value_usdt` fallback,
  24h availability with sufficient bot-cycle history, and chart source
  isolation.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

Known follow-up:
- Verify and synchronize the paired bot repository `docs/DATA_CONTRACT.md` and
  `docs/KPI_REGISTRY.md` copies when that repository is available.

## 2026-06-19 - Portfolio Status Canonical Equity Snapshots

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Updated `/portfolio_status` history and chart reads to use
  `bot.portfolio_snapshots.notes.portfolio_equity_usdt` as the only canonical
  historical equity source.
- Ignored snapshots without valid positive `portfolio_equity_usdt`, including
  legacy `data.portfolio_equity_usdt` and `open_value_usdt`-only payloads.
- Preserved the existing 24h/7d/30d tolerance windows and in-memory Telegram
  chart rendering; no backfill, Binance calls, or bot-owned writes were added.

Operator impact:
- 24h change becomes available once production has a valid canonical snapshot
  inside the 18-30h window and a fresh latest canonical snapshot.
- 7d/30d remain unavailable until enough canonical history exists.
- Chart rendering becomes available with at least two valid canonical 7-day
  points.

Validation:
- Added focused failing tests first for canonical `notes.portfolio_equity_usdt`,
  missing/invalid canonical equity, legacy `data` rejection,
  `open_value_usdt` rejection, 24h availability, chart availability, and 7d/30d
  insufficient-history behavior.
- Focused Telegram Portfolio Status tests passed.
- `core/tests.py` passed.

Known follow-up:
- Verify and synchronize the paired bot repository `docs/DATA_CONTRACT.md` and
  `docs/KPI_REGISTRY.md` copies when that repository is available.

## 2026-06-16 - Portfolio Status Open Value Naming

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/KPI_REGISTRY.md

Summary:
- Renamed the internal `/portfolio_status` open-position valuation field to
  `open_value_usdt`, replacing the previous invested-capital wording.
- Updated the KPI registry canonical metric to
  `portfolio_status_open_value_usdt`.
- Preserved the existing `Open value` Telegram label and valuation formula.

Operator impact:
- Runtime output, calculations, snapshot history, chart generation, Telegram
  delivery, SQL queries, and source-of-truth rules are unchanged.

Validation:
- Focused tests were updated first and failed against the old implementation
  with the expected missing `open_value_usdt` key before the service rename.

## 2026-06-16 - Portfolio Status Snapshot Tolerance

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md

Summary:
- Tightened `/portfolio_status` historical change matching so horizon
  snapshots must fall inside deterministic age windows: 18-30h for 24h, 6-8d
  for 7d, and 28-32d for 30d.
- Replaced arbitrary "latest point at or before target" matching with closest
  in-window snapshot selection.
- Preserved chart generation and Telegram delivery behavior; chart availability
  still depends on two usable 7-day points, not on every change horizon being
  available.

Operator impact:
- Historical change values now render `unavailable` when evidence is too old,
  too recent, missing, or incomplete instead of reusing stale snapshots.
- No Binance calls, trading behavior, accounting writes, schema changes, or
  generated image persistence were introduced.

Validation:
- Added failing regression tests for valid, offset-valid, stale, too-recent,
  and insufficient snapshot evidence across 24h, 7d, and 30d horizons.
- Added coverage proving chart availability is independent from complete
  horizon-change availability.
- Focused portfolio-status and broader Telegram diagnostics tests passed.

## 2026-06-16 - Telegram Portfolio Status V2

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added snapshot-backed 24h/7d/30d portfolio change calculations for
  `/portfolio_status`, using only explicit reliable equity/account-value USDT
  fields from `bot.snapshots.data`.
- Added a dependency-free, transport-agnostic in-memory PNG renderer for the
  initial 7-day equity chart.
- Updated Telegram delivery so `/portfolio_status` sends the PNG as a photo
  with the text summary as caption when enough history exists, falls back to
  text if image delivery fails, and sends text only with a compact unavailable
  note when history is insufficient.
- Preserved the read-only dashboard boundary: no Binance calls, no trades, no
  bot-owned accounting mutations, no generated image persistence, and no
  historical values inferred from missing data.

Operator impact:
- Operators can see historical portfolio deltas and a compact 7-day equity
  chart when the bot has produced usable snapshots.
- Missing, stale, incomplete, or ambiguous snapshot history still renders as
  unavailable instead of zero.

Validation:
- Added failing tests first for 24h available, 7d available, 30d unavailable,
  no snapshots, stale/incomplete snapshots, valid PNG bytes, Telegram photo
  delivery, image-send fallback, and text-only fallback.
- Focused portfolio-status tests passed.
- Broader Telegram diagnostics tests passed, including existing `/buy_status`
  coverage.
- `core/tests.py` passed.

Known follow-up:
- Formalize and synchronize the canonical bot-side `bot.snapshots` equity
  payload/freshness rule and paired KPI registry copy when that repository is
  available.

## 2026-06-15 - Telegram Portfolio Status

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added the allowlisted read-only `/portfolio_status` Telegram command and
  command-guide entry.
- Added a dedicated portfolio summary service that uses open FIFO lots for
  quantity and cost basis, portfolio projection prices for valuation, latest
  healthcheck details for free USDT, and UTC-day linked lot closures for
  realized PnL.
- Added current valued open-lot exposure and projection equity, plus
  material-only aggregate unrealized PnL and best/worst contributors with
  conservative unavailable handling.
- Applied the existing healthcheck stale threshold to free USDT and portfolio
  projection timestamps so old or timestamp-less live values are unavailable.
- Left 24h/7d/30d changes unavailable because the shared snapshot contract does
  not yet define a verified equity payload or freshness rule.
- Recorded dynamic on-demand 7d PNG chart delivery as a follow-up; no generated
  images are persisted.

Operator impact:
- Operators can review portfolio performance separately from BUY capacity.
- The current valuation of open positions is labeled `Open value` to avoid
  implying historical invested capital or cost basis.
- Missing prices, missing entry data, and unavailable history are visible and
  are not silently treated as zero.
- The command performs no Binance calls and no bot-owned table mutations.

Validation:
- Added failing tests before implementation for routing, help, empty state,
  positive/negative unrealized PnL, missing valuation inputs, UTC realized PnL
  wiring, contributor selection, unavailable history, and read-only behavior.
- Focused portfolio-status tests passed.
- Full pytest suite: 241 passed plus 12 subtests.
- Python compilation and `git diff --check` passed.

Known follow-up:
- Synchronize the new dashboard portfolio-status KPI entries into the canonical
  bot repository `docs/KPI_REGISTRY.md`; that paired file is outside this
  workspace's writable scope.

## 2026-06-13 - Telegram BUY Status PnL Summary

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
- Added a compact `/buy_status` PnL section separating open-position
  projection PnL from accounting-realized PnL for the current UTC calendar
  day.
- Reused the existing `bot.portfolio` projection formula for open PnL.
- Aggregated open PnL across all material positions independently of the
  eight-row mobile display cap, and rendered it as unavailable if any material
  valuation or entry price is unavailable.
- Sourced realized PnL from `bot.lot_closures.realized_pnl`, using linked
  `trade_operations.executed_at` with `created_at` fallback only when execution
  time is null, inside the UTC interval `[00:00, next 00:00)`.
- Labeled the Telegram value `Realized today (UTC)` and corrected the KPI
  registry's stale closure-date wording.
- Added direct regressions proving the summary includes a ninth material row
  while the visible list remains capped at eight, and that the realized label
  explicitly names UTC.

Operator impact:
- Operators can distinguish open projection performance from realized trading
  results without treating either value as Binance's proprietary "Today's
  PNL."
- The Telegram value matches Analytics UTC calendar-day grouping and is
  explicitly distinct from Daily Audit's rolling previous-24h window.
- BUY capacity, dust/material classification, cooldowns, synchronization,
  accounting mutation, and trade execution are unchanged.

Validation:
- Added failing regression proof for an eight-row-only summary and for a
  realized label without the explicit UTC qualifier.
- Covered positive, negative, zero, mixed, empty, over-eight-position,
  unavailable-input, compact-layout, and exact UTC operation-timestamp boundary
  behavior.
- Ran focused PnL tests: 13 passed plus 5 boundary subtests.
- Ran `core/tests.py`: 195 passed plus 12 subtests.
- Ran the full pytest suite: 228 passed plus 12 subtests.

## 2026-06-11 - BUY Status Dust Exposure Classification

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Fixed Telegram `/buy_status` material-exposure rendering so display rows are
  defensively classified by `quantity * current_price >= DUST_MIN_NOTIONAL_USDT`.
- Added nested `healthcheck.details.position_classification` support while
  preserving existing flat healthcheck classification compatibility.
- Added regressions for WLDUSDT-like tiny residuals, material positions above
  threshold, unknown valuation rows, and stale material-symbol display data.

Operator impact:
- Tiny residuals such as `0.0884 WLDUSDT * 0.4367 = 0.03860428 USDT` can no
  longer appear under Material Exposure in `/buy_status`.
- Unknown-price positive rows remain visible as unknown value and continue to
  consume effective capacity.

Validation:
- Added failing BUY-status formatter regression before the fix.
- Ran focused Telegram BUY-status tests.

## 2026-06-10 - Pre-commit Evidence Function Fix

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md

Summary:
- Fixed protected pre-commit workflow validation so it no longer calls removed
  or undefined evidence helpers.
- Aligned pre-commit evidence checks with the documented high/medium/low risk
  model: high-risk changes require common and conditional evidence, medium-risk
  changes require common evidence with secondary warnings, and low-risk changes
  warn instead of failing solely for missing workflow evidence.
- Updated the hook self-check fixtures so behavior and KPI scenarios include
  the documentator evidence required by current governance.

Protected workflow files changed:
- `.codex/hooks/pre-commit.sh`
- `.codex/hooks/self-check.sh`

Operator impact:
- Commits no longer abort with `require_workflow_order: command not found`.
- Protected workflow infrastructure changes remain blocked unless
  `ALLOW_WORKFLOW_INFRA_CHANGE=1` is intentionally set for reviewed commits.

Validation:
- Reproduced the failure with `.codex/hooks/self-check.sh` before the fix.
- Ran shell syntax validation for touched hook scripts and related helper
  libraries.
- Ran `.codex/hooks/self-check.sh`: passed.

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
