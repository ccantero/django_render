---
doc_id: kpi-registry
doc_version: 1.0.31
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-06-24
source_repo: binanceBot
---

# KPI Registry

This registry is the canonical naming and taxonomy reference for Binance Bot
operational metrics. It documents existing bot-local observability surfaces and
planned KPI families before new metrics are added.

It is a documentation and observability-governance artifact only. It does not
change runtime behavior, trading rules, database schema, healthcheck payloads,
or dashboard/shared contracts.

## Reading guide

Use this file to:

- avoid duplicate KPI names
- identify canonical metric names
- understand source-of-truth boundaries
- distinguish KPI vs Diagnostic vs Helper metrics
- review planned vs implemented observability

Do not use this file as:

- runtime schema
- API contract
- dashboard payload guarantee
- replacement for `docs/DATA_CONTRACT.md`

## Taxonomy

- **KPI**: primary metric used for operator decisions or daily capital review.
- **Diagnostic**: contextual explanation, breakdown, reason, or supporting
  evidence for a KPI.
- **Helper metric**: intermediate calculation used by a KPI or diagnostic.
- **Alias / deprecated**: compatible legacy or duplicate name. Prefer the
  documented canonical name for new output.
- **Planned**: desired metric or family not implemented in current bot output.

## Metric Status Values

- `implemented`: exists in current runtime/operator tooling.
- `partial`: exists in some output but not everywhere expected, or has
  incomplete consumer coverage.
- `planned`: documented target, not implemented yet.
- `alias`: compatibility name for another canonical metric.
- `deprecated`: should not be used for new output.
- `experimental`: available for research/operator analysis but not yet stable
  for dashboard/shared contract usage.

Unless a row says otherwise, current operator-report metrics are bot-local
observability and not dashboard/shared contract guarantees.

## Metric Naming Rules

- Use `_usdt` for monetary values denominated in USDT.
- Use `_pct` for percentage values whose unit is percent.
- Use `_ratio` for rates expressed as percentages in current reports unless
  the metric explicitly documents a `0-1` scale.
- Use `_count` for counts.
- Use `_minutes` or `_hours` for durations.
- Avoid ambiguous names such as `idle_capital` without specifying the base.
- If a metric has an alias, document the canonical name and the legacy name.
- Prefer names that expose the denominator when ambiguity is likely, for
  example `idle_free_capital_ratio` and `stagnant_slot_ratio`.
- New bot-local JSON metrics must not be treated as dashboard/shared contracts
  until a contract task explicitly promotes them.

## Django Sync Note

`docs/KPI_REGISTRY.md` in the bot repository is canonical for KPI naming and
semantics. If the Django dashboard keeps a local copy, it must be synchronized
manually from this file, similar to the shared data contract workflow. Use
`DASHBOARD_KPI_REGISTRY` during workflow validation when that paired copy is
available.

Do not move this registry to a database table or create KPI definition
migrations/runtime tables for the current governance use case. A database table
for KPI definitions should be considered only if runtime rendering or
configuration, editable UI, feature flags, or dynamic audit of KPI definition
changes becomes a real requirement.

## Source-of-Truth Rules

- `position_lots` is accounting truth for open inventory and FIFO lot state.
- `portfolio` is projection/valuation only. It may provide `current_price`,
  display quantity, or USDT cash projection, but it is not SELL coverage truth.
- `bot_healthcheck.details` is the current source for `/buy_status`,
  BUY capacity, latest BUY state, and latest BUY reason.
- `trade_operations` is the economic operation layer for filled BUY/SELL
  operations and operation metadata.
- `lot_closures` is the FIFO realized PnL layer.
- `sell_decision_events` is diagnostics only. It explains decisions or
  dry-run candidates and must not be treated as executed trades.
- Binance Spot snapshot is external operational truth for current exchange
  balances. It does not replace bot accounting truth in `position_lots`.

## Duplicate and Alias Decisions

- `idle_free_capital_ratio` is the canonical name for free USDT divided by
  known open plus free capital. `idle_capital_ratio` is a bot-local JSON alias
  kept for compatibility and should not be used for new output.
- `median_hold_time_hours` in Capital Velocity is a compatibility alias for
  `median_open_position_age_hours`; prefer the open-position age name.
- BUY capacity metrics answer whether the bot may open more positions now.
  Slot Efficiency metrics answer how effectively configured slots are being
  used by material, unknown, productive, or stagnant exposure. They share
  `max_positions` and effective-position semantics but are not duplicates.
- `capital_days_by_symbol` and capital-days consumers are reused by Capital
  Velocity, Trapped Capital, and Dust Containment. The canonical calculation is
  `estimated_value_usdt * age_hours / 24`; each report may filter or rank a
  different subset.

## BUY Capacity / Exposure

Source family: latest `bot_healthcheck.details`, `/buy_status` consumers, and
position classification from portfolio projection.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `raw_positions_count` | Diagnostic | Count all positive-quantity portfolio rows visible to BUY diagnostics. | `count(portfolio rows where quantity > 0)` | `portfolio` projection | `BotRunner` healthcheck details | `/buy_status`, audit review | count | Missing details means unavailable. | `effective_positions_count` | Raw rows include dust and unknown value positions. |
| `material_positions_count` | KPI | Count positions large enough to consume BUY capacity. | `count(quantity * current_price >= DUST_MIN_NOTIONAL_USDT)` | `portfolio` valuation projection | `PositionClassificationService`, `BotRunner` | `/buy_status`, capacity review | count | Unknown price rows are excluded here and counted separately. | `raw_positions_count` | Material count is part of effective capacity. |
| `dust_positions_count` | Diagnostic | Count low-value positive positions. | `count(0 < quantity * current_price < DUST_MIN_NOTIONAL_USDT)` | `portfolio` valuation projection | `PositionClassificationService`, `BotRunner` | `/buy_status`, dust review | count | Unknown price rows are not dust. | `material_positions_count` | Dust remains visible but does not consume BUY capacity. |
| `unknown_value_positions_count` | Diagnostic | Count positive positions with unavailable valuation. | `count(quantity > 0 and current_price missing/null/non-positive)` | `portfolio` projection | `PositionClassificationService`, `BotRunner` | `/buy_status`, reconciliation review | count | Zero when all positive rows can be valued. | `dust_positions_count` | Unknown value positions conservatively consume BUY capacity. |
| `effective_positions_count` | KPI | Current position count used by BUY max-position gate. | `material_positions_count + unknown_value_positions_count` | `bot_healthcheck.details` | `BotRunner` | `/buy_status`, Capital Velocity slot comparison | count | Missing details means unavailable. | `raw_positions_count` | Dust does not count against this value. |
| `max_positions` | KPI | Configured BUY position capacity. | Runtime `MAX_POSITIONS` persisted in healthcheck details. | `bot_healthcheck.details` | `BotRunner` | `/buy_status`, Capital Velocity slot ratios | count | Slot ratios are unavailable when missing or zero. | exchange limits | This is bot policy capacity, not Binance account capacity. |
| `remaining_buy_capacity` | KPI | Number of additional BUY slots currently available. | `max(0, max_positions - effective_positions_count)` | `bot_healthcheck.details` | `BotRunner` | `/buy_status`, operator review | count | Unavailable when capacity details are missing. | `available_slots` | Same semantics as slot availability, but current `/buy_status` scope. |
| `free_usdt` | KPI | Free USDT available for BUY decisions or deployment analysis. | Latest free USDT value; fallback may use USDT portfolio projection in reports. | `bot_healthcheck.details.free_usdt`; fallback `portfolio` for some scripts | `BotRunner`; Capital Velocity loader | `/buy_status`, Capital Velocity | USDT | `None` when not available; ratios using it become unavailable. | `known_open_plus_free_value_usdt` | Report source should be exposed when fallback is used. |
| `latest_buy_state` | Diagnostic | Stable lifecycle state for the latest BUY evaluation. | Last BUY diagnostic state persisted by runner. | `bot_healthcheck.details` | `BotRunner` | `/buy_status`, audit/churn review | enum/string | Missing means no current diagnostic details. | `latest_buy_reason` | Examples include `available`, `blocked_by_positions`, `no_candidate`, `execution_error`. |
| `latest_buy_reason` | Diagnostic | Stable reason for latest BUY state. | Last BUY diagnostic reason persisted by runner. | `bot_healthcheck.details` | `BotRunner`, `BuyService` | `/buy_status`, audit/churn review | enum/string | Missing means unavailable. | `latest_buy_state` | Examples include `capacity_available`, `effective_positions_at_max_capacity`, cooldown reasons, and execution errors. |
| `scanner_candidates_available` | Diagnostic | Count scanner candidates visible to the BUY cycle. | Scanner diagnostics `candidates` when present, otherwise `len(opportunities.candidates)`. | `bot_healthcheck.details`, `bot.event_log` BUY/scanner rows | `BotRunner` | `/buy_status`, BUY decision/blocker analysis, operator review | count | `None` before scanner runs or when unavailable; zero means scanner returned no candidates. | `buy_candidates_seen` | Scanner availability as observed by the BUY cycle, not prefilter universe size. |
| `buy_candidates_limit` | Diagnostic | Configured limit for ranked scanner candidates supplied to BUY validation. | `BUY_CANDIDATE_LIMIT`, defaulting to `max(MAX_POSITIONS * 3, 15)`. | Runtime config via `OpportunityService.default_limit` | `BotConfig`, `OpportunityService`, `BotRunner` | `/buy_status`, operator review | count | `None` when the opportunity service does not expose a concrete limit. | `max_positions` | Candidate supply width, not BUY capacity. |
| `buy_candidates_seen` | Diagnostic | Number of candidates actually handed to BUY validation. | `len(opportunities.candidates)` for the cycle. | `bot_healthcheck.details`, `bot.event_log` BUY rows | `BotRunner` | `/buy_status`, BUY blocker investigation | count | `None` before scanner runs; zero means no BUY validation candidates. | `scanner_candidates_available` | Seen by BUY after scanner limit/fallback output, not all market symbols. |
| `candidate_selected_rank` | Diagnostic | One-based scanner rank of the candidate selected by BUY validation. | Rank in the supplied candidate list when `BuyService` returns the first accepted candidate. | `bot_healthcheck.details`, `buy_plan` log context | `BuyService`, `BotRunner` | `/buy_status`, operator review | rank/count | `None` when no candidate was selected. | exchange fill rank | Pre-execution scanner rank only. |
| `candidate_rejection_count_before_selected` | Diagnostic | Count higher-ranked candidates rejected before the selected candidate. | Number of BUY validation rejections recorded before the selected candidate. | `bot_healthcheck.details`, `buy_plan` log context | `BuyService`, `BotRunner` | `/buy_status`, BUY blocker investigation | count | `None` when no candidate was selected. | total cycle rejections | Counts only rejections before the selected candidate; if all candidates fail, use rejection summaries. |
| `material_exposure_usdt` | KPI | Current USDT value of material portfolio exposure in BUY status. | `sum(quantity * current_price for material positions)` | `portfolio` valuation projection in healthcheck details | `BotRunner`; `buy_status_formatter` for defensive display | `/buy_status` | USDT | Unknown valuation is rendered unavailable, not zero; material-symbol display values below `DUST_MIN_NOTIONAL_USDT` are demoted to dust display rows. | `material_open_capital_usdt` | BUY-status exposure is portfolio-row based; Capital Velocity uses open lots. |
| `material_position_unrealized_pnl_usdt` | Diagnostic | Approximate current unrealized PnL shown beside each displayed material `/buy_status` position. | `(current_price - entry_price) * quantity` for each displayed material portfolio row | `portfolio` valuation projection | Django `/buy_status` formatter | `/buy_status` | USDT | Render `PnL unavailable` when entry price is missing, invalid, or non-positive, or when quantity/current price cannot be used. | realized PnL, lot-backed unrealized PnL | Display-only projection; does not read `position_lots`, does not affect BUY capacity, and only applies to material rows already shown. |
| `material_position_unrealized_pnl_pct` | Diagnostic | Approximate current unrealized PnL percent shown beside each displayed material `/buy_status` position. | `((current_price - entry_price) / entry_price) * 100` for each displayed material portfolio row | `portfolio` valuation projection | Django `/buy_status` formatter | `/buy_status` | percent | Render `PnL unavailable` when entry price is missing, invalid, or non-positive, or when quantity/current price cannot be used. | realized PnL percent, lot-backed unrealized PnL percent | Display-only projection; two-decimal signed percentage for mobile readability. |
| `dust_exposure_usdt` | Diagnostic | Current USDT value of dust portfolio exposure in BUY status. | `sum(quantity * current_price for dust positions)` | `portfolio` valuation projection in healthcheck details | `BotRunner` | `/buy_status`, dust review | USDT | Unknown valuation excluded. | `dust_open_capital_usdt` | Dust exposure is visible but not BUY-capacity blocking. |

