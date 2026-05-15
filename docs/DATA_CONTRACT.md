# DATA_CONTRACT.md — Binance Bot Shared Database Contract (v2)

This document defines the shared database contract between the **Binance Python Bot** and external consumers such as a **Django Dashboard**.

The bot and dashboard are separate projects. They do not share application code. They only share the database.

The dashboard must treat this document as the source of truth for interpreting bot-owned data.

---

## 1. System Boundary

### Trading Bot

Responsible for:

- Binance API interaction
- BUY / SELL execution
- FIFO accounting
- Portfolio projection updates
- Trade reconciliation
- Healthcheck / snapshots
- Writing trading-owned database tables

### Dashboard

Responsible for:

- Reading bot state
- Showing operational and financial status
- Displaying positions, lots, trades, healthchecks and alerts
- Sending only explicit control commands if a safe control table exists

The dashboard must not execute trading logic.

### Current Django model mappings

Dashboard routes, read models, forms, and templates live in the `dashboard` Django app. Database table mappings remain in the apps below.

The dashboard currently maps bot-owned tables in `core.trading_models` with `managed = False` and read-only save/delete guards:

- `bot.bot_healthcheck`
- `bot.portfolio`
- `bot.position_lots`
- `bot.trade_operations`
- `bot.trade_fills`
- `bot.lot_closures`
- `bot.snapshots`
- `bot.dust_detections`
- `bot.sell_decision_events`

The dashboard also maps workflow tables in `core.models`:

- `bot.dust_signal_reviews`
- `bot.manual_corrections`

When the configured database engine is SQLite, `bot_table_name()` maps selected workflow tables to plain table names for local/test compatibility. PostgreSQL deployments use the `bot` schema table names.

### Current API serializers

DRF serializers currently exist for:

- `profile.UserProfile` through `ProfileSerializer`
- `currencyconverter.Currency` through `CurrencySerializer` and `CurrencyDetailSerializer`
- `currencyconverter.ExchangeRate` through `ExchangeRateSerializer`

No DRF serializer currently wraps bot-owned trading tables.

### Current API routes

- `/api/login/` returns an auth token through DRF `ObtainAuthToken`.
- `/api/profiles/` exposes the profile viewset.
- `/currencyconverter/json/currencies/` exposes currency list/detail endpoints.
- `/currencyconverter/json/exchangerates/` exposes exchange-rate list/detail endpoints.
- `/api/schema` exposes the OpenAPI schema.
- `/api/docs` exposes Swagger UI.
- `/health/` exposes a public Django app liveness response for keepalive checks. It does not read or interpret bot-owned healthcheck data.

Compatibility note: bot-owned table schemas are external contracts. Dashboard model field changes must be reviewed against the bot schema before release.

---

## 2. Core Principle

### Accounting Source of Truth

`position_lots` is the accounting source of truth.

`portfolio` is a projection / read layer.

This distinction is critical.

A row in `portfolio` may look like the current position, but the authoritative tradable inventory is in `position_lots`.

### Critical Rule

SELL coverage must always be calculated from open lots in `position_lots`, never from `portfolio`.

### Projection Drift

Small differences between `portfolio` and `position_lots` may exist because of:

- Binance dust
- manual external operations
- rounding
- incomplete historical data
- projection lag
- fees charged in base asset

The dashboard should surface drift as an alert, not silently hide it.

---

## 3. Core Tables and Semantics

## 3.1 `trade_fills`

Raw execution data from Binance.

Represents the lowest-level fill information returned by Binance after an order execution.

Typical usage:

- Audit trail
- Fee tracking
- Execution price reconstruction
- Debugging Binance-level behavior

Dashboard usage:

- Optional detailed view
- Do not use directly for high-level PnL unless aggregation rules are clear

Conceptual fields:

- order id
- symbol
- side
- executed quantity
- executed price
- quote quantity
- commission / fee
- commission asset
- timestamp

---

## 3.2 `trade_operations`

Economic operation layer.

Represents aggregated BUY / SELL operations derived from one or more Binance fills.

Typical usage:

- Recent trades table
- Realized PnL summary when available
- Fee summary when available
- Operation status and rejection diagnostics

Dashboard usage:

- Show last BUY / SELL operations
- Show side, symbol, status, quantities, prices, fees, realized PnL if present
- Prefer this table over raw fills for user-facing trade history

Conceptual fields:

- operation id
- order id
- symbol
- side: BUY / SELL
- status
- executed base quantity
- executed quote quantity
- average price
- fees
- realized PnL for SELL if available
- created / executed timestamp

Important desired constraints:

- `UNIQUE(order_id)` to avoid duplicate operation records
- critical quantities and operation identifiers should be NOT NULL where possible

---

## 3.3 `position_lots`

FIFO inventory source of truth.

Each BUY creates or increases open lots.
Each SELL closes lots using FIFO logic.

This is the authoritative table for real tradable inventory.

Dashboard usage:

- Calculate open lot quantity by asset / symbol
- Detect dust / small residual inventory
- Validate portfolio projection consistency
- Show detailed lot-level inventory if needed

Conceptual fields:

- lot id
- symbol
- asset
- original quantity
- remaining/open quantity
- entry price
- status: open / closed / partial
- opened by trade operation
- opened timestamp
- updated timestamp

Open inventory logic:

```sql
-- Conceptual only. Adjust column names to actual schema.
select
    symbol,
    sum(remaining_quantity) as open_quantity
from bot.position_lots
where remaining_quantity > 0
group by symbol;
```

Important:

- Do not calculate SELL coverage from `portfolio`.
- Use only open lots / positive remaining quantity.

---

## 3.4 `lot_closures`

FIFO closure records.

Represents how SELL operations close previously opened lots.

Typical usage:

- Realized PnL calculation
- FIFO audit trail
- Validation of SELL correctness

Dashboard usage:

- Show realized PnL details
- Validate that SELL executed quantity equals closed lot quantity
- Detect incomplete closures

Conceptual fields:

- closure id
- sell trade operation id
- closed lot id
- closed quantity
- entry price
- exit price
- realized PnL
- timestamp

Important desired constraints:

- `trade_operation_id` should be NOT NULL
- closures must reconcile with SELL operations

---

## 3.5 `portfolio`

Materialized portfolio projection.

A read-optimized snapshot of current positions.

Dashboard usage:

- Main positions table
- Approximate current value
- Unrealized PnL if entry/current prices are available

Important:

- `portfolio` is not the accounting source of truth.
- It may drift from `position_lots`.
- Always cross-check with `position_lots` for consistency alerts.

Conceptual fields:

- symbol
- asset
- quantity
- entry price
- current price
- updated timestamp

Suggested dashboard calculations:

```text
position_value = quantity * current_price
unrealized_pnl = (current_price - entry_price) * quantity
```

