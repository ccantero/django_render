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
- Drift alerts between `bot.portfolio` and `bot.position_lots`
- Compact homepage Active Operational Issues from unresolved critical/warning dust/drift signals only, plus informational residual counts
- Dust / residual dashboard from `bot.dust_detections`
- Read-only Telegram mobile diagnostics commands for bot health, BUY capacity status, positions, latest SELL diagnostics, and why-not-sell explanations
- Read-only “Why positions are not selling” dashboard table sourced from open `bot.position_lots` and latest `bot.sell_decision_events`
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
- Normalized fee totals use `bot.trade_operations.fee_amount_in_quote` for FILLED USDT-quote operations; fees that cannot be normalized to USDT are excluded.
- PnL by day uses linked trade operation timestamps (`executed_at` then `created_at`), not a timestamp on `lot_closures`.
- SELL coverage must never be inferred from `portfolio`.
- Position exit status must be observational only: use `position_lots` for open inventory, `portfolio` only for display values, and persisted SELL diagnostics only for explanations.
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
read shared bot tables. Supported commands are `/health`, `/buy_status`,
`/position SYMBOL`, `/last_sell SYMBOL`, and `/why_not_sell SYMBOL`.

Run tests:

```bash
python manage.py test core
pytest
```

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
