---
doc_id: design
doc_version: 1.1.0
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-05-21
source_repo: django_render
---

# Django Dashboard — Design Notes

## Design Principle

The dashboard is an operator console, not a trading engine.

It should make the system observable, understandable, and auditable without hiding uncertainty or mutating accounting state directly.

The system should favor observability, schema transparency, reproducible
diagnostics, and explicit version visibility over implicit operator knowledge.

Operators and AI tooling should be able to determine runtime version, schema
version, documentation freshness, contract freshness, and projection freshness
without manually inspecting repository history.

---

## UX Goals

- Show the current bot status quickly.
- Surface operational risks before financial KPIs.
- Make dust/drift signals understandable to a human operator.
- Prevent accidental direct DB corrections.
- Guide users toward the manual correction workflow.
- Keep all correction requests explicit and auditable.

---

## Dashboard Sections

Dashboard operator pages are implemented in the `dashboard` Django app.

### Main dashboard

Home dashboard responsibility: concise operator console for health, urgent action, reconciliation, performance, and latest activity.

- Compact Bot Health card with normalized health badge, status, heartbeat age, read-only state, and latest message
- Compact Inventory Integrity card with material positions, portfolio-vs-lots drift, reconciliation status, and muted tolerance/missing-price details
- Compact Analytics card that links to deferred KPI detail instead of computing full-history metrics on the homepage
- Detailed PnL-by-symbol and PnL-by-day history is intentionally deferred to Analytics rather than built for the homepage
- Compact latest operations table, capped at four rows
- Compact Active Operational Issues dust summary with at most five unresolved critical/warning signals
- Informational Residuals summary with count, approximate exposure, and latest detection timestamp; info-only residuals are not promoted to active issues
- Lightweight open FIFO lot exit-status section that links to the full Exit Status page without loading SELL diagnostics by default. Stablecoin cash balances and pure SPOT/projection balances without open lots are explicitly outside this SELL-candidate view.
- Compact BUY / Cooldown card from latest healthcheck details and compact churn summary counts from read-only recent operation history
- Link to the full Dust / Residuals dashboard
- Link to Analytics

### Analytics dashboard

Analytics dashboard responsibility: Performance analysis: KPIs, fees, PnL breakdowns, historical tables.
Analytics read-model output may be cached briefly because the page is read-only and historical aggregates are intentionally deferred away from the homepage.

- Performance KPI cards:
  - net realized PnL
  - total fees USDT
  - win rate
  - average win and average loss
  - profit factor
  - gross deployed capital
  - manual/accounting adjustment PnL
- Fees USDT summary
- Fees by asset
- PnL by symbol
- PnL by day

### Operational Trading KPIs v2

- `/dashboard/operational-kpis/` is a compact read-only analysis page for strategy-version summaries, hold-time analytics, same-symbol SELL→BUY churn, and fee efficiency.
- Filters: date range, strategy version, symbol, and churn threshold minutes.
- Historical rows without `strategy_version` are shown as `unversioned`.
- Manual/accounting-only corrections are excluded from trading-quality metrics when the operation payload identifies them.
- Strategy-level churn frequency uses same-symbol reentries divided by eligible FILLED SELLs, matching the churn table denominator; ratio values are labeled as percentages in the UI.

### Future Capital and Exit Observability

- Trapped-capital and capital-days concepts should help operators identify
  inventory that consumes opportunity or stays open longer than intended.
- Holding-efficiency views should stay operational and comparative, not audited
  accounting statements.
- Time-based exit dry-run visibility should show what the bot would have done
  under stable strategy rules without executing trades from Django.
- These views should consume bot-owned reports or shared-contract fields and
  avoid deriving new truth from portfolio projections alone.

### Exit Status and Churn / Cooldown

- `/dashboard/exit-status/` carries bounded recent SELL diagnostics for
  open-lot symbols while the homepage stays compact; missing diagnostics should
  degrade to `Review`, and a failed diagnostics read should render
  `Diagnostics unavailable`.
