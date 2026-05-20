# Binance Bot Django Dashboard

Django dashboard for observing and operating the Binance Python Bot through a shared database contract.

The dashboard is a **consumer/operator UI**. It must not execute trading logic, call Binance for trading decisions, or mutate bot-owned accounting tables directly.

---

## Current Scope

- Authenticated dashboard overview
- Compact operator console homepage with Bot Health, Inventory Integrity, and Performance Snapshot cards
- Valuation consistency between `bot.portfolio` projection value and open `bot.position_lots` accounting value
- Recent operations/latest trade, capped to the latest four operations on the homepage
- Fees by asset
- Wave 8 Phase 1 read-only performance KPI dashboard:
  - net realized PnL after normalized USDT fees
  - total fees USDT
  - win rate, average win/loss, and profit factor
  - gross deployed capital approximation
  - PnL by symbol and day
- Read-only Operational Trading KPIs v2 page:
  - strategy-version summary, including historical `unversioned` rows
  - hold-time analytics and buckets
  - same-symbol SELL→BUY churn metrics with configurable threshold
  - fee-efficiency metrics using normalized quote fees only
- Drift alerts between `bot.portfolio` and `bot.position_lots`
- Compact homepage Active Operational Issues from unresolved critical/warning dust/drift signals only, plus informational residual counts
- Dust / residual dashboard from `bot.dust_detections`
- Read-only Telegram mobile diagnostics commands for command discovery, bot health, BUY capacity status, positions, latest SELL diagnostics, and why-not-sell explanations
- Read-only “Why positions are not selling” visibility through `/dashboard/exit-status/`; the homepage stays lightweight and links there instead of loading SELL diagnostics by default
- Read-only `/dashboard/churn/` page for recent SELL→BUY re-entry observability and homepage churn summary counts
- Dust signal detail page
- Dust detections show linked manual correction status by `source_detection_id`
- Manual review actions:
  - mark ignored
  - review later
- Manual correction request workflow through `bot.manual_corrections`
- Manual correction list/detail views
- Staff-only correction request creation
- Public app liveness endpoint at `/health/` for Render keepalive/cron pings

---

## Architecture Position

```text
Binance Bot project
  owns trading logic
  owns bot.* accounting tables
  writes health, trades, lots, dust detections, manual correction status

Django Dashboard project
  reads bot.* tables
  displays operational state
  creates PENDING manual correction requests only
  never applies corrections directly
```

The dashboard and bot are separate projects and share only the database.

---

## Critical Rules

- `position_lots` is the accounting source of truth.
- `portfolio` is a projection/read layer.
- Performance KPIs are operational visibility, not audited accounting statements.
- Operational Trading KPIs v2 are operational analytics, not audited accounting statements; identifiable manual/accounting-only corrections are excluded from trading-quality metrics.
- Normalized fee totals use `bot.trade_operations.fee_amount_in_quote` for FILLED USDT-quote operations; fees that cannot be normalized to USDT are excluded.
- PnL by day uses linked trade operation timestamps (`executed_at` then `created_at`), not a timestamp on `lot_closures`.
- SELL coverage must never be inferred from `portfolio`.
- Position exit status must be observational only: use `position_lots` for open inventory, `portfolio` only for display values, and persisted SELL diagnostics only for explanations.
- Position exit status distinguishes strategy holds, dust/min-filter blockers, drift, metadata issues, read-only mode, and anomalous diagnostics; known reasons must render an interpretation and suggested next step rather than “Unknown.”
- BUY cooldown visibility reads only latest `bot.bot_healthcheck.details`; supported cooldown reasons are `loss_reentry_cooldown_active`, `take_profit_reentry_cooldown_active`, and `sell_reentry_cooldown_active`.
- The dashboard must not directly update:
  - `bot.position_lots`
  - `bot.trade_operations`
  - `bot.trade_fills`
  - `bot.lot_closures`
  - `bot.portfolio`
- The dashboard may create `PENDING` rows in `bot.manual_corrections` only through the explicit review workflow.
- The bot-side CLI/service applies or rejects corrections.
- The dashboard may hide/disable obvious duplicate correction clicks for detections with linked `PENDING` or `APPLIED` corrections, but bot-side duplicate validation remains authoritative.