## BUY Decision Analysis

Source family: `analyze_buy_decisions.py` over bounded recent
`bot.event_log` BUY/scanner diagnostics, latest `bot_healthcheck.details`, and
recent FILLED BUY `trade_operations`. These fields are bot-local explanatory
diagnostics only; they are not new dashboard/shared contracts and do not
change BUY behavior.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `capital_deployment_blocker_summary` | Diagnostic | Operator-readable primary explanation for undeployed free USDT. | Backward-compatible priority classifier over capacity, cooldown, sizing/minNotional, scanner, rejection, and evidence availability, plus explicit attribution metadata. | Derived from event_log, latest healthcheck, and recent BUY operations | BUY Decision Analysis | Daily audit bundle, operator review | object/string reason | `primary_blocker=insufficient_evidence` when evidence is missing or inconclusive. | `idle_free_capital_ratio` | Explains why deployment did or did not happen; it is not a capital ratio. `primary_blocker` remains priority-order for compatibility and should be read beside `dominant_blocker_by_count`. |
| `primary_blocker_method` | Diagnostic | Explain how `primary_blocker` was attributed. | Fixed value `priority_order` for the current analyzer classifier. | Derived from analyzer classifier | BUY Decision Analysis | Daily audit bundle, operator review | enum/string | `unknown` should be used only when a future path cannot identify attribution. | `dominant_blocker_by_count` | Supported values are `latest_state`, `dominant_count`, `weighted_count`, `priority_order`, and `unknown`; current producer emits `priority_order`. |
| `dominant_blocker_by_count` | Diagnostic | Show the most frequent blocker observed during the analysis window independently from current state. | Highest non-zero value from `blocker_counts`, tie-broken deterministically by reason name. | Derived from analyzer blocker counters | BUY Decision Analysis | Daily audit bundle, operator review | object/reason/count | `{reason: unknown, count: 0}` when no count evidence exists. | `primary_blocker` | Historical frequency only; it does not override the compatibility primary blocker. |
| `blocker_counts` | Diagnostic | Raw count inputs used for dominant-blocker attribution. | Counts of real insufficient USDT, cooldown, capacity, sizing, and no-candidate evidence in the selected window. | `bot.event_log` BUY/scanner diagnostics and latest healthcheck-derived summaries | BUY Decision Analysis | Daily audit bundle, operator review | object/count | Counts default to zero when evidence is absent. | `top_rejection_reasons` | Normalized blocker-family counts, not raw reason distribution. |
| `top_rejection_reasons` | Diagnostic | Most frequent BUY rejection/skip reasons in the window. | Count stable reasons from BUY rejection/skip/sizing evidence. | `bot.event_log` BUY diagnostics | BUY Decision Analysis | Daily audit bundle, operator review | list/count | Empty when no rejection evidence exists. | SELL rejection reasons | BUY-only explanation context. |
| `matched_position_classification` | Diagnostic | Explain which portfolio classification caused an `already_in_portfolio` BUY rejection. | Classification bucket for the rejected symbol in the current BUY position classification: `material`, `unknown_value`, `dust`, or `not_found`. | `bot.event_log` BUY rejection context from `BuyService` | BuyService | Event-log review, BUY blocker investigation | enum/string | Only present for `already_in_portfolio` rejection diagnostics; absent for unrelated rejection reasons. | `effective_positions_count` | Observability only; BUY still blocks only through effective gating positions, so dust should not produce this blocker in normal runtime. |
| `matched_position_estimated_value_usdt` | Diagnostic | Show the estimated USDT value of the matched position when available. | `quantity * current_price` for the matched portfolio position when quantity and current price are positive. | `portfolio` valuation projection captured in BUY rejection context | BuyService | Event-log review, BUY blocker investigation | USDT | `None` when current price or quantity is unavailable/non-positive. | realized PnL | Approximate projection value, not accounting truth or executed notional. |
| `matched_position_current_price_present` | Diagnostic | Show whether the matched position had a usable current price at rejection time. | `true` when matched position current price is positive; otherwise `false`. | `portfolio.current_price` captured in BUY rejection context | BuyService | Event-log review, BUY blocker investigation | boolean | Only present for `already_in_portfolio` rejection diagnostics. | valuation freshness | Presence only; it does not prove the price is fresh. |
| `cooldown_summary` | Diagnostic | Summarize BUY blockers from symbol-level cooldowns. | Count cooldown rejection reasons and remaining cooldown context when available. | `bot.event_log`, latest healthcheck cooldown fields | BUY Decision Analysis | Daily audit bundle, operator review | count/minutes | Zero counts when no cooldown evidence exists. | churn/re-entry history | Runtime blocker evidence, not historical churn quality. |
| `sizing_summary` | Diagnostic | Summarize BUY sizing and minNotional blockers. | Count sizing rejection event names/reasons and minNotional subset. | `bot.event_log` BUY sizing diagnostics | BUY Decision Analysis | Daily audit bundle, operator review | count | Zero counts when no sizing evidence exists. | exchange executed notional | Pre-execution sizing evidence only. |
| `insufficient_usdt_summary` | Diagnostic | Split `insufficient_usdt` evidence into real free-USDT shortages vs slot-allocation-derived shortages. | Count BUY rejection/sizing evidence where free USDT is below required USDT separately from slot-cap evidence where slot cap is below required USDT; include top affected symbols and bounded recent examples. | `bot.event_log` BUY sizing/rejection diagnostics | BUY Decision Analysis | Daily audit bundle, operator review | object/count/USDT | Counts are zero and examples empty when no matching evidence exists; missing amounts render unavailable rather than inferred. | `free_usdt`, Slot Efficiency ratios | Explains blocked BUY sizing evidence only; it does not change allocation policy or prove account equity. |
| `scanner_summary` | Diagnostic | Distinguish no-candidate scanner outcomes from candidate availability. | Count no-candidate, candidate-available, and unknown scanner evidence. `market_scanner_candidate_evaluated` uses `candidate_count > 0` as candidate evidence, `candidate_count = 0` as no-candidate evidence, and missing `candidate_count` as unknown. | `bot.event_log` scanner/BUY events and latest healthcheck reason | BUY Decision Analysis | Daily audit bundle, operator review | count/object | Unknown when scanner summary events omit candidate counts. | candidate rejection | No candidates means scanner produced none; rejections mean candidates existed but failed later checks. Do not infer candidate availability from scanner event existence alone. |
| `scanner_candidate_events_count` | Diagnostic | Count scanner summary events that explicitly observed candidates. | `count(scanner events where candidate_count > 0)` plus explicit BUY candidate availability events. | `bot.event_log` scanner/BUY events | BUY Decision Analysis | Daily audit bundle, operator review | count | Zero when no explicit positive candidate evidence exists. | `candidate_available_events_count` | More explicit scanner-focused count; older compatibility field remains present. |
| `scanner_no_candidate_events_count` | Diagnostic | Count scanner summary events that explicitly observed no candidates. | `count(scanner events where candidate_count = 0)` plus explicit no-candidate BUY/healthcheck evidence. | `bot.event_log` scanner/BUY events and latest healthcheck reason | BUY Decision Analysis | Daily audit bundle, operator review | count | Zero when no explicit no-candidate evidence exists. | candidate rejection count | Drives `primary_blocker=no_candidates` only when no later rejection evidence is present. |
| `scanner_unknown_events_count` | Diagnostic | Count scanner summary events whose candidate availability cannot be determined. | `count(scanner summary events missing candidate_count or equivalent count field)` | `bot.event_log` scanner events | BUY Decision Analysis | Daily audit bundle, operator review | count | Zero when all scanner summary events contain candidate counts. | no-candidate count | Preserves backward compatibility for older events without creating false candidate availability. |
| `capacity_summary` | Diagnostic | Show max-position/effective-capacity context for BUY blocking. | Latest `max_positions`, `effective_positions_count`, and `remaining_buy_capacity`; plus capacity blocker count. | `bot_healthcheck.details`, event_log rejection reasons | BUY Decision Analysis | Daily audit bundle, operator review | count | Fields unavailable when missing from healthcheck. | Slot Efficiency ratios | Capacity context for BUY deployment, not slot productivity. |