- `/dashboard/churn/` carries recent read-only SELL→BUY re-entry gaps, under
  15-minute counts, and linked preceding SELL realized PnL when available.
- Cooldown copy should name loss/stop-loss, take-profit, and recent-sell
  re-entry blocks in human language; absent optional detail keys must not hide
  the stable reason.

### Public and auth pages

- Home page at `/`
- Login and logout pages
- Public demo dashboard at `/dashboard/demo/`
- Public app liveness endpoint at `/health/`
- About-me page at `/me`
- Thanks page at `/thanks/`

### Dust / Residuals

Source: `bot.dust_detections`

Shows:

- grouped detections
- 25-row pagination
- symbol, severity, reason, event type, and review filters
- severity
- reason
- event type
- latest run id
- approximate exposure
- estimated delta
- suggested action
- review status
- operator guidance
- linked correction status

### Dust detail

Shows latest grouped signal details:

- spot quantity
- open lot quantity
- quantity delta
- price USDT
- estimated values
- payload
- run id
- manual review actions
- correction status for the latest detection and raw detections

### Manual corrections

Source: `bot.manual_corrections`

Shows:

- pending/applied/rejected/failed correction requests
- correction detail
- request metadata
- error message if failed
- payload

### Telegram mobile diagnostics

Source: shared bot tables only.

The existing Telegram webhook supports concise, allowlisted, read-only operator
commands:

- `/help`
- `/health`
- `/buy_status`
- `/position SYMBOL`
- `/last_sell SYMBOL`
- `/why_not_sell SYMBOL`

Messages use Telegram HTML parse mode, escape dynamic values before rendering,
and should stay compact enough for mobile review. `/help` should act as a compact
operator guide, and skipped/rejected SELL diagnostics should lead with a plain
language interpretation and suggested action before lower-level event fields.
Dust/drift alerts should use human labels, expose raw reason/event identifiers in
details, and explicitly call out tiny dust values below `0.01 USDT` without
making them look like large incidents. `/buy_status` is conservative
about exposure rather than pessimistic about missing optional fields: effective
positions are `material + unknown`, dust is explicitly non-blocking, missing free
USDT renders as `diagnostic unavailable`, and a missing latest BUY reason renders
as `unavailable` without blocking capacity. Its mobile summary separates
Capacity, Positions, Material exposure, Dust exposure, Latest BUY, and Status;
sorts material exposure by approximate USDT value; caps material rows at eight;
lists dust symbols only when there are five or fewer; and keeps missing or
non-positive projection prices visibly unavailable rather than silently turning
them into zero. Capacity and latest BUY blockers remain separate so “slots
available” can coexist with “insufficient free USDT.” It uses
`diagnostic_unavailable` only when required inputs such as position
classification or max-position config cannot be read. Inline keyboard buttons,
if added later, must be navigation or refresh controls only and must never
trigger trading.

When the latest bot healthcheck carries persisted reconciliation
`inventory_warnings`, `/buy_status` may add a compact operator-facing section
for `WARNING`/`CRITICAL` items only. The section should be capped for mobile
readability, humanize known reasons, and use the bot-provided notional or
valuation state rather than rebuilding diagnostics inside Django. The BUY /
Cooldown card may show only the compact warning count so the homepage remains
lightweight.

Inventory warning UX should distinguish accounting drift, stale projection,
dust-only residuals, and material inventory mismatches. When bot payloads expose
enough source metadata, Django and Telegram should show compact hints such as
lots/Spot reconciled, portfolio projection may be stale, or inventory warning
count, without turning those hints into dashboard-side correction logic.

### Daily Trading Audit

If Django later exposes Daily Trading Audit output, it should be designed as a
review page rather than a second accounting engine. The page should present the
bot-produced summary in operator terms such as actions, non-actions,
starting/ending USDT, realized PnL and fees, churn/re-entry candidates, and
inventory warnings.

---

## Operator Guidance

Guidance should favor safety:

- Never classify unknown signals as safe.
- Use “Unclassified signal / needs review” as fallback.
- Use approximate values only for prioritization.
- Display “Do not correct from DB directly. Use manual correction workflow.”
- For inventory mismatch work, direct operators to the bot-side analyzer,
  manual correction CLI, and portfolio sync script rather than adding Django
  mutation tools.

Recommended labels:

- Below min notional
- Lots > Binance
- Binance > Lots
- Possible incomplete sell
- Unclassified signal

Position exit status should map known persisted SELL reasons conservatively:

- `stop_loss_not_reached` / `take_profit_not_reached` -> `Holding`
- `rounded_quantity_zero` -> `Dust / Unsellable`
- `quantity_below_min_notional` -> `Dust / Below minNotional`
- `quantity_below_min_qty` -> `Dust / Below minQty`
- `insufficient_binance_balance` -> `Drift / Review needed`
- `no_open_lots` -> `No accounting inventory`
- `exchange_filter_missing` -> `Metadata issue`
- `read_only` -> `Read-only`
- positive-PnL `stop_loss_reached` -> `Anomaly`

Mapped reasons should show a human interpretation and suggested next step.
Unmapped non-empty reasons fall back to `Review`, never `Unknown`.

---

## Manual Correction Request Design

The dashboard form creates only a request.

It must show a safety confirmation:

- This does not execute Binance orders.
- This does not convert dust.
- This is an accounting correction request.
- Bot-owned service/CLI must apply it.

When a dust detection is linked to a `PENDING` or `APPLIED` correction through `source_detection_id`, the dashboard should disable the create action and show a clear message. This is only click-prevention UX; bot-side duplicate prevention remains the source of truth.

For `CLOSE_LOTS_EXTERNAL_SELL`, prefill quantity only when safe:

```text
quantity = open_lot_quantity - spot_quantity
only when open_lot_quantity > spot_quantity
```

Never prefill a negative quantity.

Validated operator case:

- For a reviewed external/manual balance loss where `spot_quantity = 0` and `open_lot_quantity > 0`, the expected request is usually `CLOSE_LOTS_EXTERNAL_SELL`.
- The request should keep `status = PENDING`, a positive quantity, reviewed price, reason, requester identity, `source_detection_id` when available, and dashboard provenance in payload.
- Labels should make Binance Small Amount Exchange / manual dust conversion understandable to operators when the raw detection reason is broader, such as `earn_or_external_transfer`.
- Historical detections should stay visible as audit history after correction, but current views should avoid making old rows look newly unresolved.
- Review/ignore/external-or-Earn state suppresses Telegram paging only; it does not delete persisted detections or mutate accounting state.

---

## Decimal and Formatting Rules

- Treat financial values as Decimal.
- Round only for display.
- Count and warn on missing prices instead of silently treating them as zero.
- Do not write rounded display values back to DB.
- Do not recalculate trading PnL in the dashboard unless the contract defines the source fields.
- Wave 8 Phase 1 performance KPIs use `lot_closures.realized_pnl` and `trade_operations.fee_amount_in_quote`.
- Operational Trading KPIs v2 use the same Decimal-safe fee source, ignore missing timestamps for hold/churn metrics, and only show fee ratios when the denominator is positive.
- PnL by day uses the linked trade operation `executed_at` timestamp, falling back to `created_at`; closures without a linked operation timestamp are excluded only from the day table.
- Show profit factor as N/A when gross loss is zero.
- Label gross deployed capital as approximate because it is based on FILLED BUY quote value, not audited capital efficiency.

---

## Notifications

Notifications should be produced by the bot directly. The dashboard should display alert state but should not be a required relay for critical events.

Preferred:

```text
Bot -> Telegram/Pushover
Dashboard -> review UI
```

## API / Admin Behavior

- Currency and exchange-rate resources expose read access to unauthenticated users and write access to authenticated users through DRF permissions.
- Profile API uses token authentication and an own-profile update permission.
- Django admin is enabled at `/admin/` for registered models.
- API schema and Swagger UI are available through drf-spectacular.