---

## Shared Contract

Read `docs/DATA_CONTRACT.md` before changing dashboard models or queries.

Dashboard models for bot-owned tables should use:

```python
class Meta:
    managed = False
```

No Django migrations should be generated for bot-owned tables unless the table is intentionally dashboard-owned.

---

## Manual Correction Workflow

1. Bot detects dust/drift and persists rows to `bot.dust_detections`.
2. Dashboard groups and classifies signals for operator review.
3. Staff user creates a `PENDING` manual correction request.
4. Bot operator applies it from the bot project CLI:

```bash
python src/scripts/manual_correction.py apply --id <id>
python src/scripts/manual_correction.py apply --id <id> --confirm
```

The dashboard does not execute Binance orders and does not apply accounting corrections.

### Inventory Mismatch Runbook

For inventory mismatches, use the bot project tooling before proposing new
dashboard behavior. Django remains a read/review/request UI and must not fix
inventory directly.

Bot-side investigation and remediation scripts:

```bash
python src/scripts/analyze_symbol_inventory_gap.py BTCUSDT
python src/scripts/manual_correction.py create ...
python src/scripts/manual_correction.py apply --id <ID>
python src/scripts/manual_correction.py apply --id <ID> --confirm
PYTHONPATH=src python src/scripts/sync_portfolio_from_api.py
```

Interpretation rules:

- `position_lots` is accounting truth.
- Binance Spot is live operational truth.
- `portfolio` is a projection/read model and may be stale or rebuilt from
  open lots/projection logic.
- If lots and Spot match but `portfolio` differs, treat it as projection/cache
  mismatch evidence, not permission for Django to mutate accounting tables.

### Validated Correction Path

The dashboard request path has been validated for `CLOSE_LOTS_EXTERNAL_SELL`,
including a 2026-05-08 ASIACOIN / `币安人生USDT` dust-closure case where Binance
Small Amount Exchange removed the remaining SPOT balance while a FIFO lot stayed
open. The dashboard created only the `PENDING` request; the bot CLI performed
dry-run review and explicit confirmed application; and the dashboard then read
the corrected state/history.

Confirmed boundary:

```text
Dashboard = read/review/request UI
Bot CLI/service = correction executor
Binance = not called by the correction
```

---

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Development uses Django settings from `django_render/settings.py`. By default, the database falls back to local SQLite at `db.sqlite3`; production-style deployments can provide `DATABASE_URL`.

Required environment variables:

- `CC_DEBUG`
- `SECRET_KEY`
- `TUTORIAL_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_TOKEN`
- `DATABASE_URL` when `CC_DEBUG` is false

Optional Telegram diagnostics allowlist settings:

- `TELEGRAM_ALLOWED_CHAT_IDS`
- `TELEGRAM_ALLOWED_USER_IDS`

The mobile diagnostics commands require the incoming Telegram chat ID or user ID
to match one of those allowlists. The commands use safe HTML formatting and only
read shared bot tables. Supported commands are `/help`, `/health`, `/buy_status`,
`/position SYMBOL`, `/last_sell SYMBOL`, and `/why_not_sell SYMBOL`. `/help`
returns a compact operator guide, and SELL rejection diagnostics present a short
human-readable interpretation and suggested action before lower-level event
details for easier mobile review. Dust/drift alert templates are also kept human
readable: tiny values are labeled as tiny dust, while raw event/reason/stage
fields remain available for debugging.

Reviewing or ignoring a dust signal suppresses repeated paging only. It does not
delete `bot.dust_detections`, change FIFO accounting, or apply a correction.

Example operator-facing alert shapes:

```text
🤔 Why not sell — XRPUSDT
Status: Holding
Reason: stop_loss_not_reached
Interpretation: Stop loss has not been reached...
Suggested action: No action. Continue monitoring.
```

```text
⚠️ Dust / drift detected — XRPUSDT
Status: Warning
Reason: Manual / external operation
Interpretation: tiny dust value...
Suggested action: Review in dashboard...
```

### Troubleshooting `/buy_status`