## BUY Blocker Analysis

Source family: `analyze_buy_blockers.py` over bounded recent
`bot.event_log` BUY/scanner diagnostics, latest `bot_healthcheck.details`,
and recent FILLED BUY `trade_operations`. These fields are bot-local
operator diagnostics only; they are not dashboard/shared contracts and do not
change BUY behavior. Scanner aggregate counters can overlap, so funnel stages
derived from scanner diagnostics are approximate rather than exact
per-candidate lineage.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `buy_acceptance_rate` | KPI | Share of observed candidates that became FILLED BUY operations in the selected window. | `candidates_accepted / candidates_seen * 100` | Derived from `bot.event_log` candidate evidence and FILLED BUY `trade_operations` | BUY Blocker Analysis | Operator review | percent | `0` when no candidates are observed. | order fill rate | Acceptance is window-level diagnostic evidence, not exchange fill quality. |
| `buy_funnel_conversion_rate` | KPI | Final BUY conversion from first reported funnel stage to FILLED BUY context. | `final_buy_count / scanner_candidates_count * 100` | Derived from analyzer funnel | BUY Blocker Analysis | Operator review | percent | `0` when funnel denominator is unavailable/zero. | `buy_acceptance_rate` | Usually similar, but funnel may use scanner diagnostic stage counts. |
| `top_buy_blocker` | Diagnostic | Most frequent stable BUY blocker in the selected evidence window. | Highest blocker count, tie-broken deterministically by reason name. | `bot.event_log` BUY/scanner diagnostics | BUY Blocker Analysis | Operator review | reason/string | `unknown` when no blocker evidence exists. | `primary_blocker` in BUY Decision Analysis | Frequency-based, not priority-order current state. |
| `capital_idle_attribution_pct` | Diagnostic | Relative contributor shares when free capital, free slots, and BUY rejection evidence coexist. | `blocker_rejection_count / total_rejections_with_idle_context * 100` | `bot.event_log` rejection reasons plus latest healthcheck `free_usdt` and `remaining_buy_capacity` | BUY Blocker Analysis | Operator review | percent map | Empty/unavailable when free USDT, remaining capacity, or rejection evidence is missing. | exact deployable USDT | Relative frequency only; exact USDT loss is not inferred. |
| `buy_blocker_concentration` | KPI | Detect whether one blocker dominates the rejection window. | `max(blocker_count) / sum(blocker_counts) * 100` | Derived from stable blocker counts | BUY Blocker Analysis | Operator review | percent | `0` when no blocker evidence exists. | acceptance rate | High concentration suggests a focused blocker; low concentration suggests systemic dispersion. |
| `blocker_entropy` | KPI | Measure blocker dispersion across reasons. | Shannon entropy over positive blocker-count shares. | Derived from stable blocker counts | BUY Blocker Analysis | Operator review | entropy units | `0` when no blocker evidence exists. | price volatility | Higher entropy means blockers are spread across more reasons. |
| `buy_funnel` | Diagnostic | Approximate stage counts from scanner candidates through final BUY. | Ordered stage counts from scanner diagnostics, BUY rejections, and FILLED BUY context. | `bot.event_log` and `trade_operations` | BUY Blocker Analysis | Operator review | list/count | Missing stages are omitted or represented by available aggregate counts. | exact per-candidate trace | Scanner diagnostics are aggregate and may overlap. |

## BUY Cooldown Analysis

Source family: `analyze_buy_cooldowns.py` over bounded recent
`bot.event_log` BUY rejection diagnostics, latest `bot_healthcheck.details`,
and optional existing `buy_decision_analysis.json` context. These fields are
bot-local explanatory diagnostics only; they are not dashboard/shared
contracts and do not change BUY behavior. The analyzer accepts both
per-candidate rejection rows and compact summary rows with `reasons` /
`examples`; missing symbol detail is reported as `unknown_symbol`.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `cooldown_rejections` | Diagnostic | Count BUY rejections caused by re-entry cooldown reasons in the analysis window. | `count(BUY rejection diagnostics where reason in loss/take-profit/generic re-entry cooldown)`, expanding compact `reasons` counts when present | `bot.event_log` BUY rejection diagnostics | BUY Cooldown Analysis | Operator review | count | Zero when no cooldown evidence exists. | executed BUY count | Raw observations; repeated checks during one cooldown may overcount opportunities. |
| `cooldown_rejection_pct` | Diagnostic | Share of BUY rejections represented by cooldown blockers. | `cooldown_rejections / total_buy_rejections * 100` | Derived from BUY rejection diagnostics | BUY Cooldown Analysis | Operator review | percent | `0` when denominator is zero. | win/loss rate | Rejection-window diagnostic only. |
| `cooldown_reasons` | Diagnostic | Count cooldown blockers by stable reason. | group cooldown rejections by reason | `bot.event_log` diagnostics | BUY Cooldown Analysis | Operator review | object/count | Missing reasons are omitted or zero for canonical loss/take-profit keys. | SELL reasons | BUY blocker reasons, not executed SELL classifications. |
| `remaining_cooldown_histogram` | Diagnostic | Show how much cooldown time was left when candidates were rejected. | bucket `cooldown_remaining_minutes` into `<15m`, `15-60m`, `1-6h`, `6h+` | BUY rejection diagnostics | BUY Cooldown Analysis | Operator review | bucket/count | Rows without remaining minutes do not contribute to buckets. | cooldown policy duration | Remaining time at rejection, not configured duration. |
| `logical_cooldown_groups` | Diagnostic | Collapse repeated observations during the same inferred cooldown window. | group by `(symbol, cooldown_reason, cooldown_window)` using SELL operation id, cooldown end, or observed-time fallback | Derived from BUY rejection diagnostics | BUY Cooldown Analysis | Operator review | list/count | Falls back conservatively when SELL/cooldown-end evidence is missing. | raw rejection count | Opportunity estimate, not proof of independent orders. |
| `logical_cooldown_rejections` | Diagnostic | Count logical cooldown opportunities after duplicate grouping. | `count(logical_cooldown_groups)` | Derived | BUY Cooldown Analysis | Operator review | count | Zero when no cooldown groups exist. | `cooldown_rejections` | Lower or equal to raw cooldown rejections. |
| `potential_overcount_reduction` | Diagnostic | Estimate how many raw cooldown observations are repeated within logical groups. | `cooldown_rejections - logical_cooldown_rejections` | Derived | BUY Cooldown Analysis | Operator review | count | Zero when no repeated groups are detected. | storage retention reduction | Analytical overcount only, not row deletion guidance. |
| `potential_buy_count` | Diagnostic | Per-symbol logical BUY opportunities blocked by cooldown. | count logical groups for a symbol/reason | Derived | BUY Cooldown Analysis | Operator review | count | Zero when a symbol has only raw non-cooldown rejections. | executed BUYs | Potential opportunity count, not a guaranteed order. |
| `upper_bound_deployable_free_usdt` | Diagnostic | Capacity-bound upper bound of free USDT that could have been deployed if cooldown blockers were absent. | `free_usdt` when logical cooldown opportunities and available capacity exist; `0` when none; `None` when free USDT unavailable | Latest healthcheck or input BUY decision analysis context | BUY Cooldown Analysis | Operator review | USDT | `None` when free USDT missing; method field explains fallback. | exact order notional | Upper bound only; per-candidate BUY notional is not invented. |
| `upper_bound_deployable_free_usdt_pct` | Diagnostic | Share of current free USDT represented by the capacity-bound cooldown opportunity upper bound. | `upper_bound_deployable_free_usdt / free_usdt * 100` where available | Derived | BUY Cooldown Analysis | Operator review | percent | `None` when free USDT unavailable. | idle/free capital ratio | Only evaluates cooldown-blocked opportunities in the selected window. |
| `estimated_deployable_free_usdt` | Alias / deprecated | Backward-compatible bot-local JSON alias for `upper_bound_deployable_free_usdt`. | Same as `upper_bound_deployable_free_usdt`. | Derived | BUY Cooldown Analysis JSON | Existing bot-local consumers | USDT | Same as canonical field. | exact order notional | Prefer `upper_bound_deployable_free_usdt` for new output and discussion. |
| `estimated_deployable_free_usdt_pct` | Alias / deprecated | Backward-compatible bot-local JSON alias for `upper_bound_deployable_free_usdt_pct`. | Same as `upper_bound_deployable_free_usdt_pct`. | Derived | BUY Cooldown Analysis JSON | Existing bot-local consumers | percent | Same as canonical field. | idle/free capital ratio | Prefer `upper_bound_deployable_free_usdt_pct` for new output and discussion. |

## Cooldown Outcome Analysis