Only calculate if all required values exist.

---

## 3.6 `bot.bot_healthcheck`

Operational health status written by the bot.

Dashboard usage:

- Last bot heartbeat
- Last cycle status
- Error status if available
- Running / stale / unknown indicators

Conceptual fields:

- status
- heartbeat timestamp, currently `created_at`
- details payload, which may include error context
- run id if available

Current bot healthcheck details may include additive material-position
classification fields:

- `positions_count`: raw positive-quantity portfolio rows
- `material_positions_count`: rows with estimated value greater than or equal
  to `DUST_MIN_NOTIONAL_USDT`
- `dust_positions_count`: rows with estimated value greater than zero and below
  `DUST_MIN_NOTIONAL_USDT`
- `unknown_value_positions_count`: positive-quantity rows with missing, null,
  or non-positive current price
- `material_symbols`
- `dust_symbols`
- `unknown_value_symbols`

These fields are healthcheck JSON details only. They do not add or modify
database columns, and they do not change the accounting source-of-truth model.
BUY exposure gating uses material positions plus unknown-value positions,
conservatively treating unknown-value rows as exposure until price is known.
Dust positions remain excluded from BUY gating because they are non-material
exposure, even though they may remain latent inventory and possible future
reusable liquidity. `portfolio` remains a projection and `position_lots`
remains the FIFO accounting truth.

Dashboard Telegram diagnostics may expose `/buy_status` from these persisted
healthcheck details. The diagnostic is read-only and conservative: if max
positions or capital data are not exposed by the bot, the dashboard reports
`N/A`, `unknown`, or `uncertain` rather than asserting that BUYs are possible.

Suggested dashboard status logic:

```text
Healthy: recent healthcheck, using `created_at` as the current heartbeat timestamp
Stale: latest healthcheck heartbeat older than threshold
Unknown: no healthcheck available
Error: latest status indicates failure
```

Threshold should be configurable. Start with 5–15 minutes depending on bot interval.

---

## 3.7 `snapshots`

Periodic bot state snapshots.

Dashboard usage:

- Historical state
- Last known portfolio/bot snapshot
- Future charts

Do not depend on this table for critical accounting unless its schema and semantics are verified.

---

## 3.8 `sell_decision_events`

Read-only SELL diagnostics emitted by the bot.

Dashboard usage:

- Show the latest SELL diagnostic for a symbol.
- Explain the latest rejected or skipped SELL event to mobile operators.
- Inspect validation details without executing trades or mutating accounting.

Current Telegram diagnostics read these conceptual fields when available:

- symbol
- event_name
- reason
- validation_stage
- estimated_pnl_percent
- entry_price
- current_price
- configured_stop_loss
- normalized_stop_loss_threshold
- stop_loss_threshold
- take_profit_threshold
- sell_decision_reason
- profit_guard_bypassed
- created_at
- payload

Dashboard position exit status may also read additive payload fields when the
bot emits them:

- `run_id`
- `asset`
- `open_lot_quantity`
- `portfolio_quantity`
- `estimated_value_usdt`
- `reason`
- `reasons`
- `strategy_name`
- `evaluated_at`

The dashboard treats these fields as explanation metadata only. Open inventory
still comes from `bot.position_lots`; `portfolio` remains display/projection
only.

Stop-loss contract:

- `STOP_LOSS_PCT` is an operator-facing loss percentage input.
- Supported forms `3`, `0.03`, `-3`, and `-0.03` normalize to the same internal
  threshold: `-3%`.
- Internal comparison uses negative-loss semantics.
- `stop_loss_reached` with `estimated_pnl_percent > 0` is invalid diagnostic
  data and should be treated as an operational anomaly.
- `profit_guard_bypassed=true` is valid only for real-loss stop-loss exits.

Normalized SELL evaluation reason values:

- `take_profit_not_reached`
- `stop_loss_not_reached`
- `take_profit_reached`
- `stop_loss_reached`
- `no_open_lots`
- `insufficient_binance_balance`
- `quantity_below_step_size`
- `quantity_below_min_qty`
- `quantity_below_min_notional`
- `rounded_quantity_zero`
- `realized_profit_below_threshold`
- `dust_residual_protection`
- `strategy_hold`
- `exchange_filter_missing`
- `read_only`
- `unknown`

Important:

- This table is diagnostics/audit data only.
- Dashboard consumers must not derive SELL coverage from this table.
- Dashboard consumers must not update or delete rows in this table.
- Telegram/mobile responses must escape dynamic values before HTML rendering.
- Dashboard consumers may use latest rows to explain why an open-lot symbol is
  currently not selling, but must not treat those rows as accounting state.

---

## 3.9 Optional `bot_control`

A safe control-plane table may exist or be added intentionally.

Dashboard usage:

- Stop / Resume requests
- Display desired state
- Display who last changed the state

Suggested conceptual fields:

- id
- desired_state: running / paused
- updated_by
- updated_at
- reason

Rules:

- Dashboard may write only to this table if intentionally implemented.
- Bot should read this table safely at cycle boundaries.
- Stop / Resume must be POST-only and CSRF-protected.
- Dashboard must never kill the bot process directly unless explicitly designed and secured.

---

## 4. Data Flows

## BUY Flow

```text
Binance order/fills
→ trade_fills
→ trade_operations
→ position_lots
→ portfolio
```

Meaning:

- Binance returns one or more fills.
- The bot persists raw fills.
- The bot creates an economic BUY operation.
- The BUY opens one or more lots.
- Portfolio is refreshed as a projection.

## SELL Flow

```text
Binance order/fills
→ trade_fills
→ trade_operations
→ lot_closures
→ position_lots
→ portfolio
```

Meaning:

- Binance returns one or more fills.
- The bot persists raw fills.
- The bot creates an economic SELL operation.
- The SELL closes existing lots using FIFO.
- Lot remaining quantities are updated.
- Portfolio is refreshed as a projection.

Optional opt-in SELL-side SPOT dust cleanup can make the Binance SELL execution
quantity larger than the FIFO closure quantity. In that case:

- a normal lot-backed SELL signal must already exist
- only same-asset SPOT-free residual quantity may be appended
- `trade_operations.executed_base_qty` remains the full Binance execution
  quantity
- SELL fill metadata `executed_qty` remains the full Binance execution quantity
- FIFO closes only `lot_backed_quantity`
- the extra residual is described in JSON payload metadata, not represented as
  a lot closure

Current metadata keys:

- `spot_dust_included`
- `lot_backed_quantity`
- `extra_spot_dust_quantity`
- `extra_spot_dust_estimated_value_usdt`
- `dust_cleanup_policy = "append_same_asset_spot_dust_to_normal_sell"`

Concrete example:

```text
executed_base_qty = 0.00038435
lot_backed_quantity = 0.00037000
extra_spot_dust_quantity = 0.00001435
```

