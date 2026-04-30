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

## 3.6 `healthcheck`

Operational health status written by the bot.

Dashboard usage:

- Last bot heartbeat
- Last cycle status
- Error status if available
- Running / stale / unknown indicators

Conceptual fields:

- status
- last cycle timestamp
- last successful cycle timestamp
- last error
- updated timestamp
- run id if available

Suggested dashboard status logic:

```text
Healthy: recent healthcheck and status OK
Stale: last healthcheck older than threshold
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

## 3.8 Optional `bot_control`

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

Every filled SELL operation should have matching `lot_closures` rows.

```text
SELL executed quantity ≈ SUM(lot_closures.closed_quantity)
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
from bot.healthcheck
order by updated_at desc
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

## 7.5 Operational Alerts

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

---

## 8. Dust / Small Residual Handling

Dust means small residual quantities or values that may be below Binance minimum notional / lot-size requirements.

Dashboard should detect and show dust candidates.

Do not auto-convert, auto-sell, or move to Earn from the dashboard unless a separate explicit and audited workflow is implemented.

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
7. Existing Stop / Resume UI wired only if a safe backend exists

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

## 18. DustDetectionService Log Contract (Wave 1)

`DustDetectionService` currently emits structured logs only. It does not write a dedicated dust table yet.

Wave 1 events may include:

- `dust_detection_started`
- `dust_candidate_detected`
- `lot_below_min_notional_detected`
- `balance_without_lot_coverage_detected`
- `lot_balance_drift_detected`
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
- Do not call Binance for prices in Wave 1.
- Missing prices are allowed.
- If price is missing, `estimated_value_usdt` should be `null` / `None`.
- Valuation is approximate and intended for prioritization, not final accounting.

Wave 1 constraints:

- No DB writes for dust detections.
- No automatic selling.
- No automatic Binance dust conversion.
- No automatic Earn movement.
- No mutation of `trade_operations`, `position_lots`, `lot_closures`, or `portfolio`.
- Dust detection failure should be logged but should not crash a healthy trading cycle.

---

## 19. Future `dust_detections` Table Contract (Wave 2 Proposal)

Recommended future table owned by the bot:

```text
bot.dust_detections
```

Suggested conceptual fields:

- id
- run_id
- detected_at
- event_type
- severity
- asset
- symbol
- spot_quantity
- open_lot_quantity
- quantity_delta
- price_usdt
- estimated_value_usdt
- estimated_delta_value_usdt
- reason
- suggested_action
- source
- reviewed_at
- reviewed_by
- review_note
- payload/json details

Dashboard usage after Wave 2:

- Show latest dust detections.
- Group by symbol/asset.
- Surface warning/critical detections first.
- Do not treat summed dust values as audited financial PnL.
- Allow manual review state only if the table explicitly supports it.