Source family: `analyze_cooldown_outcomes.py` over logical BUY cooldown
groups from `bot.event_log` and persisted historical snapshot projection
prices. The analyzer prefers contract-visible `bot.snapshots` when usable and
falls back to bot-local `bot.portfolio_snapshots` when needed. These fields are
bot-local counterfactual diagnostics only; they are not dashboard/shared
contracts, order simulations, or evidence that a blocked BUY would have
executed.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `return_after_15m` | Diagnostic | Approximate price return 15 minutes after a logical cooldown opportunity. | `(posterior_snapshot_price - entry_snapshot_price) / entry_snapshot_price * 100` | `bot.snapshots` or fallback `bot.portfolio_snapshots` projection prices | Cooldown Outcome Analysis | Operator review | percent | `None` and window marked incomplete when entry or posterior price evidence is missing. | realized PnL | Counterfactual price movement only; no order size or fill assumed. |
| `return_after_30m` | Diagnostic | Approximate price return 30 minutes after a logical cooldown opportunity. | Same as `return_after_15m` using the 30m horizon. | Historical snapshot projection prices | Cooldown Outcome Analysis | Operator review | percent | `None` when incomplete. | realized PnL | Uses bounded persisted snapshots, not Binance calls. |
| `return_after_60m` | KPI | Default primary readable horizon for cooldown outcome review. | Same as `return_after_15m` using the 60m horizon. | Historical snapshot projection prices | Cooldown Outcome Analysis | Operator review | percent | `None` when incomplete. | realized PnL or win rate | Text report highlights `--primary-horizon`, default `60m`. |
| `return_after_90m` | Diagnostic | Approximate price return 90 minutes after a logical cooldown opportunity. | Same as `return_after_15m` using the 90m horizon. | Historical snapshot projection prices | Cooldown Outcome Analysis | Operator review | percent | `None` when incomplete. | realized PnL | Counterfactual only. |
| `return_after_180m` | KPI | Longer cooldown outcome review horizon. | Same as `return_after_15m` using the 180m horizon. | Historical snapshot projection prices | Cooldown Outcome Analysis | Operator review | percent | `None` when incomplete. | realized PnL | Counterfactual only. |
| `best_return_pct` | Diagnostic | Best observed configured-horizon return after a cooldown opportunity. | `max(non_null horizon returns)` | Derived from horizon returns | Cooldown Outcome Analysis | Operator review | percent | `None` when all horizons are incomplete. | intrahorizon high | It does not search highs between snapshots or horizons. |
| `worst_return_pct` | Diagnostic | Worst observed configured-horizon return after a cooldown opportunity. | `min(non_null horizon returns)` | Derived from horizon returns | Cooldown Outcome Analysis | Operator review | percent | `None` when all horizons are incomplete. | intrahorizon drawdown | It does not search lows between snapshots or horizons. |
| `incomplete_windows` | Diagnostic | Horizons that lack sufficient persisted price evidence. | list horizon labels where entry or posterior price is unavailable | Derived | Cooldown Outcome Analysis | Operator review | list | Empty when every horizon has evidence. | zero return | Missing data is not treated as zero. |
| `cooldown_saved_losses_pct` | KPI | Share of classified cooldown opportunities whose observed average horizon return was negative. | `saved_loss_count / classified_opportunities * 100`; per-horizon variant uses negative returns over complete windows | Derived from horizon returns | Cooldown Outcome Analysis | Operator review | percent | `0` when there is no classified denominator. | loss cooldown count | Outcome diagnostic, not the reason the cooldown fired. |
| `cooldown_blocked_gains_pct` | KPI | Share of classified cooldown opportunities whose observed average horizon return was positive. | `blocked_gain_count / classified_opportunities * 100`; per-horizon variant uses positive returns over complete windows | Derived from horizon returns | Cooldown Outcome Analysis | Operator review | percent | `0` when there is no classified denominator. | take-profit cooldown count | Outcome diagnostic, not proof a BUY would have filled. |
| `net_cooldown_effect_pct` | KPI | Primary-horizon counterfactual price return after cooldown opportunities. Positive means cooldowns likely blocked gains; negative means they likely saved losses at the configured horizon. | average non-null returns for `primary_horizon`, default `60m`; per-horizon values are exposed separately in `net_cooldown_effect_by_horizon_pct` | Derived from horizon returns | Cooldown Outcome Analysis | Operator review | percent | `None` when the primary horizon has no return evidence. | realized strategy PnL | Approximate price-only effect; no position sizing, fees, slippage, or fills. |
| `net_cooldown_effect_by_horizon_pct` | Diagnostic | Show net effect independently for each configured horizon. | map each horizon to average non-null horizon return | Derived from horizon returns | Cooldown Outcome Analysis | Operator review | percent map | Horizon value is `None` when no complete windows exist for that horizon. | `net_cooldown_effect_pct` | Prevents mixing 15m/30m/60m/90m/180m returns into one headline average. |
| `primary_horizon` | Diagnostic | Horizon used for headline interpretation. | CLI/config value, default `60m` | Analyzer argument | Cooldown Outcome Analysis | Operator review | enum/string | Defaults to `60m`. | lookahead window | Does not hide per-horizon output. |

## Capital Deployment

Source family: `analyze_capital_velocity.py` over `position_lots`,
`portfolio`, and latest healthcheck details.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `known_open_capital_usdt` | KPI | Total valued open capital across open lots. | `sum(estimated_value_usdt where value known)` | `position_lots` plus `portfolio.current_price` | Capital Velocity | Daily audit bundle, operator review | USDT | Unknown-valued positions excluded and counted separately. | `material_open_capital_usdt` | Includes material and dust known values. |
| `material_open_capital_usdt` | KPI | Open lot-backed capital currently material by dust threshold. | `sum(estimated_value_usdt for classification=material)` | `position_lots` plus `portfolio.current_price` | Capital Velocity | Daily audit bundle, operator review | USDT | Unknown-valued positions excluded. | `material_exposure_usdt` | Lot-backed deployment, not portfolio-row BUY status exposure. |
| `dust_open_capital_usdt` | Diagnostic | Open lot-backed capital below dust threshold. | `sum(estimated_value_usdt for classification=dust)` | `position_lots` plus `portfolio.current_price` | Capital Velocity | Dust/capital review | USDT | Unknown-valued positions excluded. | `dust_exposure_usdt` | Lot-backed open dust, not arbitrary Spot dust. |
| `free_usdt` | KPI | Cash-like free capital available to redeploy. | `bot_healthcheck.details.free_usdt` or USDT portfolio projection fallback. | Latest healthcheck preferred | Capital Velocity | Daily audit bundle | USDT | `None` when unavailable; idle ratios unavailable. | `idle_free_capital_ratio` | Report includes `free_usdt_source`. |
| `known_open_plus_free_value_usdt` | Helper metric | Denominator for deployment ratios. | `known_open_capital_usdt + free_usdt_or_zero` | Derived from open lots and free USDT source | Capital Velocity | Capital Velocity ratios | USDT | Status is `partial` if unknown valuations exist. | total account equity | It is not a full account equity statement. |
| `material_exposure_ratio` | KPI | Share of known open plus free capital deployed in material lots. | `material_open_capital_usdt / known_open_plus_free_value_usdt * 100` | Derived | Capital Velocity | Operator review | percent | `None` when denominator is zero/unavailable. | slot utilization | Measures capital share, not slot count. |
| `idle_free_capital_ratio` | KPI | Share of known open plus free capital sitting as free USDT. | `free_usdt / known_open_plus_free_value_usdt * 100` | Derived | Capital Velocity | Operator review | percent | `None` when `free_usdt` is unavailable. | `idle_capital_ratio` | Status: `implemented`, `experimental` for dashboard/shared contract use. Canonical name for new output. |
| `idle_capital_ratio` | Alias / deprecated | Backward-compatible bot-local JSON name. | Same as `idle_free_capital_ratio`. | Derived | Capital Velocity JSON | Existing bot-local JSON consumers | percent | Same as canonical metric. | distinct idle-capital formulas | Status: `alias`, `deprecated`. Do not add new outputs under this name. |

## Capital Velocity

Source family: `analyze_capital_velocity.py`.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `avg_open_position_age_hours` | Diagnostic | Average age of open positions. | `avg(now - oldest_opened_at per symbol)` | `position_lots.opened_at` | Capital Velocity | Operator review | hours | `None` when no known ages. | weighted age | Unweighted by capital. |
| `median_open_position_age_hours` | KPI | Median age of open positions. | median of open position ages | `position_lots.opened_at` | Capital Velocity | Operator review | hours | `None` when no known ages. | `median_hold_time_hours` | Canonical name; less sensitive to outliers than average. |
| `median_hold_time_hours` | Alias / deprecated | Compatibility alias for median open age. | Same as `median_open_position_age_hours`. | Derived | Capital Velocity JSON | Bot-local JSON compatibility | hours | Same as canonical metric. | realized hold time | Prefer `median_open_position_age_hours`. |
| `weighted_avg_open_position_age_hours` | KPI | Capital-weighted age of open positions. | `sum(age_hours * estimated_value_usdt) / sum(estimated_value_usdt)` | `position_lots` plus `portfolio.current_price` | Capital Velocity | Operator review | hours | `None` when no valued open capital. | average age | More influenced by large positions. |
| `capital_days_total` | KPI | Total value-time consumed by open capital. | `sum(estimated_value_usdt * age_hours / 24)` | Derived from open lots and valuation | Capital Velocity | Operator review | USDT-days | Unknown value or age excluded. | trapped capital | Capital-days is exposure over time, not PnL. |
| `capital_days_by_symbol` | Diagnostic | Capital-days contribution per symbol. | same calculation grouped by symbol | Derived | Capital Velocity | Operator review | USDT-days | Symbol omitted if value or age unavailable. | PnL by symbol | Ranking signal, not performance. |
| `top_capital_days_consumers` | Diagnostic | Highest capital-days symbols. | Top rows from `symbols_consuming_most_capital_days`. | Derived | Capital Velocity | Text report | list | Empty when no valued ages. | stagnant-only list | Includes all classifications with capital-days. |
| `stagnant_material_positions` | KPI | Material positions old enough and inside neutral PnL band. | `classification=material and age >= stagnant_hours and min_pnl_pct <= unrealized_pnl_pct <= max_pnl_pct` | Open lots plus valuation | Capital Velocity, Trapped Capital | Operator review | list/count | Excludes unknown valuation or unknown age. | old material positions | Requires both age and PnL band. |
| `capital_locked_in_neutral_positions_usdt` | KPI | Capital tied in stagnant neutral-band positions. | `sum(estimated_value_usdt for stagnant_material_positions)` | Derived | Capital Velocity | Operator review | USDT | Zero when no stagnant candidates. | trapped_capital_usdt | Neutral-band subset, not all material open value. |
| `global_reuse_delay_minutes_avg` | KPI | Average delay from FILLED SELL to next FILLED BUY. | average `next BUY executed_at - SELL executed_at` | `trade_operations` | Capital Velocity | Operator review | minutes | `None` when no reusable SELL/BUY sequence. | same-symbol delay | Global reuse does not prove exact USDT lineage. |
| `reuse_delay_p50_minutes` | KPI | Median global SELL -> BUY reuse delay. | nearest/median percentile over global delays | `trade_operations` | Capital Velocity | Operator review | minutes | `None` when no delays. | average delay | JSON field is `sell_to_buy_reuse_delay_p50_minutes`. |
| `reuse_delay_p75_minutes` | Diagnostic | p75 global SELL -> BUY reuse delay. | nearest-rank percentile | `trade_operations` | Capital Velocity | Operator review | minutes | `None` when no delays. | same-symbol p75 | JSON field is `sell_to_buy_reuse_delay_p75_minutes`. |
| `reuse_delay_p90_minutes` | KPI | Tail global SELL -> BUY reuse delay. | nearest-rank percentile | `trade_operations` | Capital Velocity | Operator review | minutes | `None` when no delays. | same-symbol p90 | JSON field is `sell_to_buy_reuse_delay_p90_minutes`. |
| `sells_without_reuse_inside_window` | KPI | SELL count not followed by a global BUY inside configured window. | `count(global_reuse_within_window=false)` | `trade_operations` | Capital Velocity | Operator review | count | Zero when every SELL reused inside window. | sells without same-symbol reuse | JSON field is `sell_without_global_reuse_within_window_count`. |
| `approximate_reuse_ratio` | KPI | Approximate released capital redeployed by next BUY inside window. | `capital_redeployed_by_next_buy_usdt / capital_released_usdt * 100` | `trade_operations.gross_quote` | Capital Velocity | Operator review | percent | `None` when no released capital. | audited capital attribution | Approximation; multiple SELLs may map to same BUY. |