---

## 5. Invariants

These invariants define what a healthy database should approximately satisfy.

### 5.1 Lots vs Portfolio Quantity

For every symbol with open lots:

```text
SUM(position_lots.remaining_quantity) ≈ portfolio.quantity
```

This should allow a small tolerance for dust and rounding.

### 5.2 No SELL Without Lot Closures

Every filled SELL operation should have matching `lot_closures` rows for the
lot-backed accounting quantity.

```text
normal SELL:
SELL executed quantity ≈ SUM(lot_closures.closed_quantity)

SELL with spot_dust_included=true:
lot_backed_quantity ≈ SUM(lot_closures.closed_quantity)
```

### 5.3 No Negative Open Quantity

Open lot remaining quantity should never be negative.

### 5.4 Closed Lots Should Not Have Remaining Quantity

A fully closed lot should have zero remaining quantity.

### 5.5 Open Lots Should Have Positive Remaining Quantity

An open or partial lot should have positive remaining quantity.

### 5.6 BUY Operations Should Open Lots

Every filled BUY operation should create at least one corresponding lot, unless it is explicitly recorded as skipped/rejected/failed.

### 5.7 Fees Should Be Accounted For

Fees should be visible either in `trade_fills`, `trade_operations`, or both.

### 5.8 Order Idempotency

A Binance `order_id` should not create duplicate economic operations.

Desired constraint:

```text
UNIQUE(order_id)
```

---

## 6. Reference SQL Checks

These queries are intentionally written as templates. Adjust schema and column names to the actual database.

### 6.1 Inspect Tables

```sql
select table_schema, table_name
from information_schema.tables
where table_schema not in ('pg_catalog', 'information_schema')
order by table_schema, table_name;
```

### 6.2 Inspect Columns

```sql
select
    table_schema,
    table_name,
    column_name,
    data_type,
    is_nullable
from information_schema.columns
where table_schema not in ('pg_catalog', 'information_schema')
order by table_schema, table_name, ordinal_position;
```

### 6.3 Inspect Constraints

```sql
select
    tc.table_schema,
    tc.table_name,
    tc.constraint_name,
    tc.constraint_type,
    kcu.column_name
from information_schema.table_constraints tc
left join information_schema.key_column_usage kcu
    on tc.constraint_name = kcu.constraint_name
   and tc.table_schema = kcu.table_schema
where tc.table_schema not in ('pg_catalog', 'information_schema')
order by tc.table_schema, tc.table_name, tc.constraint_type;
```

### 6.4 Open Lots by Symbol

```sql
-- Adjust remaining_quantity/status names if needed.
select
    symbol,
    sum(remaining_quantity) as open_lot_quantity,
    count(*) as open_lot_count
from bot.position_lots
where remaining_quantity > 0
group by symbol
order by symbol;
```

### 6.5 Portfolio vs Lots Drift

```sql
-- Adjust column names and schema names if needed.
with lots as (
    select
        symbol,
        sum(remaining_quantity) as lot_quantity
    from bot.position_lots
    where remaining_quantity > 0
    group by symbol
), portfolio_positions as (
    select
        symbol,
        quantity as portfolio_quantity
    from bot.portfolio
)
select
    coalesce(p.symbol, l.symbol) as symbol,
    coalesce(p.portfolio_quantity, 0) as portfolio_quantity,
    coalesce(l.lot_quantity, 0) as lot_quantity,
    coalesce(p.portfolio_quantity, 0) - coalesce(l.lot_quantity, 0) as quantity_diff
from portfolio_positions p
full outer join lots l on l.symbol = p.symbol
where abs(coalesce(p.portfolio_quantity, 0) - coalesce(l.lot_quantity, 0)) > 0.00000001
order by symbol;
```

### 6.6 SELL Operations Without Closures

```sql
-- Adjust executed_base_qty / closed_quantity names if needed.
select
    op.id,
    op.order_id,
    op.symbol,
    op.executed_base_qty,
    coalesce(sum(lc.closed_quantity), 0) as closed_quantity,
    op.executed_base_qty - coalesce(sum(lc.closed_quantity), 0) as diff
from bot.trade_operations op
left join bot.lot_closures lc
    on lc.trade_operation_id = op.id
where op.side = 'SELL'
  and op.status = 'FILLED'
group by op.id, op.order_id, op.symbol, op.executed_base_qty
having abs(op.executed_base_qty - coalesce(sum(lc.closed_quantity), 0)) > 0.00000001
order by op.id desc;
```

### 6.7 BUY Operations Without Lots

```sql
-- Adjust opened_by_trade_operation_id if actual FK name differs.
select
    op.id,
    op.order_id,
    op.symbol,
    op.executed_base_qty,
    count(pl.id) as opened_lots
from bot.trade_operations op
left join bot.position_lots pl
    on pl.opened_by_trade_operation_id = op.id
where op.side = 'BUY'
  and op.status = 'FILLED'
group by op.id, op.order_id, op.symbol, op.executed_base_qty
having count(pl.id) = 0
order by op.id desc;
```

### 6.8 Negative Remaining Lots

```sql
select *
from bot.position_lots
where remaining_quantity < 0
order by updated_at desc;
```

### 6.9 Dust Candidates

```sql
-- If current price is available in portfolio.
-- Adjust threshold. Example: 5 USDT.
with open_lots as (
    select
        symbol,
        sum(remaining_quantity) as open_quantity
    from bot.position_lots
    where remaining_quantity > 0
    group by symbol
)
select
    l.symbol,
    l.open_quantity,
    p.current_price,
    l.open_quantity * p.current_price as estimated_value
from open_lots l
left join bot.portfolio p on p.symbol = l.symbol
where p.current_price is not null
  and l.open_quantity * p.current_price > 0
  and l.open_quantity * p.current_price < 5
order by estimated_value asc;
```

### 6.10 Recent Rejections / Skips

```sql
-- Adjust status/rejection_reason names if needed.
select *
from bot.trade_operations
where status not in ('FILLED', 'SUCCESS')
order by created_at desc
limit 50;
```

### 6.11 Latest Healthcheck

```sql
select *
from bot.bot_healthcheck
order by created_at desc, id desc
limit 1;
```

---

## 7. Dashboard Read Model Guidelines

## 7.1 Bot Status Card

Use `healthcheck` if available.

Show:

- Current status
- Last heartbeat / last cycle
- Last error if present
- Age of last update

Status interpretation should be defensive:

- No row = Unknown
- Old row = Stale
- Error status = Error
- Recent OK = Healthy

Homepage badge normalization treats `OK`, `ok`, `healthy`, and `success` as
healthy; stale heartbeats override the status label; `error`, `failed`, and
`critical` are displayed as errors; missing rows are unknown; and other statuses
are warnings.

## 7.2 Financial Summary