`/buy_status` treats BUY capacity conservatively without letting optional
diagnostic gaps hide useful information:

- The Telegram message is grouped for mobile review into Capacity, Positions,
  Material exposure, Dust exposure, Latest BUY, and Status sections.
- `Effective positions` means `material + unknown`; unknown-value positions count
  against capacity until the bot can value them.
- Dust positions are shown explicitly as `non-blocking` and do not consume BUY
  capacity.
- Material and dust exposure are approximate display values enriched from
  read-only `bot.portfolio`; `bot.position_lots` remains the accounting source of
  truth.
- Material exposure is sorted by approximate USDT value, capped to eight rows,
  and dust symbols are only listed compactly when there are five or fewer.
- Missing/non-positive projection prices are not treated as zero: the command
  shows valuation as unavailable or partially unavailable instead.
- If persisted healthcheck details do not include `max_positions`, the dashboard
  falls back to runtime config/env aliases such as `MAX_POSITIONS`.
- If free USDT cannot be read, the command shows
  `Free USDT: diagnostic unavailable` while still reporting capacity.
- If the latest BUY reason is absent, the command shows
  `Latest BUY reason: unavailable`; that alone does not block BUY status.
- Active re-entry cooldown reasons render as human-readable blocked states and,
  when present, include latest SELL/cooldown metadata from healthcheck details.
- Persisted reconciliation `inventory_warnings` from the latest healthcheck are
  shown only when they contain `WARNING`/`CRITICAL` diagnostics; `/buy_status`
  does not reconstruct those warnings from accounting tables.

These inventory warnings are intentionally read-only display diagnostics: the
dashboard and Telegram commands render bot-persisted reconciliation output,
avoid rebuilding accounting state, and never call Binance while formatting the
message.

### Daily Trading Audit

Daily Trading Audit is currently a bot-owned reporting surface. Django should
consume or display it only after the bot-side output is stable and documented in
the shared data contract; the dashboard should not become the owner of audit
computation.

Run tests:

```bash
python manage.py test core
pytest
```

Local dashboard profiling is opt-in only:

```bash
DASHBOARD_PROFILE=true python manage.py runserver
DASHBOARD_PROFILE=true DASHBOARD_PROFILE_SQL=true DASHBOARD_SLOW_QUERY_MS=100 python manage.py runserver
```

This logs per-section dashboard timings locally; slow SQL logging is disabled unless explicitly enabled.
The profiler writes directly to the local runserver console when enabled.

The test settings provide safe defaults for required secrets and use SQLite at `/tmp/django_render_test.sqlite3`.

Keepalive endpoint:

```bash
curl https://<your-render-host>/health/
```

The endpoint returns `{"status":"ok"}` when the Django web process is reachable. It does not check bot health or database state.

## Detected Stack

- Django 3.2.25
- Dedicated `dashboard` app for dashboard routes, read models, forms, and templates
- Django REST Framework with token auth
- drf-spectacular OpenAPI schema/docs
- pytest-django and Django `TestCase`/`TransactionTestCase`
- SQLite by default through `dj-database-url`
- PostgreSQL supported through `DATABASE_URL`; Docker Compose defines a PostgreSQL service
- WhiteNoise for static files
- Bootstrap 3 package
- No Celery or Redis integration detected
- No Django management commands detected

## Codex Workflow

All Codex tasks must follow `AGENTS.md`: planner, implementer, tester, documentator. Missing steps are hard failures.

---

## Security Requirements

- Dashboard must require login.
- Manual correction request creation is staff/superuser-only.
- State-changing actions must be POST-only and CSRF-protected.
- Public/demo views must never expose sensitive data.
- Database grants should be reviewed so public roles cannot mutate bot-owned accounting tables.

---

## Notifications

Push notifications should be emitted by the bot directly through a notifier such as Telegram/Pushover, not routed through the dashboard.

Preferred flow:

```text
Bot detects event -> writes DB -> sends alert
Dashboard observes/reviews state
```

Do not introduce an API between bot and dashboard only for iPhone notifications.

## Development Workflow

This repository uses a mandatory Codex governance workflow.

Read:
- AGENTS.md
- .codex/skills/
- .codex/subagents/