## Slot Efficiency

Source family: Capital Velocity slot utilization plus `/buy_status` capacity.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `slot_utilization_ratio` | KPI | Configured BUY capacity currently occupied by effective positions. | `effective_positions / max_positions * 100` | Capital Velocity derived from open lots and latest healthcheck | Capital Velocity | Operator review | percent | `None` when `max_positions` missing or zero. | material exposure ratio | Status: `implemented`, `experimental` for dashboard/shared contract use. Count-based, not capital-based. |
| `productive_slot_ratio` | KPI | Share of configured slots occupied by non-stagnant material positions. | `productive_material_positions / max_positions * 100` | Derived | Capital Velocity | Operator review | percent | `None` when `max_positions` missing or zero. | `productive_material_ratio` | Status: `implemented`, `experimental` for dashboard/shared contract use. Denominator is max-position capacity. |
| `stagnant_slot_ratio` | KPI | Share of configured slots occupied by stagnant material positions. | `stagnant_material_positions / max_positions * 100` | Derived | Capital Velocity | Operator review | percent | `None` when `max_positions` missing or zero. | `stagnant_material_ratio` | Status: `implemented`, `experimental` for dashboard/shared contract use. Denominator is max-position capacity. |
| `productive_material_ratio` | Diagnostic | Share of material positions not classified stagnant. | `productive_material_positions / material_positions * 100` | Derived | Capital Velocity | Operator review | percent | `None` when no material positions. | `productive_slot_ratio` | Status: `implemented`, `experimental` for dashboard/shared contract use. Denominator is current material positions. |
| `stagnant_material_ratio` | Diagnostic | Share of material positions classified stagnant. | `stagnant_material_positions / material_positions * 100` | Derived | Capital Velocity | Operator review | percent | `None` when no material positions. | `stagnant_slot_ratio` | Status: `implemented`, `experimental` for dashboard/shared contract use. Denominator is current material positions. |
| `available_slots` | Diagnostic | Remaining slots by Capital Velocity view. | `max(0, max_positions - effective_positions)` | Latest healthcheck plus open-position classification | Capital Velocity | Operator review | count | `None` when `max_positions` unavailable. | `remaining_buy_capacity` | Status: `implemented`, `partial` across reports because `/buy_status` uses `remaining_buy_capacity`. Same capacity concept, different report family. |

## Trapped Capital / Holding Efficiency

Source family: `analyze_trapped_capital.py` and overlapping Capital Velocity
stagnant metrics.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `trapped_capital_usdt` | KPI | Capital currently trapped in stale/stagnant review candidates. | Planned canonical rollup of stagnant/would-exit candidate value. | `position_lots` plus valuation | Planned | Future operator review | USDT | Not emitted as a single current field. | `known_open_capital_usdt` | Status: `planned`. Current reports expose component summaries rather than one field. |
| `stagnant_candidates` | KPI | Material old small-PnL candidates for review. | `classification=material and age > stagnant_hours and min_pnl_pct <= unrealized_pnl_pct <= max_pnl_pct` | `position_lots` plus `portfolio.current_price` | Trapped Capital | Operator review | list/count | Excludes unknown age or valuation. | Capital Velocity stagnant list | Same concept, report-specific output. |
| `old_material_positions` | Diagnostic | Material positions older than review thresholds. | material positions sorted/bucketed by age | `position_lots.opened_at` plus valuation | Trapped Capital | Operator review | list/count | Unknown age bucket remains unknown. | stagnant candidates | Old alone does not require neutral PnL. |
| `unrealized_pnl_pct` | KPI | Approximate unrealized PnL percent for open position. | `(estimated_value_usdt - cost_basis_usdt) / cost_basis_usdt * 100` | `position_lots.entry_price`, quantity, `portfolio.current_price` | Trapped Capital, Capital Velocity | Operator review | percent | `None` when value or cost basis unavailable/zero. | realized PnL | Projection, not accounting-realized. |
| `unrealized_pnl_usdt` | KPI | Approximate unrealized PnL value. | `estimated_value_usdt - cost_basis_usdt` | Open lots plus valuation | Trapped Capital, Capital Velocity | Operator review | USDT | `None` when price unavailable. | `realized_pnl` | Approximate and open-position only. |
| `holding_age_buckets` | Diagnostic | Group open or closed lots by holding age. | bucket by age thresholds such as `<6h`, `6-24h`, `1-3d`, `3-7d`, `>7d` | `position_lots.opened_at`, `lot_closures.closed_at` | Trapped Capital | Operator review | bucket counts/values | Unknown timestamps stay unknown. | median open age | Buckets are explanatory. |
| `capital_days_consumers` | Diagnostic | Rank positions consuming value-time. | sort by `capital_days desc` | Derived | Trapped Capital, Capital Velocity | Operator review | list | Empty when age/value unavailable. | PnL rankings | High capital-days can be profitable or unprofitable. |
| `would_exit_candidates` | Planned | Dry-run candidates that a future time-based exit policy would select. | Configured age/PnL/material filters | Trapped Capital | Trapped Capital | Operator review | list/count/USDT | Empty when no matches. | runtime dry-run events | Status: `partial`, `experimental`. Report-only selection exists; a canonical shared output is not promoted. |

## Churn / Re-entry

Source family: Capital Velocity same-symbol reuse and existing churn/audit
review over `trade_operations`, `lot_closures`, and optional healthcheck
cooldown diagnostics.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `same_symbol_reentry_count` | KPI | Count SELLs followed by later BUY of the same symbol. | `count(same_symbol_reentries)` | `trade_operations` | Capital Velocity | Operator review | count | Zero when no same-symbol reuse. | global reuse count | Same-symbol only. |
| `same_symbol_reuse_delay_minutes` | KPI | Delay from SELL to next same-symbol BUY. | `next same-symbol BUY executed_at - SELL executed_at` | `trade_operations` | Capital Velocity | Operator review | minutes | Row omitted when no later same-symbol BUY. | global reuse delay | Same-symbol churn signal. |
| `under_15m` | Diagnostic | Flag very rapid re-entry. | `same_symbol_reuse_delay_minutes <= 15` | Derived | Capital Velocity | Operator review | boolean/count | False when delay above threshold. | configured threshold | Fixed helper flag. |
| `under_60m` | Diagnostic | Flag rapid re-entry under one hour. | `same_symbol_reuse_delay_minutes <= 60` | Derived | Capital Velocity | Operator review | boolean/count | False when delay above threshold. | configured threshold | Fixed helper flag. |
| `under_threshold` | KPI | Flag same-symbol re-entry under configured churn threshold. | `same_symbol_reuse_delay_minutes <= churn_threshold_minutes` | Derived | Capital Velocity | Operator review | boolean/count | False when delay above threshold. | `under_60m` | Threshold is configurable. |
| `possible_churn` | KPI | Rapid same-symbol re-entry without stronger PnL classification. | `under_threshold and realized_pnl_usdt is not negative` | `trade_operations`, `lot_closures` | Capital Velocity | Operator review | count/class | Unknown PnL can remain `possible_churn` or `unknown` depending classifier. | healthy reuse | Review aid only; does not block BUYs. |
| `healthy_reuse` | Diagnostic | Same-symbol reuse not considered rapid churn and with usable PnL evidence. | classifier output from delay and realized PnL | Derived | Capital Velocity | Operator review | count/class | Unavailable PnL may classify unknown. | profitable re-entry | It is not a guarantee of good strategy. |
| `loss_reentry` | KPI | Rapid re-entry after a loss-making SELL. | `realized_pnl_usdt < 0 and delay <= threshold` | `lot_closures.realized_pnl` linked to SELL | Capital Velocity | Operator review | count/class | Requires linked PnL evidence. | stop-loss cooldown | Observed history, not active blocker. |
| `take_profit_reentry` | Planned | Re-entry after take-profit SELL. | later BUY after SELL classified by `raw_payload.sell_reason=take_profit_reached` or positive linked PnL | `trade_operations`, `lot_closures`, diagnostics | Planned | Future churn review | count/class | Not currently emitted as a Capital Velocity class. | `healthy_reuse` | Status: `planned`. Existing cooldown diagnostics already use take-profit classification for BUY blocking. |
| `normal_reentry` | Planned | Re-entry after generic SELL without loss/take-profit classification. | later BUY after generic SELL | `trade_operations` | Planned | Future churn review | count/class | Not currently emitted as a Capital Velocity class. | `possible_churn` | Status: `planned`. Planned taxonomy name only. |
| `latest_cooldown_blockers` | Diagnostic | Latest BUY rejection caused by re-entry cooldown. | healthcheck latest BUY reason and cooldown fields | `bot_healthcheck.details` | `BotRunner`, `BuyService` | `/buy_status`, churn script, audit | enum/minutes | Missing when no cooldown rejection occurred. | observed churn | Runtime blocker, not historical reuse. |