Use `portfolio` for display values.
Use `position_lots` for validation.
Use `trade_operations` / `lot_closures` for realized PnL if available.

Suggested cards:

- Open positions count
- Approximate portfolio value
- Realized PnL
- Total fees
- Drift warnings count
- Dust positions count

Homepage active dust/drift issue summaries should be read-model filters over
existing grouped `bot.dust_detections` data. They should show unresolved
critical/warning signals only, exclude handled review/correction states when
those dashboard workflow tables are available, and keep info-only residuals as
a compact count/exposure summary rather than a homepage active-issue row.

## 7.3 Open Positions

Primary display source: `portfolio`.
Validation source: `position_lots`.

For each symbol/asset:

- Display portfolio quantity
- Display lot open quantity
- Show drift if difference exceeds tolerance
- Display entry price and current price when available
- Display unrealized PnL when calculable

## 7.4 Recent Operations

Primary source: `trade_operations`.

Show latest operations ordered by timestamp descending.

Columns:

- timestamp
- symbol
- side
- status
- executed base quantity
- executed quote quantity
- average price
- fees
- realized PnL when available

## 7.4.1 Fees (USDT) Card

For normalized fee display on USDT pairs, prefer `bot.trade_operations.fee_amount_in_quote` over raw `trade_fills.commission` because it already stores the fee converted to the quote asset.

Recommended query:

```sql
select
    side,
    sum(fee_amount_in_quote) as total_fee_usdt,
    count(*) as operations_count
from bot.trade_operations
where status = 'FILLED'
  and quote_asset = 'USDT'
group by side
order by side;
```

Dashboard display:

- Total fees in USDT = sum of all returned `total_fee_usdt` values
- BUY fees = BUY row
- SELL fees = SELL row
- Operations = sum of `operations_count`

Important:

- This is operational fee reporting, not full audited PnL.
- Do not call Binance from the dashboard to recalculate these values.
- Keep calculations Decimal-safe and round only for display.

## 7.4.2 Performance KPIs (Wave 8 Phase 1)

Dashboard usage:

- Read-only operational visibility only.
- Use `bot.lot_closures.realized_pnl` where available for realized PnL.
- Use `bot.trade_operations.fee_amount_in_quote` for normalized USDT fees on `status = 'FILLED'` and `quote_asset = 'USDT'` operations.
- Do not invent fee conversions for fees that cannot be normalized to USDT.
- Exclude unnormalized fees from normalized USDT fee totals and display that limitation.
- Group realized PnL by symbol through linked `trade_operations` when available.
- Group realized PnL by linked `trade_operations.executed_at` date when available, falling back to linked `trade_operations.created_at`.
- If no linked operation timestamp exists, include the closure in realized PnL totals and symbol grouping but skip it from PnL by day.
- Use FILLED BUY quote value as an initial gross deployed capital approximation and label it as approximate/gross deployed capital.
- Do not reference `lot_closures.timestamp`; that column does not exist in the shared schema.

Current metric semantics:

- Net realized PnL = realized PnL from closures minus normalized USDT fees.
- Win rate ignores zero-PnL closures and reports breakeven separately.
- Average loss is displayed as signed realized PnL.
- Profit factor is `gross_profit / abs(gross_loss)`.
- If gross loss is zero, profit factor should display N/A rather than infinity.

Manual correction handling:

- Manual/accounting correction operations may appear in `trade_operations` and linked `lot_closures`.
- Dashboards may split manual/accounting adjustment PnL only when operation metadata clearly identifies the operation as a manual correction.
- If metadata is unavailable or ambiguous, dashboards should include those rows in realized PnL totals and display the limitation.

Important:

- These KPIs are operational metrics, not audited accounting statements.
- The dashboard must not call Binance or execute trading logic to fill missing data.

## 7.5 BUY Diagnostics Contract - Pending Review

The current shared contract exposes material-position classification through
healthcheck details and BUY/SELL decisions through bot-owned decision surfaces,
but this is not yet enough for a reliable `/buy_status` diagnostic.

Observed diagnostic gap:

```text
BUY state: uncertain
Reason: max positions unavailable
Max positions: N/A
Free USDT: N/A
Latest BUY reason: N/A
```

This can occur even when the runtime reaches `buy_order_plan` and attempts a
Binance BUY, so consumers must treat current `/buy_status` output as incomplete
when key fields are `N/A`.

Future contract options:

1. Extend `bot.bot_healthcheck.details` with stable BUY diagnostic fields:
   `max_positions`, `material_positions_count`,
   `unknown_value_positions_count`, `dust_positions_count`, `free_usdt`,
   `buy_capacity_state`, `latest_buy_state`, `latest_buy_reason`,
   `latest_buy_symbol`, `latest_buy_error_class`, and
   `latest_buy_error_code`.
2. Reuse or expand existing bot-owned order decision data if it already
   contains the needed BUY lifecycle and rejection details.
3. Add a new bot-owned read-only diagnostic table only if existing surfaces are
   insufficient.

Consumer rules:

- Dashboard/Telegram must not infer that BUY is blocked solely because
  diagnostic fields are missing.
- Dust-only inventory should be shown as non-blocking for `max_positions` when
  material-position classification says `material=0` and `unknown=0`.
- Binance execution errors must be shown separately from capacity gating.
- Diagnostics are read-only and must not execute trades, call Binance, or
  mutate accounting state.

---

## 7.6 Runtime Operational Events Contract - Future

Future operational hardening should add a bot-owned event table for important
runtime exceptions and degraded states.

Candidate table:

```text
bot.runtime_events
```

Candidate fields:

- `id BIGSERIAL PRIMARY KEY`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `run_id TEXT NULL`
- `severity TEXT NOT NULL`
- `event_type TEXT NOT NULL`
- `component TEXT NULL`
- `exception_class TEXT NULL`
- `message TEXT NULL`
- `symbol TEXT NULL`
- `traceback_hash TEXT NULL`
- `payload JSONB NOT NULL DEFAULT '{}'::jsonb`

Rules:

- This table is operational observability only.
- It is not accounting truth and not trading state.
- Persisted runtime exceptions may degrade healthcheck status to
  warning/error/critical.
- Dashboard may read and display these events.
- Telegram may alert on warning/error/critical events with dedupe/rate
  limiting.
- Payloads must be sanitized and must not include secrets, raw environment
  values, API keys, DB URLs, or Telegram tokens.
- Persistence failure must not crash the bot or mutate accounting tables.

---

## 7.7 Operational Alerts

Start with simple DB-derived alerts:

- Healthcheck is stale
- Latest healthcheck has error status
- Portfolio quantity differs from open lots quantity
- Open lot exists without portfolio row
- Portfolio row exists without matching open lots
- Dust / small residual open lots
- Recent rejected operations
- SELL operation without matching lot closures
- BUY operation without matching opened lots
- Negative remaining lot quantity