## Dust / Residuals

Source family: `/buy_status`, `analyze_dust_containment.py`, Capital Velocity,
and SELL residual cleanup diagnostics.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `dust_exposure_usdt` | Diagnostic | Total estimated dust value in BUY status. | `sum(quantity * current_price for dust portfolio rows)` | `portfolio` projection in healthcheck | `BotRunner` | `/buy_status` | USDT | Unknown valuation excluded. | dust open lot capital | Portfolio-row projection. |
| `dust_positions_count` | Diagnostic | Number of dust positions. | count dust-classified positions | `portfolio` projection or open lots depending report | `BotRunner`, Dust Containment, Capital Velocity | `/buy_status`, operator reports | count | Unknown valuation separated. | cosmetic dust count | Source family must be stated. |
| `recurring_residual_symbols` | KPI | Symbols repeatedly producing dust/residuals. | group residual/dust evidence by symbol over window | `position_lots`, `dust_detections`, SELL payloads | Dust Containment | Operator review | list/count | Empty when no recurrence. | one-time dust | Persistence and recurrence matter operationally. |
| `dust_capital_days` | KPI | Value-time consumed by dust positions. | `sum(dust_estimated_value_usdt * age_hours / 24)` | `position_lots` plus valuation | Dust Containment | Operator review | USDT-days | Unknown age/value excluded. | dust exposure | Adds time dimension. |
| `cleanup_attempted_count` | KPI | Number of SELL residual cleanup attempts observed. | count cleanup diagnostics with attempted state | `trade_operations.raw_payload`, optional `sell_decision_events` | Dust Containment | Operator review | count | Zero when no evidence or table missing. | applied count | Attempted can include rejected. |
| `cleanup_applied_count` | KPI | Count residual cleanup attempts actually applied to exchange quantity. | count applied cleanup diagnostics | `trade_operations.raw_payload` preferred | Dust Containment | Operator review | count | Zero when no applied evidence. | FIFO closures | Applied residual is metadata; FIFO closes lot-backed qty only. |
| `cleanup_rejected_count` | Diagnostic | Count cleanup attempts rejected by policy or exchange filters. | count rejected diagnostics | `trade_operations.raw_payload`, diagnostics | Dust Containment | Operator review | count | Zero when no rejected evidence. | unsellable open lots | Rejection reason should be preserved. |
| `rejection_reasons` | Diagnostic | Stable reasons cleanup was not applied. | group rejected cleanup diagnostics by reason | SELL payloads and diagnostics | Dust Containment | Operator review | map/count | Empty when no rejected attempts. | SELL strategy reasons | Residual cleanup context only. |
| `cosmetic_vs_operational_dust` | KPI | Distinguish harmless tiny dust from review-worthy residuals. | severity/origin classification using value, age, recurrence, and evidence | Dust Containment derived | Dust Containment | Operator review | class | Unknown evidence remains limitation. | material positions | Human review aid only. |

## SELL Diagnostic Volume

Source family: `analyze_sell_decision_events.py` over
`bot.sell_decision_events` diagnostics. These fields are bot-local storage and
volume diagnostics only; they are not trading KPIs or dashboard contracts.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `duplicate_group_count` | Diagnostic | Number of exact duplicate-like SELL diagnostic groups in the configured time window. | count groups where symbol/event/reason/validation-stage/created-at bucket has more than one row | `sell_decision_events` grouping fields | SELL diagnostic analyzer | Operator review | count | Zero when no exact duplicate groups. | duplicate database rows | Event-name-specific heuristic; does not prove payload identity or total reduction. |
| `duplicate_event_count` | Diagnostic | Total rows contained in exact duplicate-like groups. | sum group row counts for exact groups with count > 1 | `sell_decision_events` grouping fields | SELL diagnostic analyzer | Operator review | count | Zero when no exact duplicate groups. | total table rows | Bounded by analyzer `--days`; payload is not read. |
| `potential_reduction_if_one_per_group` | Diagnostic | Estimate future row reduction if each exact duplicate-like group emitted one row. | `sum(count - 1 for exact duplicate groups)` | Derived from exact duplicate groups | SELL diagnostic analyzer | Operator review | count | Zero when no exact duplicate groups. | storage bytes recovered | Event-name-specific future-emission estimate only; historical storage still requires retention/reclaim. |
| `top_duplicate_reasons` | Diagnostic | Reasons contributing most duplicate-like SELL diagnostics. | aggregate duplicate groups by reason | `sell_decision_events.reason` | SELL diagnostic analyzer | Operator review | list/count | Empty when no duplicate groups. | strategy reason distribution | Bot-local volume review. |
| `top_duplicate_symbols` | Diagnostic | Symbols contributing most duplicate-like SELL diagnostics. | aggregate duplicate groups by symbol | `sell_decision_events.symbol` | SELL diagnostic analyzer | Operator review | list/count | Empty when no duplicate groups. | open position count | Bot-local volume review. |
| `top_duplicate_event_names` | Diagnostic | Event names contributing most duplicate-like SELL diagnostics. | aggregate duplicate groups by event_name | `sell_decision_events.event_name` | SELL diagnostic analyzer | Operator review | list/count | Empty when no duplicate groups. | retained event policy | Bot-local volume review. |
| `logical_duplicate_group_count` | Diagnostic | Number of logical cross-event SELL diagnostic groups in the configured time window. | count groups where symbol/reason/validation-stage/created-at bucket has more than one row | `sell_decision_events` grouping fields | SELL diagnostic analyzer | Operator review | count | Zero when no logical groups. | exact duplicate groups | Omits `event_name` to expose detected/skipped pairs; payload is not read. |
| `logical_duplicate_event_count` | Diagnostic | Total rows contained in logical cross-event duplicate groups. | sum group row counts for logical groups with count > 1 | `sell_decision_events` grouping fields | SELL diagnostic analyzer | Operator review | count | Zero when no logical groups. | exact duplicate event count | Bounded by analyzer `--days`; payload is not read. |
| `potential_reduction_if_one_per_logical_group` | Diagnostic | Estimate future row reduction if each logical group emitted one row. | `sum(count - 1 for logical duplicate groups)` | Derived from logical duplicate groups | SELL diagnostic analyzer | Operator review | count | Zero when no logical groups. | storage bytes recovered | Cross-event future-emission estimate only; not a deletion instruction. |
| `top_logical_duplicate_reasons` | Diagnostic | Reasons contributing most logical duplicate-like SELL diagnostics. | aggregate logical groups by reason | `sell_decision_events.reason` | SELL diagnostic analyzer | Operator review | list/count | Empty when no logical groups. | strategy reason distribution | Bot-local volume review. |
| `top_logical_duplicate_symbols` | Diagnostic | Symbols contributing most logical duplicate-like SELL diagnostics. | aggregate logical groups by symbol | `sell_decision_events.symbol` | SELL diagnostic analyzer | Operator review | list/count | Empty when no logical groups. | open position count | Bot-local volume review. |

## Exit Quality / Time-based Exit