Alerts should be informational unless the condition is clearly critical.

## 7.8 Position Exit Status

The main dashboard may show a read-only “Why positions are not selling” view.

Primary inventory source: `bot.position_lots`.

Display/projection source: `bot.portfolio`.

Explanation source: latest persisted `bot.sell_decision_events` row per symbol.

Required dashboard columns:

- Symbol
- Status label
- Main reason
- Estimated value USDT
- Open lot qty
- Current price
- Suggested action

Suggested action mapping:

- `quantity_below_min_notional`, `quantity_below_min_qty`, or
  `rounded_quantity_zero`: `Dust: review/ignore or wait until reusable`
- `stop_loss_not_reached` and `take_profit_not_reached`:
  `Hold: strategy thresholds not reached`
- `insufficient_binance_balance`:
  `Review drift: Binance balance lower than lots`
- `no_open_lots`: `No accounting inventory`
- `exchange_filter_missing`: `Review exchange metadata`
- `read_only`: `Bot is in READ_ONLY`

Constraints:

- Do not execute trades.
- Do not call Binance from Django.
- Do not mutate `position_lots`, `portfolio`, `trade_operations`,
  `trade_fills`, or `lot_closures`.
- Do not count dust/minNotional rows as material exposure in this view.

---

## 8. Dust / Small Residual Handling

Dust means small residual quantities or values that may be below Binance minimum notional / lot-size requirements.

Dashboard should detect and show dust candidates.

Assets intentionally moved to Earn or held as long-term accumulation inventory should not be silently interpreted as trading drift.

Until explicit Earn/location/accounting semantics exist, these movements should be treated as reviewed external operations.

Do not auto-convert, auto-sell, or move to Earn from the dashboard unless a separate explicit and audited workflow is implemented.

Repeated operational detections may generate multiple `bot.dust_detections`
rows even when Telegram notifications are suppressed. Dashboard consumers must
not assume one Telegram alert per row, one unresolved issue per row, or one
operational incident per row. Repeated rows may represent historical observation
continuity, heartbeat visibility, or unchanged suppressed signals.

Ignored, reviewed, or suppressed rows in `bot.dust_signal_reviews` suppress
matching Telegram paging only. Matching uses the stable available review
signature: `event_type`, `symbol`, `asset`, `reason`, and `severity`.
`bot.dust_signal_reviews` currently has no quantity field, so
`quantity_delta` is not part of the persisted review signature yet. Matching
detections continue to be inserted into `bot.dust_detections` and remain visible
in dashboard history.

Telegram cooldown/rate-limit suppression is runtime-only behavior. Cooldown
state is in-memory, is not persisted, is not part of the shared DB contract,
does not mutate accounting state, and does not imply review completion.

Current DB accounting semantics are based on Binance SPOT visibility. Future
visibility-only integrations may expose Earn, Flexible Earn, Locked Earn, or
Staking balances without changing FIFO accounting ownership, lot closure
semantics, or portfolio source-of-truth semantics.

Suggested first version:

```text
Dust candidate = open lot quantity/value is positive but below configured min notional threshold
```

If exchange filters are not available in the dashboard DB, use a configurable threshold and label it approximate.

Recommended settings:

```text
DUST_MIN_NOTIONAL_USDT = 5
DRIFT_QTY_TOLERANCE = 0.00000001
HEALTHCHECK_STALE_MINUTES = 15
```

---

## 9. Precision Rules

Financial data should be treated as Decimal, not float.

Dashboard display should:

- Use Decimal-safe calculations
- Avoid binary float arithmetic
- Round only for display
- Never write rounded values back to trading tables

Bot-side desired hardening:

- migrate critical financial columns to DB `NUMERIC`
- use Python `Decimal`
- avoid float conversions in repositories and services

---

## 10. Security Rules

- Dashboard must require authentication.
- Dashboard must not expose control actions publicly.
- Any Stop / Resume action must be POST-only and CSRF-protected.
- Do not expose API keys, secrets or raw environment variables.
- Do not display sensitive Binance credentials.
- Dashboard database user should preferably be read-only, except for an explicit control-plane table.
- Telegram diagnostics must restrict access to configured chat/user allowlists.
- Telegram diagnostics must use safe HTML escaping and must not include raw exceptions, DB URLs, tokens, or environment values.

---

## 11. Django Integration Guidelines

Because the dashboard project is separate from the bot project:

- Prefer Django models with `managed = False` for existing bot tables.
- Do not create migrations for existing bot-owned tables unless intentionally extending the shared contract.
- Keep dashboard queries read-only except for explicit control-plane tables.
- Use aggregation queries to avoid N+1 problems.
- Keep all financial calculations defensive around NULL values.
- Use Decimal-safe calculations.

Example model Meta pattern:

```python
class PositionLot(models.Model):
    ...

    class Meta:
        managed = False
        db_table = "bot.position_lots"  # adjust to actual schema/table name
```

Use the actual schema/table names from the database.

---

## 12. Implementation Rule For Codex / Agents

Before changing code:

1. Inspect the existing Django project structure.
2. Inspect actual DB schema or provided schema dump.
3. Map each dashboard metric to a specific table and column.
4. State assumptions explicitly.
5. Keep changes small and reviewable.
6. Do not invent trading semantics from column names alone.
7. Prefer read-only dashboard models for bot-owned tables.
8. Only add migrations for dashboard-owned or intentionally shared control-plane tables.

---

## 13. First Dashboard Version Scope

Recommended first version:

1. Bot status card from `healthcheck`
2. Portfolio summary from `portfolio`
3. Open-lots summary from `position_lots`
4. Drift alerts between portfolio and lots
5. Recent operations from `trade_operations`
6. Basic dust candidates
7. Fees by asset and normalized Fees (USDT) card
8. Existing Stop / Resume UI wired only if a safe backend exists

Avoid in first version:

- Complex charts
- Full PnL attribution if fields are unclear
- Automatic correction workflows
- Trading actions
- Binance API calls from dashboard

---

## 14. Bot Project Responsibilities When Schema Changes

When the bot changes any shared table, update this contract.

Examples that require contract updates:

- new table
- renamed column
- changed status values
- changed quantity semantics
- changed PnL calculation
- changed dust policy
- changed healthcheck format
- changed control-plane behavior

Rule:

```text
If dashboard interpretation could change, DATA_CONTRACT.md must change in the same PR/commit.
```

---

## 15. Known Edge Cases

- Dust can remain after sells because Binance filters prevent selling very small quantities.
- Manual Binance app operations can create drift from bot accounting.
- Fees charged in base asset can reduce balances and create small mismatches.
- Reconciliation may detect external lots or historical incompleteness.
- Portfolio may be temporarily stale during cycle execution.
- Dashboard should display uncertainty rather than force false precision.
- Normalized fee cards should use `trade_operations.fee_amount_in_quote` when available instead of attempting external price conversion.
- Long-term accumulation assets mixed with trading inventory may distort trading metrics and exposure calculations if not explicitly modeled.

---

## 16. Minimal Codex Prompt For Dashboard Work

Use this when asking Codex to work on the dashboard:

```text
Read DATA_CONTRACT.md first.
The dashboard and bot are separate projects and only share the database.
Do not infer trading semantics from column names alone.
Use position_lots as accounting source of truth.
Use portfolio only as projection/read layer.
Do not implement trading logic in the dashboard.
Prefer managed=False Django models for existing bot tables.
Before coding, inspect current project structure and actual DB schema.
Keep changes small, safe and reviewable.
```

---

## 17. Preflight Safety Contract

The bot performs preflight checks before building or running trading services.

Checks:

- Required ENV variables:
  - `DATABASE_URL`
  - `BINANCE_API_KEY`
  - `BINANCE_API_SECRET`
- Database connectivity through a lightweight query
- Binance account access with configured API credentials

Expected behavior:

- On success, log `preflight_ok`.
- On failure, fail fast with non-zero process exit.
- Trading runner must not be built when preflight fails.
- Secrets must never be logged.

---

## 18. DustDetectionService Contract

`DustDetectionService` emits structured logs and, when `DATABASE_URL` is configured, writes observations to `bot.dust_detections`.

Persistence is observational only. It must never sell, convert dust, move assets to Earn, mutate lots, mutate portfolio, or participate in trading transactions. Insert failures are logged as `dust_detection_persistence_failed` and must not crash an otherwise healthy bot cycle.

Events may include:

- `dust_detection_started`
- `dust_candidate_detected`
- `lot_below_min_notional_detected`
- `balance_without_lot_coverage_detected`
- `lot_balance_drift_detected`
- `sell_residual_detected` (persisted event type for recent SELL residual observations)
- `dust_detection_completed`
- `dust_detection_failed`

Expected event fields when available:

- `run_id`
- `asset`
- `symbol`
- `quantity`
- `spot_quantity`
- `open_lot_quantity`
- `quantity_delta`
- `price_usdt`
- `estimated_value_usdt`
- `estimated_delta_value_usdt`
- `reason`
- `severity`

Price / valuation rules:

- Use `portfolio.current_price` as the preferred source for `price_usdt`.
- Use `price_usdt = 1` for USDT.
- Do not call Binance for prices from dust detection.
- Missing prices are allowed.
- If price is missing, `estimated_value_usdt` should be `null` / `None`.
- Valuation is approximate and intended for prioritization, not final accounting.

Classification rules:

- `lot_below_min_notional_detected` remains the event type for small open lots
  below the configured or exchange minNotional threshold.
- A reconciled small open lot is an `info` `below_min_notional` observation
  when Binance SPOT balance and open lots match within tolerance.
- `possible_incomplete_sell` requires stronger evidence, such as a recent SELL
  residual signal or an actual SPOT-vs-lot quantity mismatch. Dashboards should
  not treat every partial open lot below minNotional as an incomplete SELL.

Constraints:

- No automatic selling.
- No automatic Binance dust conversion.
- No automatic Earn movement.
- No mutation of `trade_operations`, `position_lots`, `lot_closures`, or `portfolio`.
- Ignored/reviewed dashboard state may suppress Telegram paging only; it must
  not suppress persistence or mutate accounting state.
- Dust detection failure should be logged but should not crash a healthy trading cycle.

---

## 19. `dust_detections` Table Contract (Wave 2)

Table owned by the bot:

```text
bot.dust_detections
```

Fields:

- `id` primary key
- `run_id` nullable cycle id
- `detected_at` timestamp used by dashboard ordering
- `event_type` required detection path:
  - `dust_candidate_detected`
  - `lot_below_min_notional_detected`
  - `balance_without_lot_coverage_detected`
  - `lot_balance_drift_detected`
  - `sell_residual_detected`
- `severity`
- `asset`
- `symbol`
- `spot_quantity NUMERIC(38, 18)`
- `open_lot_quantity NUMERIC(38, 18)`
- `quantity_delta NUMERIC(38, 18)`
- `price_usdt NUMERIC(38, 18)`
- `estimated_value_usdt NUMERIC(38, 18)`
- `estimated_delta_value_usdt NUMERIC(38, 18)`
- `reason`
- `suggested_action`
- `source`
- `payload JSONB`
- `created_at`

Indexes:

- `detected_at`
- `asset`
- `symbol`
- `severity`
- `reason`
- `run_id`
- `event_type`

Important:

- Numeric fields are Decimal-safe `NUMERIC`, not floats.
- Same asset/symbol may legitimately produce multiple rows in one run only when `event_type` distinguishes the detection path.
- `payload` is detail/context for dashboards and manual review. It is not an instruction to correct accounting state.

## 19.1 `dust_signal_reviews` Table Contract

Table shared with the dashboard:

```text
bot.dust_signal_reviews
```

Purpose:

- Store operator review state for grouped dust/drift signals.
- Let the bot skip Telegram paging for signals already marked ignored,
  reviewed, or suppressed.
- Preserve `bot.dust_detections` as the complete observation/history table.

Current matching signature:

- `event_type`
- `symbol`
- `asset`
- `reason`
- `severity`

Important:

- Review state is alert-only operational state.
- Review state is not an accounting correction.
- Review state does not mutate `bot.position_lots`, `bot.portfolio`,
  `bot.trade_operations`, `bot.trade_fills`, `bot.lot_closures`, Binance
  balances, or `bot.manual_corrections`.
- Matching detections must continue to be inserted into `bot.dust_detections`
  every cycle.
- The current table has no quantity signature field. Future quantity-aware
  review matching would require an explicit schema/contract update.

Dashboard usage after Wave 2:

- Show latest dust detections.
- Group by symbol/asset.
- Surface warning/critical detections first.
- Do not treat summed dust values as audited financial PnL.
- Use `bot.dust_signal_reviews` only for operator review and alert
  suppression state; do not treat it as detection history or accounting state.

Validation SQL:

```sql
-- Latest dust detections
select
    detected_at,
    run_id,
    event_type,
    severity,
    symbol,
    asset,
    reason,
    spot_quantity,
    open_lot_quantity,
    quantity_delta,
    estimated_value_usdt,
    estimated_delta_value_usdt,
    suggested_action
from bot.dust_detections
order by detected_at desc, id desc
limit 50;

-- Grouped detections by symbol/reason
select
    symbol,
    reason,
    event_type,
    severity,
    count(*) as detections,
    max(detected_at) as latest_detected_at
from bot.dust_detections
group by symbol, reason, event_type, severity
order by latest_detected_at desc;

-- High severity / operationally important detections
select *
from bot.dust_detections
where severity in ('warning', 'critical')
order by detected_at desc, id desc
limit 100;

-- Latest run_id detections
with latest_run as (
    select run_id
    from bot.dust_detections
    where run_id is not null
    order by detected_at desc, id desc
    limit 1
)
select d.*
from bot.dust_detections d
join latest_run r on r.run_id = d.run_id
order by d.detected_at desc, d.id desc;
```