Source family: `analyze_time_based_exit_outcomes.py` over runtime dry-run
`sell_decision_events.reason=time_based_exit_candidate`.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `total_candidates` | KPI | Count runtime dry-run time-based exit candidates reviewed. | `count(candidate rows after filters)` | `sell_decision_events` diagnostics | Time-based Exit Outcome | Operator review | count | Zero when no candidates. | would-exit dry-run report | Status: `implemented`, `experimental`. Runtime persisted candidates only. |
| `sold_within_lookahead` | KPI | Candidates later sold by normal strategy inside lookahead. | count first non-manual FILLED SELL within window | `trade_operations`, diagnostics | Time-based Exit Outcome | Operator review | count | Zero when no later SELL found. | live time-based exits | Status: `implemented`, `experimental`. The runtime candidate itself did not necessarily sell. |
| `still_open` | KPI | Candidates still open at review time. | candidates not sold and with current open valuation | `position_lots`, `portfolio.current_price` | Time-based Exit Outcome | Operator review | count | Unknown current value may classify inconclusive. | no-sell decision | Status: `implemented`, `experimental`. Still open can be positive or negative. |
| `estimated_capital_that_would_have_been_released_usdt` | KPI | Estimated capital a live time-based exit would have released. | `sum(candidate estimated_value_usdt)` | `sell_decision_events.estimated_value_usdt` | Time-based Exit Outcome | Operator review | USDT | Missing values ignored; fallback total zero when none. | realized proceeds | Status: `implemented`, `experimental`. Candidate estimate, not actual execution. |
| `time_based_partial_exit_candidate` | Diagnostic | Dry-run-only candidate showing whether a configured-fraction partial time-based exit would be viable. | computed for runtime time-based candidates from open lot quantity, current `PARTIAL_TAKE_PROFIT_FRACTION`, current price, rounding, minQty, minNotional, and fraction-validity checks | `sell_decision_events` diagnostics | SellService | Operator review, future calibration reports | boolean/reason/payload | Rejection reason explains ineligible cases; `partial_fraction_not_positive` covers fractions `<= 0` and `partial_fraction_not_partial` covers fractions `>= 1`; missing payload means the runtime did not emit the partial diagnostic. | live partial SELL | Status: `implemented`, `experimental`. It does not call Binance, submit orders, mutate accounting, or enable live partial exits. |
| `capital_released_usdt` | Diagnostic | Estimated USDT value that a hypothetical partial time-based exit would release. | `time_based_partial_exit_would_sell_quantity * current_price` | `sell_decision_events` diagnostics | SellService | Operator review, future calibration reports | USDT | `0` when quantity or price is unavailable/non-positive. | realized proceeds | Status: `implemented`, `experimental`. Hypothetical dry-run value only. |
| `would_create_dust` | Diagnostic | Flags whether a hypothetical partial time-based exit would leave an unsellable projected remainder. | true when projected remainder would be below minQty, below minNotional, or round to zero | `sell_decision_events` diagnostics plus exchange filter context | SellService | Operator review, future calibration reports | boolean | False when no dust-forming rejection is detected. | existing SPOT dust inventory | Status: `implemented`, `experimental`. Evaluates projected remainder only. |
| `realized_pnl_after_not_exiting_usdt` | KPI | Realized PnL from later normal SELLs after candidates were not exited by time policy. | `sum(linked lot_closures.realized_pnl)` | `lot_closures` linked to later SELL | Time-based Exit Outcome | Operator review | USDT | `None` when no linked realized PnL evidence. | unrealized PnL | Status: `implemented`, `partial` when closure links are missing, `experimental` for shared use. Answers what happened after waiting. |
| `current_unrealized_pnl_for_still_open_candidates_usdt` | KPI | Current approximate PnL for candidates still open. | `sum(latest_unrealized_pnl_usdt for still-open candidates)` | Open lots plus valuation | Time-based Exit Outcome | Operator review | USDT | `None` when current price missing. | realized PnL | Status: `implemented`, `partial` when valuation is missing, `experimental` for shared use. Projection only. |
| `beneficial_exit_candidate` | KPI | Outcome class where exiting earlier appears beneficial. | classifier based on later realized/current PnL evidence | Derived | Time-based Exit Outcome | Operator review | count/class | Requires sufficient evidence. | recommendation | Status: `implemented`, `experimental`. Classification feeds recommendation. |
| `harmful_exit_candidate` | KPI | Outcome class where exiting earlier appears harmful. | classifier based on later realized/current PnL evidence | Derived | Time-based Exit Outcome | Operator review | count/class | Requires sufficient evidence. | recommendation | Status: `implemented`, `experimental`. Indicates waiting looked better. |
| `still_open_negative` | KPI | Still-open candidate currently negative. | not sold and latest unrealized PnL < 0 | Open lots plus valuation | Time-based Exit Outcome | Operator review | count/class | Requires current valuation. | beneficial exit | Status: `implemented`, `partial` when valuation is missing, `experimental` for shared use. Related but not identical. |
| `still_open_positive` | Diagnostic | Still-open candidate currently positive. | not sold and latest unrealized PnL >= 0 | Open lots plus valuation | Time-based Exit Outcome | Operator review | count/class | Requires current valuation. | harmful exit | Status: `implemented`, `partial` when valuation is missing, `experimental` for shared use. Positive open PnL does not prove realized outcome. |
| `inconclusive` | Diagnostic | Candidate lacks enough evidence for beneficial/harmful classification. | classifier fallback | Derived | Time-based Exit Outcome | Operator review | count/class | Default when data missing. | no outcome | Status: `implemented`, `experimental`. Includes insufficient data and some normal-strategy sells. |
| `recommendation` | KPI | Operator-facing time-based-exit policy recommendation. | summary classifier over outcome counts | Derived | Time-based Exit Outcome | Operator review | string | Conservative when evidence is weak. | runtime config | Status: `implemented`, `experimental`. Does not change live SELL policy. |
| `per_symbol_summary` | Diagnostic | Calibrate time-based exit outcomes by symbol. | group candidate outcomes by symbol and summarize counts, realized/current PnL, estimated released capital, and beneficial/harmful ratios | Derived from Time-based Exit Outcome rows | Time-based Exit Outcome | Operator review, daily audit bundle | list | Empty when no candidate symbols. | dashboard contract | Status: `implemented`, `experimental`. Bot-local JSON/TXT only. |
| `candidate_age_hours` | Diagnostic | Candidate holding age used for time-based exit outcome calibration. | persisted age when available; otherwise candidate timestamp minus oldest safe lot-open timestamp; safe current-open-lot evidence may be marked approximate | `sell_decision_events` diagnostics plus `position_lots.opened_at` read-only evidence | Time-based Exit Outcome | Operator review, daily audit bundle | hours | `None` when no persisted, derived, or safe approximate source exists. | current open-position age KPI | Status: `implemented`, `experimental`. Bot-local output only. |
| `age_source` | Diagnostic | Explains how `candidate_age_hours` was sourced. | enum: `persisted`, `derived_from_open_lot`, `approximated_from_current_open_lot`, or `unknown` | Derived from candidate payload and lot evidence | Time-based Exit Outcome | Operator review, daily audit bundle | enum/string | `unknown` when no safe age evidence exists. | data quality status | Status: `implemented`, `experimental`. Approximate sources must remain visible. |
| `holding_bucket_summary` | Diagnostic | Calibrate outcomes by candidate holding age. | group candidate outcomes by `<6h`, `6-12h`, `12-24h`, `24-48h`, `48-72h`, `>72h`, or `unknown` from `candidate_age_hours` evidence | Candidate diagnostics plus `position_lots.opened_at` read-only evidence | Time-based Exit Outcome | Operator review, daily audit bundle | list | Missing age goes to `unknown`, not zero; source counts expose persisted, derived, approximate, and unknown evidence. | open-position age KPI | Status: `implemented`, `experimental`. |
| `age_source_counts` | Diagnostic | Show age-source mix inside a holding bucket or symbol holding bucket. | count candidates grouped by `age_source` | Derived from candidate rows | Time-based Exit Outcome | Operator review, daily audit bundle | map/count | Empty map when the group has no rows. | candidate outcome counts | Status: `implemented`, `experimental`. Helps detect approximation-heavy reports. |
| `unknown_age_count` | Diagnostic | Count candidates in a holding bucket group whose age could not be derived. | count rows where `candidate_age_hours is None` | Derived from candidate rows | Time-based Exit Outcome | Operator review, daily audit bundle | count | Zero when every row has persisted, derived, or approximate age. | unknown PnL count | Status: `implemented`, `experimental`. |
| `holding_bucket_by_symbol` | Diagnostic | Calibrate holding-age outcomes by symbol. | group candidate outcomes by symbol and holding bucket, including ratios, capital/PnL summaries, `unknown_age_count`, and `age_source_counts` | Derived from Time-based Exit Outcome rows | Time-based Exit Outcome | Operator review, daily audit bundle | object/map | Empty object when no candidate rows. | dashboard contract | Status: `implemented`, `experimental`. Bot-local JSON/TXT only. |
| `pnl_bucket_summary` | Diagnostic | Calibrate outcomes by candidate PnL at detection time. | group candidate outcomes by `<-3%`, `-3% to -2%`, `-2% to -1%`, `-1% to 0%`, `0% to 1%`, `1% to 2%`, `>2%`, or `unknown` | `sell_decision_events.estimated_pnl_percent` | Time-based Exit Outcome | Operator review, daily audit bundle | list | Missing PnL goes to `unknown`, not zero. | realized PnL buckets | Status: `implemented`, `experimental`. |
| `symbol_pnl_bucket_summary` | Diagnostic | Find symbol-specific PnL bands where a global rule may be useful or risky. | group candidate outcomes by symbol plus PnL bucket | Derived | Time-based Exit Outcome | Operator review, daily audit bundle | list | Empty when no candidate rows. | per-symbol PnL performance | Status: `implemented`, `experimental`. Review aid only. |
| `beneficial_ratio` | Diagnostic | Share of a calibration group where earlier exit appears beneficial. | `beneficial / candidates * 100` | Derived from outcome classification | Time-based Exit Outcome | Operator review, daily audit bundle | percent | `None` when candidate denominator is zero. | win rate | Status: `implemented`, `experimental`. Beneficial includes later loss sells and still-open negative candidates. |
| `harmful_ratio` | Diagnostic | Share of a calibration group where earlier exit appears harmful. | `harmful / candidates * 100` | Derived from outcome classification | Time-based Exit Outcome | Operator review, daily audit bundle | percent | `None` when candidate denominator is zero. | loss rate | Status: `implemented`, `experimental`. Harmful includes later profitable sells and still-open positive candidates. |
| `calibration_hints` | Diagnostic | Conservative daily-audit hints for time-based exit threshold review. | derived lists of high-beneficial/low-harmful symbols, mixed/risky symbols, promising or harmful buckets, high-unknown-age symbols, and unknown/approximation warnings | Derived | Time-based Exit Outcome | Operator review, daily audit bundle | object/list | Empty lists when no matching hints; warnings list reports unknown-heavy or approximation-heavy evidence. | live activation decision | Status: `implemented`, `experimental`. Does not alter `recommendation` or runtime config. |

## Accounting / Reconciliation Health

Source family: healthcheck reconciliation details, audit events, inventory gap
analysis, and shared DB contract.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `reconciliation_ok` | KPI | Whether latest reconciliation is healthy. | latest healthcheck reconciliation status | `bot_healthcheck.details.reconciliation` | Bot cycle healthcheck | Dashboard/mobile, audit | boolean | Missing means unknown, not healthy. | process liveness | Accounting health, not app uptime. |
| `inventory_warnings_count` | KPI | Count reconciliation inventory warnings. | `len(inventory_warnings[])` | `bot_healthcheck.details.reconciliation` | Bot cycle healthcheck | `/buy_status`, dashboard/mobile | count | Zero only when details are present and empty. | alert count | Warning severity may vary. |
| `missing_portfolio_rows_count` | KPI | Open lots missing portfolio projection rows. | count open-lot symbols without portfolio row | Healthcheck reconciliation details | Bot cycle healthcheck | Dashboard/mobile, audit | count | Missing means unavailable. | unknown valuation | Missing row can still be material. |
| `material_missing_portfolio_rows_count` | KPI | Material open lots missing portfolio projection. | count missing rows with known material notional | Healthcheck reconciliation details | Bot cycle healthcheck | Dashboard/mobile, audit | count | Missing valuation is counted separately. | total missing rows | Material subset only. |
| `unknown_valuation_missing_portfolio_rows_count` | Diagnostic | Missing portfolio rows where notional cannot be valued. | count missing rows with unknown valuation | Healthcheck reconciliation details | Bot cycle healthcheck | Dashboard/mobile, audit | count | Missing means unavailable. | dust missing rows | Conservative visibility for unknown exposure. |
| `portfolio_rows_without_open_lots_count` | KPI | Portfolio projection rows not backed by open lots. | count positive portfolio rows without open lots | Healthcheck reconciliation details | Bot cycle healthcheck | Dashboard/mobile, audit | count | Missing means unavailable. | dust residuals | Could be projection lag, external movement, or dust. |
| `quantity_drift_count` | KPI | Symbols where portfolio quantity and open lots drift. | count symbols with quantity mismatch beyond tolerance | Healthcheck reconciliation details | Bot cycle healthcheck | Dashboard/mobile, audit | count | Missing means unavailable. | price drift | Quantity/accounting mismatch only. |
| `sell_closure_gaps` | KPI | FILLED SELLs whose executed quantity differs from FIFO closures. | compare `trade_operations.executed_base_qty` to `sum(lot_closures.quantity_closed)` | `trade_operations`, `lot_closures` | Inventory gap analyzer | Operator review | count/list | Empty when no gaps found in window. | residual cleanup metadata | Closure gap is accounting evidence. |

## Performance / PnL

Source family: `get_audit_events.py`, Trapped Capital holding-time buckets,
`lot_closures`, and `trade_operations`.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `realized_pnl` | KPI | FIFO realized PnL from closed lots. | `sum(lot_closures.realized_pnl)` | `lot_closures` | Audit, Trapped Capital | Operator review | USDT | Missing closures mean unavailable, not zero unless query result is empty. | unrealized PnL | Accounting-realized layer. |
| `normalized_fees` | KPI | Fees normalized for review. | aggregate fees when fill/operation data supports normalization | `trade_fills`, `trade_operations` | Audit events | Operator review | USDT or asset-specific | Unavailable when source data lacks fee evidence. | realized PnL | Fee treatment must be explicit. |
| `win_rate` | KPI | Share of closed outcomes with positive PnL. | `wins / closed_count * 100` | `lot_closures` buckets | Trapped Capital, audit-style reports | Operator review | percent | `None` when no closed sample. | profitable symbols count | Depends on grouping window. |
| `average_win_loss` | KPI | Average winning and losing realized PnL. | avg positive PnL and avg negative PnL | `lot_closures` | Planned/current bucket summaries | Operator review | USDT | `None` when side has no samples. | profit factor | Uses arithmetic averages. |
| `profit_factor` | KPI | Gross wins divided by gross losses. | `sum(winning pnl) / abs(sum(losing pnl))` | `lot_closures` | Planned | Future performance report | ratio | `None` when no losses or no sample. | win rate | Status: `planned`. Not currently a primary emitted field. |
| `gross_deployed_capital_approximation` | Diagnostic | Approximate capital deployed through operations. | sum BUY gross quote or closed notional when available | `trade_operations.gross_quote`, closures | Audit/Trapped Capital | Operator review | USDT | Unavailable when notional evidence missing. | account equity | Approximation, not audited cashflow. |
| `pnl_by_symbol` | KPI | Realized PnL grouped by symbol. | `sum(realized_pnl) group by symbol` | `lot_closures` | Audit-style reports | Operator review | USDT | Empty when no closures in window. | unrealized symbol PnL | Realized only. |
| `pnl_by_day` | KPI | Realized PnL grouped by UTC calendar day. | `sum(lot_closures.realized_pnl)` grouped by linked operation `executed_at`, falling back to `created_at` only when execution time is null | `lot_closures.realized_pnl`, linked `trade_operations` timestamp | Django Analytics | Analytics, `/buy_status` current UTC day | USDT/day | Empty when no linked operation timestamps fall in the UTC day; closures without a linked operation timestamp remain in total/symbol PnL but not day grouping. | Daily Audit rolling previous-24h window; Binance "Today's PNL" | UTC interval is `[00:00, next 00:00)`. |
| `manual_accounting_adjustment_pnl` | Diagnostic | PnL from manual/accounting-only corrections. | sum PnL for operations marked manual/accounting-only | `trade_operations.raw_payload`, `lot_closures` | Audit events | Operator review | USDT | Zero/empty when no marked operations. | strategy PnL | Excluded from trading-quality metrics when marked. |

## Portfolio Status

Source family: Django `/portfolio_status` over open `position_lots`,
`portfolio.current_price`, latest healthcheck details, and UTC-day linked lot
closures. These are read-only dashboard metrics and do not change accounting or
trading behavior.

| Canonical name | Category | Purpose | Formula | Source of truth | Current producer | Current consumers | Units | Null/unavailable behavior | Do not confuse with | Notes / caveats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `portfolio_status_equity_usdt` | KPI | Current compact portfolio equity visible in Telegram. | `free_usdt + portfolio_status_open_value_usdt` | Healthcheck free USDT plus lot-backed quantities valued with `portfolio.current_price` | Django `/portfolio_status` | Telegram operators | USDT | Unavailable when free USDT or any open-lot current valuation is missing or stale. | audited account equity; Binance total balance | Current projection only. No Binance call is made. |
| `portfolio_status_open_value_usdt` | KPI | Current valued open-lot exposure. | Sum `open lot quantity * portfolio.current_price` for all positive open-lot symbols | `position_lots` quantity plus `portfolio` valuation | Django `/portfolio_status` | Telegram operators | USDT | Unavailable when any open-lot symbol lacks a usable current price or current projection timestamp. | `material_exposure_usdt` in BUY status | Lot-backed quantity rather than portfolio quantity; includes valued dust. Freshness uses the configured healthcheck stale threshold. |
| `portfolio_status_unrealized_pnl_usdt` | KPI | Aggregate current unrealized PnL for material open lots. | Sum `current value - lot cost basis` | `position_lots` quantity/entry price plus `portfolio.current_price` | Django `/portfolio_status` | Telegram operators | USDT | Unavailable when any required current price or material lot entry price is missing/non-positive. | realized PnL | Projection valuation, not audited realization. |
| `portfolio_status_unrealized_pnl_pct` | Diagnostic | Aggregate unrealized return on material lot cost basis. | `portfolio_status_unrealized_pnl_usdt / material cost basis * 100` | Same as aggregate unrealized PnL | Django `/portfolio_status` | Telegram operators | percent | Unavailable with incomplete cost basis; zero for an empty material portfolio. | per-position PnL percent | Cost-basis weighted aggregate. |
| `portfolio_status_best_contributor` | Diagnostic | Material symbol with the highest current unrealized USDT PnL. | `max(symbol unrealized_pnl_usdt)` | Lot-backed symbol cost basis plus projection price | Django `/portfolio_status` | Telegram operators | symbol, USDT, percent | Unavailable when no complete material contributor exists. | realized `pnl_by_symbol` | Current unrealized contribution only. |
| `portfolio_status_worst_contributor` | Diagnostic | Material symbol with the lowest current unrealized USDT PnL. | `min(symbol unrealized_pnl_usdt)` | Lot-backed symbol cost basis plus projection price | Django `/portfolio_status` | Telegram operators | symbol, USDT, percent | Unavailable when no complete material contributor exists. | realized `pnl_by_symbol` | Current unrealized contribution only. |
| `portfolio_status_24h_realized_driver` | Diagnostic | Main realized symbol shown in `/portfolio_status` PnL context. | Current UTC-day `sum(lot_closures.realized_pnl) group by symbol`, then choose the largest absolute non-zero symbol PnL for compact display. | `trade_operations` UTC operation timestamp window plus linked `lot_closures.realized_pnl` | Django `/portfolio_status` | Telegram operators | symbol, USDT | Unavailable when realized breakdown evidence cannot be read; renders `none` when the read succeeds but no contributor exists. | full realized PnL audit; Binance "Today's PNL"; historical 24h equity attribution | Uses the same current UTC calendar-day rule as Analytics and `/buy_status`, not a rolling previous-24h or snapshot-delta attribution. |
| `portfolio_status_24h_unrealized_driver` | Diagnostic | Current open-position unrealized symbol shown in `/portfolio_status` PnL context. | Select current material open-lot unrealized contributor from `position_lots` valued with `portfolio.current_price`; when reliable 24h change sign exists, prefer worst contributor for negative change and best contributor for positive change, otherwise largest absolute current contributor. | `position_lots` quantity/cost basis plus `portfolio.current_price` | Django `/portfolio_status` | Telegram operators | symbol, USDT | Unavailable when current valuation or material cost-basis evidence is incomplete. | exact historical 24h attribution; realized PnL | Current projection approximation only; it gives visible current context and does not explain free-USDT or open-value changes between snapshots. |
| `portfolio_status_change_24h_7d_30d` | Diagnostic | Historical equity change for compact Telegram review. | Latest reliable canonical bot-cycle snapshot equity minus the closest reliable historical canonical bot-cycle snapshot inside the horizon tolerance window, with percentage over historical equity. Tolerances are 18-30h for 24h, 6-8d for 7d, and 28-32d for 30d. | `bot.portfolio_snapshots` rows with `source = "bot_cycle"` and `notes.portfolio_equity_usdt` only | Django `/portfolio_status` | Telegram operators | USDT and percent | Window is unavailable when the latest snapshot is stale, no historical snapshot exists inside the horizon tolerance window, the source is not `bot_cycle`, or `portfolio_equity_usdt` is missing, invalid, or non-positive. Missing history never becomes zero, interpolated, backfilled, inferred from `portfolio`, read from `portfolio_sync_from_api`, or replaced with `open_value_usdt`. | realized PnL; price-only return; open value | Status: `implemented` in Django consumer; paired bot registry synchronization still needs verification when that repository is available. |
| `portfolio_status_equity_chart_7d_png` | Diagnostic | On-demand mobile chart of portfolio equity over the last seven days. | Render reliable 7-day canonical bot-cycle snapshot equity points as a PNG line chart | `bot.portfolio_snapshots` rows with `source = "bot_cycle"` and `notes.portfolio_equity_usdt` only | Django `/portfolio_status` chart renderer | Telegram operators; reusable by future transports | PNG bytes | Unavailable when fewer than two usable 7-day canonical bot-cycle points exist or rendering/sending fails; generated images are not persisted. `portfolio_sync_from_api` and `open_value_usdt` are not chart fallbacks. | historical change values | Transport-agnostic chart bytes; Telegram delivery is an adapter concern. |

## Planned Governance

Before adding new KPI output:

1. Check this registry for an existing canonical metric or alias.
2. Add a registry entry before implementing a new metric family.
3. State whether the metric is KPI, Diagnostic, Helper, Alias, or Planned.
4. State the metric status: `implemented`, `partial`, `planned`, `alias`,
   `deprecated`, or `experimental`.
5. State whether output is bot-local only or a shared/dashboard contract.
6. Prefer backward-compatible additions over renaming or removing existing
   output fields.