---

## 20. `manual_corrections` Table Contract (Wave 4)

Table owned by the bot:

```text
bot.manual_corrections
```

Purpose:

- Explicit, reviewed correction requests for dust/drift/external operations.
- Audit state for manual backend correction application.
- Safe dashboard-to-bot workflow without direct dashboard writes to accounting tables.

Allowed statuses:

- `PENDING`
- `APPLIED`
- `REJECTED`
- `FAILED`

Bot service-level apply handling is idempotent for already `APPLIED`
corrections: it returns the stored correction without creating new accounting
records. CLI apply still operates on `PENDING` corrections and requires
explicit confirmation for persistence.

Allowed correction types:

- `CLOSE_LOTS_EXTERNAL_SELL`
- `REDUCE_LOTS_EXTERNAL_MOVEMENT`
- `CREATE_EXTERNAL_LOT`
- `MARK_DUST_IGNORED`

Implemented applied types:

- `CLOSE_LOTS_EXTERNAL_SELL`
- `CREATE_EXTERNAL_LOT`

Semantics for `CLOSE_LOTS_EXTERNAL_SELL`:

- Used when `bot.position_lots.quantity_open` is greater than actual Binance SPOT balance because of a manual sell, convert, or external action.
- Requires positive Decimal `quantity`.
- Requires positive Decimal `price_usdt`; the backend does not fetch a price.
- Creation is rejected by the bot-owned correction workflow when an equivalent
  `PENDING` or `APPLIED` correction already exists.
- Closes open lots FIFO by `opened_at`, then `lot_id`.
- Writes `bot.lot_closures.quantity_closed`, `entry_price`, `exit_price`, `realized_pnl`, and `trade_operation_id`.
- Creates a clearly marked `bot.trade_operations` row with `side = 'SELL'`, `status = 'FILLED'`, `order_id = null`, and manual correction metadata in `client_order_id`, `run_id`, and `raw_payload`.
- Creates a synthetic `bot.trade_fills` row with `source = 'MANUAL_CORRECTION'` so existing `lot_closures.sell_fill_id` constraints are satisfied.
- Because there is no Binance order, `trade_fills.order_id` is `null`; the manual audit token is stored in fill metadata.
- Does not call Binance and does not execute a market order.
- Does not run during normal bot cycles.

Partial residual semantics:

- The requested `quantity` may be smaller than the oldest open lot quantity.
- The bot closes only the confirmed reviewed delta.
- This is valid for fee-induced residual drift, such as fees paid in the base
  asset that make Binance SPOT slightly smaller than FIFO inventory.
- For accounting-only residual reconciliation, `price_usdt` may intentionally
  be chosen so the correction does not invent trading PnL. Dashboards should
  display these rows as manual accounting corrections, not Binance-executed
  market sells.

Semantics for `CREATE_EXTERNAL_LOT`:

- Used when Binance SPOT balance is greater than open bot lots and the
  operator confirms the external/manual/Earn-return balance should become
  bot-managed tradable inventory.
- Requires positive Decimal `quantity`.
- Requires positive Decimal `price_usdt`; the backend does not fetch a price.
- Creation is rejected by the bot-owned correction workflow when an equivalent
  `PENDING` or `APPLIED` correction already exists.
- Creates a clearly marked `bot.trade_operations` row with `side = 'BUY'`,
  `status = 'FILLED'`, `order_id = null`, and manual correction metadata in
  `client_order_id`, `run_id`, and `raw_payload`.
- Creates a synthetic `bot.trade_fills` row with
  `source = 'MANUAL_CORRECTION'` and `event_type = 'BUY_FILL'`.
- Creates one `bot.position_lots` row with `status = 'OPEN'`,
  `quantity_original = quantity`, `quantity_open = quantity`, and
  `source = 'MANUAL_CORRECTION'`.
- Refreshes `bot.portfolio` as a projection from open lots.
- Does not create `bot.lot_closures` because the correction increases manual
  inventory instead of closing a sell.
- Does not call Binance and does not execute a market order.
- Does not run during normal bot cycles.

Operational drift directions:

- Binance SPOT greater than open lots is reconciled through reviewed
  `CREATE_EXTERNAL_LOT`.
- Open lots greater than Binance SPOT is reconciled through reviewed
  `CLOSE_LOTS_EXTERNAL_SELL`.
- Detection, review, request creation, dry-run preview, and confirmed apply
  remain separate steps. The dashboard may surface and request; the bot applies
  and owns all accounting mutations.

Duplicate prevention contract:

- Matching is owned by the bot code, not by dashboard logic.
- Blocking statuses are `PENDING` and `APPLIED`.
- `REJECTED` rows do not block creation because they represent an explicit
  operator decision not to proceed.
- `FAILED` rows do not block creation so an operator can review the failure and
  create a new explicit request.
- Matching compares `correction_type`, `symbol`, quantity with Decimal-safe
  tolerance, and `source_detection_id` when both compared rows have a non-null
  value.
- The current schema does not add a partial unique index for this rule because
  tolerance-based quantity matching and optional source detection semantics are
  application-level checks; a DB constraint could block legitimate future
  corrections accidentally.

Fields:

- `id BIGSERIAL PRIMARY KEY`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `applied_at TIMESTAMPTZ NULL`
- `status TEXT NOT NULL`
- `correction_type TEXT NOT NULL`
- `symbol TEXT NOT NULL`
- `asset TEXT NOT NULL`
- `quantity NUMERIC(38, 18) NULL`
- `price_usdt NUMERIC(38, 18) NULL`
- `estimated_value_usdt NUMERIC(38, 18) NULL`
- `reason TEXT NOT NULL`
- `requested_by TEXT NULL`
- `reviewed_by TEXT NULL`
- `review_note TEXT NULL`
- `source_detection_id BIGINT NULL REFERENCES bot.dust_detections(id)`
- `payload JSONB NOT NULL DEFAULT '{}'::jsonb`
- `error_message TEXT NULL`

Dashboard-created request payloads should preserve provenance where available:

- `payload.source = django_dashboard`
- source querystring/context from the reviewed detection page
- `source_detection_id` when the request was created from `bot.dust_detections`
- operator-entered review note or reason text

Indexes:

- `status`
- `correction_type`
- `symbol`
- `asset`
- `created_at DESC`
- `source_detection_id`

Important dashboard rule:

The dashboard may insert/request or review rows through this workflow only. It must not directly mutate:

- `bot.position_lots`
- `bot.trade_operations`
- `bot.trade_fills`
- `bot.lot_closures`
- `bot.portfolio`

Dashboard may request/create `PENDING` `CREATE_EXTERNAL_LOT` corrections after
operator review, but it must not apply them or directly mutate accounting
tables. Apply remains bot-owned through the manual correction service/CLI.

Actual schema constraints confirmed for Phase 1:

- `bot.position_lots.status`: `OPEN`, `CLOSED`
- `bot.trade_operations.side`: `BUY`, `SELL`
- `bot.trade_operations.status`: no current DB enum/check; the manual correction backend uses `FILLED`

Validation SQL:

```sql
-- Pending corrections for review/application
select *
from bot.manual_corrections
where status = 'PENDING'
order by created_at asc, id asc;

-- Recently applied corrections with linked operation metadata
select
    mc.id as correction_id,
    mc.applied_at,
    mc.correction_type,
    mc.symbol,
    mc.asset,
    mc.quantity,
    mc.price_usdt,
    op.id as trade_operation_id,
    op.side,
    op.status,
    op.client_order_id,
    op.raw_payload
from bot.manual_corrections mc
left join bot.trade_operations op
    on op.raw_payload->>'correction_id' = mc.id::text
where mc.status = 'APPLIED'
order by mc.applied_at desc, mc.id desc
limit 50;
```

---

## 21. Dashboard Integration Contract

The Django dashboard and bot are separate projects. They only share the database.

Recommended dashboard model policy:

- Use `managed = False` for bot-owned tables.
- Do not create dashboard migrations for bot-owned tables.
- Treat `portfolio` as projection only.
- Treat `position_lots` as accounting truth.
- Never calculate SELL coverage from `portfolio`.

Dashboard may read bot-owned tables and may create `PENDING` manual correction requests in `bot.manual_corrections` only if the operator is authorized.

Dashboard must not:

- call Binance
- execute trading logic
- apply manual corrections
- mutate accounting tables directly
- treat dust sums as audited PnL

Dashboard operator guidance should classify signals conservatively. Unknown/unclassified signals should require review rather than defaulting to low priority.

---

## 22. Notification / API Contract

No bot-to-dashboard API is required for current alerting needs.

Current alerting flow:

```text
Bot detects event
→ Bot writes DB
→ Bot sends Telegram alert directly when ALERTS_ENABLED=true
→ Dashboard remains read/review UI
```

The bot should own critical notifications because it is the component detecting live trading/accounting events.

Wave 5 phase 1 data contract impact:

- No new database tables were added.
- No existing table columns, status values, quantity semantics, or dashboard write permissions changed.
- `bot.dust_detections` and `bot.manual_corrections` remain the dashboard-facing review/history surfaces.
- Telegram alert dispatch is runtime behavior only and is not a shared database contract.
- Dashboard interpretation is unchanged; dashboards should continue to read DB state and must not proxy bot notifications.
- Dust/drift Telegram alert suppression does not hide, delete, collapse, or mark
  `bot.dust_detections` rows. Repeated detections remain visible to database
  consumers.
- Suppression is not an accounting correction. It does not mutate lots,
  portfolio, Binance balances, manual correction state, or dashboard review
  state.

Current bot-owned alert events:

- manual correction created/applied/failed
- `possible_incomplete_sell`
- lot balance drift warning/critical
- dust detection events with critical severity
- safe bot-cycle unhandled failure catch points
- external bot watchdog stale/unknown alerts, based on the latest
  `bot.bot_healthcheck` heartbeat

Current runtime alert config:

- `ALERTS_ENABLED=false`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ALERTS_MIN_SEVERITY=warning`
- `ALERTS_RATE_LIMIT_SECONDS=300`
- `BOT_STALE_THRESHOLD_MINUTES=15`
- `BOT_WATCHDOG_ALERT_COOLDOWN_MINUTES=60`

Dust/drift runtime dedupe behavior:

- Repeated known dust/drift alerts are suppressed inside
  `ALERTS_RATE_LIMIT_SECONDS` when event type, symbol, asset, reason, severity,
  and normalized material quantity/value are unchanged.
- Material changes can alert again, including severity increases, reason
  changes, event type changes, symbol/asset changes, quantity delta changes, or
  estimated USDT value changes.
- The cooldown is in memory and follows `NotificationService` runtime lifetime;
  it is not persisted in the shared database.

Dashboard review suppression behavior:

- The bot reads `bot.dust_signal_reviews` before sending eligible dust/drift
  Telegram alerts.
- Statuses `ignored`, `reviewed`, and `suppressed` suppress matching Telegram
  paging.
- The lookup is read-only and alert-only. It does not suppress
  `bot.dust_detections` inserts, dashboard history, manual corrections, or any
  accounting table.
- Severity is part of the current match, so a warning-level review does not
  automatically suppress a critical signal unless a matching critical review
  row exists.

A new API should be considered only if there is a real product requirement such as:

- multiple external consumers
- mobile app with richer UX
- stronger service boundary requirements
- need to hide database access from all consumers
- multi-user SaaS behavior

For personal iPhone push, Telegram alerts from the bot are simpler and safer than introducing a dashboard API. Pushover remains a future optional target and is not part of the current shared DB contract.

---

## 23. Operational Validation Notes

An AVNTUSDT residual/drift case validated the current shared workflow without
requiring schema changes:

- `bot.dust_detections` remains the detection/history surface.
- `bot.manual_corrections` remains the explicit request/outcome surface.
- `CLOSE_LOTS_EXTERNAL_SELL` remains the only implemented apply path.
- Telegram alerting is runtime behavior and does not change dashboard table
  interpretation.
- Manual corrections remain accounting-only and must not be treated as Binance
  orders.
- `CREATE_EXTERNAL_LOT` is now an implemented accounting-only apply path for
  confirmed external inventory increases. It creates manual BUY/FILLED audit
  records and an OPEN lot, with no Binance order and no lot closures.

An ASIACOIN / `币安人生USDT` dust-closure case on 2026-05-08 validated the same
contract without schema changes. A Binance Small Amount Exchange removed the
remaining SPOT balance while one FIFO lot stayed open; the dashboard inserted a
`PENDING` manual correction request; the bot CLI applied
`CLOSE_LOTS_EXTERNAL_SELL`; and the resulting manual trade operation, synthetic
fill, lot closure, and corrected lot state remained in bot-owned audit tables.
The request preserved dashboard provenance, requester identity, symbol, asset,
quantity, price, reason, `source_detection_id`, and querystring context.

Future changes to duplicate-correction matching or pending-correction linking
may affect dashboard behavior. If implemented through new constraints, fields,
statuses, or query semantics, this contract must be updated in the same task.
