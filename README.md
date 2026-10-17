---
doc_id: readme
doc_version: 1.1.21
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-10-17
source_repo: django_render
---

# Binance Bot Django Dashboard

Django dashboard for observing and operating the Binance Python Bot through a shared database contract.

The dashboard is a **consumer/operator UI**. It must not execute trading logic, call Binance for trading decisions, or mutate bot-owned accounting tables directly.

---

## Current Scope

- Authenticated dashboard overview
- Compact operator console homepage with Bot Health, Disk Usage, Inventory Integrity, and Performance Snapshot cards
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
- Read-only Telegram mobile diagnostics commands for command discovery, bot health, Disk Usage, BUY capacity status, portfolio performance, positions, latest SELL diagnostics, and why-not-sell explanations
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
- Dashboard Disk Usage visibility from latest bot healthcheck VPS disk data
- Experimental authenticated, read-only bot diagnostics API for health and persisted ETHUSDT inventory evidence

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
- Planned trapped-capital, holding-efficiency, and dry-run exit diagnostics should consume bot-produced or shared-contract analytics outputs instead of reconstructing accounting truth in Django.
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

## Read-only Bot Diagnostics API (PoC)

The PoC exposes two fixed diagnostics resources to an authenticated operator
client. GET retrieves data; HEAD and OPTIONS are non-mutating; write methods
are rejected:

- `GET /api/bot/health`
- `GET /api/bot/inventory/ETHUSDT`

Configure a dedicated `BOT_DIAGNOSTICS_API_TOKEN` of at least 32 characters in
the deployment environment. It is independent of Django user tokens and is
accepted only by these diagnostics views. Leave it unset to keep the API
closed. Send it as `Authorization: Bearer <token>`; do not put it in source,
chat, shell history, or logs. Responses are `no-store` and expose an
allowlisted set of fields only.

The inventory endpoint reads one `bot.portfolio` row, aggregates positive
`bot.position_lots` rows for ETHUSDT, reads the latest healthcheck, and selects
the latest matching `bot.dust_detections` observation. It returns quantities
and valuations as decimal strings, source timestamps, observation recency,
persisted BUY classification/capacity evidence when present, and explicit
unavailable states. `latest_spot_observation.observed_spot_quantity` is the
quantity recorded by that historical event. `observation_recency: recent`
means only that the event timestamp is recent; `current_exchange_truth` remains
false. It is never a current Binance Spot balance. The bot does not persist a
complete per-asset Spot balance snapshot. Its read-only Binance comparison
script obtains a live balance response and compares it with local lots and
generations without persisting that exchange snapshot. Django never calls
Binance. `bot.portfolio` is a local projection, `bot.position_lots` is FIFO
accounting evidence, and neither is represented as current exchange truth. Lot
freshness stays `unknown` because the Django read model has no lot-update
timestamp. Active generation data stays unavailable because no position
generation model is mapped here.

BUY capacity is bot-produced healthcheck evidence. Fresh values are labeled
`current_as_of_healthcheck`; stale values move under `historical_global` and
`global` becomes null. Partial fresh capacity fields are labeled
`partial_as_of_healthcheck`, with missing individual values left null. Django
does not recalculate capacity from portfolio rows or FIFO lots. A symbol's
`material` classification describes portfolio materiality; it does not prove
that a specific position generation consumes a BUY slot.

The inventory request issues separate bounded reads for healthcheck, Spot event,
portfolio, and FIFO lot aggregates. It is not an atomic cross-source snapshot.
`consistency.atomic` is false and portfolio-versus-lot differences are marked
`not_synchronized`; compare their source timestamps before drawing conclusions.

For local HTTP verification, set a disposable token in the local environment
and start Django:

```bash
export BOT_DIAGNOSTICS_API_TOKEN="$(openssl rand -hex 32)"
python manage.py runserver 127.0.0.1:8000
```

In another terminal, verify anonymous rejection and authenticated reachability:

```bash
curl -i http://127.0.0.1:8000/api/bot/health
curl -i -H "Authorization: Bearer $BOT_DIAGNOSTICS_API_TOKEN" \
  http://127.0.0.1:8000/api/bot/health
curl -i -H "Authorization: Bearer $BOT_DIAGNOSTICS_API_TOKEN" \
  http://127.0.0.1:8000/api/bot/inventory/ETHUSDT
```

Run the focused tests without any bot tables or credentials:

```bash
.venv/bin/pytest dashboard/test_bot_diagnostics_api.py -q
```

The local default SQLite database does not contain bot-owned tables, so an
authenticated request can correctly return `503 evidence_unavailable` there.
Use a disposable PostgreSQL fixture with the required bot tables to inspect a
successful response; do not point this procedure at production. Focused API
tests mock the bot read models and require no production database or Binance
credentials. The API uses four read queries for inventory and one for health;
the lot aggregate returns one row but its work scales with matching lot rows.

Example response fragments below use synthetic fixture data, not the reported
incident or a live exchange reading:

```json
{
  "healthcheck": {
    "source": "bot.bot_healthcheck",
    "status": "ok",
    "observed_at": "2026-10-17T12:00:00+00:00",
    "healthcheck_at": "2026-10-17T11:59:18+00:00",
    "age_seconds": 42,
    "freshness": "fresh"
  }
}
```

When capacity evidence is stale, the response keeps the values explicitly
historical and makes the current-capacity field unavailable:

```json
{
  "capacity_status": "historical",
  "freshness": "stale",
  "global": null,
  "historical_global": {
    "effective_positions_count": 15,
    "max_positions": 15,
    "remaining_buy_capacity": 0
  }
}
```

```json
{
  "symbol": "ETHUSDT",
  "observed_at": "2026-10-17T12:00:00+00:00",
  "portfolio": {
    "source": "bot.portfolio",
    "quantity": "0.25",
    "entry_price": "3000",
    "current_price": "3200",
    "estimated_value_usdt": "800.00",
    "valuation_status": "available",
    "updated_at": "2026-10-17T11:59:10+00:00",
    "freshness": "fresh"
  },
  "open_lots": {
    "source": "bot.position_lots",
    "quantity": "0.25",
    "count": 2,
    "first_opened_at": "2026-10-15T12:00:00+00:00",
    "last_opened_at": "2026-10-16T12:00:00+00:00",
    "freshness": "unknown",
    "freshness_reason": "Open lot rows have no update timestamp in the Django read model."
  },
  "latest_spot_observation": {
    "source": "bot.dust_detections",
    "observed_spot_quantity": "0.000093",
    "quantity_status": "available",
    "open_lot_quantity": "0.25",
    "price_usdt": "2370",
    "estimated_value_usdt": "0.22041",
    "event_type": "lot_balance_drift_detected",
    "reason": "balance differs from open FIFO lots",
    "source_label": "dust_detection_service",
    "detected_at": "2026-10-17T11:57:00+00:00",
    "observation_recency": "recent",
    "current_exchange_truth": false
  },
  "quantity_difference": {
    "portfolio_minus_open_lots": "0.00",
    "status": "available",
    "comparability": "not_synchronized"
  },
  "consistency": {
    "atomic": false,
    "mode": "separate_queries",
    "cross_source_comparisons": "not_synchronized"
  },
  "buy_capacity": {
    "source": "bot.bot_healthcheck.details",
    "freshness": "fresh",
    "capacity_status": "current_as_of_healthcheck",
    "global_status": "available",
    "symbol_classification": "material",
    "global": {
      "positions_count": 15,
      "material_positions_count": 15,
      "dust_positions_count": 0,
      "unknown_value_positions_count": 0,
      "effective_positions_count": 15,
      "max_positions": 15,
      "remaining_buy_capacity": 0
    }
  },
  "active_generation": {
    "available": false,
    "status": "unavailable",
    "reason": "No position generation read model is mapped in this Django application."
  },
  "exchange_spot": {
    "available": false,
    "status": "unavailable",
    "quantity": null,
    "estimated_value_usdt": null,
    "reason": "Django does not call Binance; persisted database evidence is not current exchange truth."
  }
}
```

An authenticated HTTP route alone does not connect ChatGPT Work Cloud to it.
The currently documented candidate is a **custom GPT Action**, which is a
separate ChatGPT surface and does not establish native ChatGPT Work
connectivity. A custom GPT Action needs an OpenAPI schema, API-key auth
configured as Bearer, a cloud-reachable HTTPS Render hostname, the dedicated
API token stored in the Action's secret configuration, and (for applicable
Enterprise/Edu workspaces) the Render domain allowed by workspace policy. Do
not put the token in a prompt. OpenAI's current guide says custom GPT Actions
for affected Enterprise workspaces are scheduled for retirement on
2026-12-11; the replacement path is not verified for this PoC. No Action,
secret delivery, workspace domain permission, or cloud request has been
configured or tested, so ChatGPT Work compatibility remains **UNVERIFIED**.
See [OpenAI's GPT Actions configuration guide](https://help.openai.com/en/articles/9442513-configuring-actions-in-gpts).

Proposed cloud check after an approved non-production endpoint is available:
create a custom GPT Action with the two fixed paths in an OpenAPI schema, use a
short-lived token for a synthetic-data environment, configure Bearer API-key
authentication in the Action secret field, allow the test Render hostname in
workspace policy, then call both operations from Action Preview. Confirm
anonymous/wrong-token calls fail and no credential appears in prompts or logs.
This tests the custom GPT Action path only; native ChatGPT Work connectivity
requires a supported Work integration and remains unverified here.

Production assumes Render's HTTPS termination and Django's production HTTPS
redirect/HSTS settings. Store the dedicated token only in the Render secret
environment and rotate it there. Render provides edge DDoS protection, but
this application has no per-route rate limiter; repeated authentication
failures do not query bot tables, though targeted application-level request
abuse is not ruled out. Before broad public enablement, use a trusted edge
allowlist/rate limit for these fixed paths where available, or add a small
application-level limit without introducing shared infrastructure.

The PoC deliberately excludes Binance API access, arbitrary symbol queries,
database/SQL access, logs, SSH/shell, trading, accounting changes, service
control, and any general-purpose agent or MCP service.

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

### Public Calculadora UVA PWA

The public currency-converter pages provide one installable PWA. The start
page is `/currencyconverter/calculadora_uva/`, and
`/currencyconverter/exchangerates/` shares its scope. The authenticated
`/dashboard/` route remains outside the PWA scope. Its service worker handles
public currency-converter GET requests only and does not cache dashboard data.
The calculator keeps the normal site navigation in regular browsers, while
standalone display mode hides that navigation and uses a single-column,
touch-sized layout with iOS safe-area padding.
The calculator also shows the current official USD and UVA values used for its
calculations in the results panel.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Development uses Django settings from `django_render/settings.py`. By default, the database falls back to local SQLite at `db.sqlite3`; production-style deployments can provide `DATABASE_URL`.
The project targets the Django 5.2 LTS dependency line, which requires Python
3.10 or newer. For Render native Python deployments, keep `.python-version`
committed at the repository root so Render installs a compatible Python runtime
before `pip install -r requirements.txt`. If the Render service has a
`PYTHON_VERSION` environment variable set, it takes precedence over
`.python-version`; remove or update old values such as Python 3.7/3.9 before
redeploying.

Required environment variables:

- `CC_DEBUG`
- `SECRET_KEY`
- `TUTORIAL_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_TOKEN`
- `DATABASE_URL` when `CC_DEBUG` is false

Optional Telegram diagnostics allowlist settings:

- `TELEGRAM_ALLOWED_CHAT_IDS`
- `TELEGRAM_ALLOWED_USER_IDS`

Optional diagnostics API setting:

- `BOT_DIAGNOSTICS_API_TOKEN` — dedicated bearer secret (minimum 32 characters); unset disables the API.

The mobile diagnostics commands require the incoming Telegram chat ID or user ID
to match one of those allowlists. The commands use safe HTML formatting and only
read shared bot tables. Supported commands are `/help`, `/health`, `/buy_status`,
`/portfolio_status`, `/position SYMBOL`, `/last_sell SYMBOL`, `/last_operations [N]`, and
`/why_not_sell SYMBOL`. `/help`
returns a compact operator guide, `/health` includes the same bot-healthcheck
VPS Disk Usage status as the dashboard, and SELL rejection diagnostics present a
short human-readable interpretation and suggested action before lower-level event
details for easier mobile review. Dust/drift alert templates are also kept human
readable: tiny values are labeled as tiny dust, while raw event/reason/stage
fields remain available for debugging.

Webhook resilience and Render deployment:

- `/help` is a static, allowlisted response and remains available when
  diagnostic database reads or Telegram message-audit persistence are unavailable.
- The webhook safely ignores non-text updates and returns a controlled `400`
  for malformed JSON; it never logs secrets or full update payloads.
- Outbound Telegram calls use `TELEGRAM_DELIVERY_TIMEOUT_SECONDS` (default
  `10`) and log safe HTTP/API failure context instead of reporting an
  unconfirmed delivery as successful.
- `PORTFOLIO_STATUS_MAX_SNAPSHOTS` (default `512`) bounds snapshot rows
  materialized for `/portfolio_status` history.
- The tracked `Procfile` uses one Gunicorn worker, two threads, and a
  30-second timeout. Confirm Render uses it before increasing workers on the
  512 MB instance.

`/portfolio_status` is separate from BUY capacity. It uses open
`bot.position_lots` for quantity and cost basis, `bot.portfolio.current_price`
for current projection valuation, latest healthcheck details for free USDT, and
the same UTC-calendar-day realized PnL rule as Analytics. Current open value
and equity include every valued open-lot position, while aggregate unrealized
PnL and best/worst contributors are material-only. Required values become
`unavailable` when required valuation or entry data is missing or older than
the configured healthcheck stale threshold. Historical 24h/7d/30d change uses
only `source = "bot_cycle"` rows with valid
`bot.portfolio_snapshots.notes.portfolio_equity_usdt` values and shows USDT
plus percentage deltas; each missing or incomplete window remains
`unavailable`. `portfolio_sync_from_api`, `open_value_usdt`, and current
`portfolio` projection data are not historical equity fallbacks. When at least
two usable 7-day canonical bot-cycle equity snapshots exist, Telegram receives
an on-demand PNG equity chart generated in memory. If history is not usable,
the command sends text only with a compact chart-unavailable note. No
historical equity is invented. The Telegram text groups those values under
`Performance`: `Portfolio equity` for 24h/7d/30d snapshot windows,
`Today's trading (UTC)` for current UTC closed-trade realization, and
`Open positions` for current unrealized open-lot PnL.

`/buy_status` labels accounting-realized PnL as `Realized today (UTC)`. It uses
the same UTC calendar-day operation-timestamp grouping as Analytics, not
Binance's proprietary "Today's PNL" and not the Daily Audit rolling previous-24h
window. Its open-position total covers all material rows even though the mobile
position list scales to the configured `MAX_POSITIONS` capacity when the
Telegram message limit allows; incomplete material valuation or entry price
data renders the total as `unavailable`.

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
- Material exposure is sorted by approximate USDT value and displays up to the
  configured `MAX_POSITIONS` capacity, subject to Telegram's 4096-character limit.
  If space runs short, the message preserves capacity, PnL, latest BUY, and status
  fields and reports how many material rows were omitted. Dust symbols have a
  separate compact policy; inventories above five show a count without listing
  every symbol. Unknown and unavailable valuation symbols use their own compact
  diagnostic limits.
- Missing/non-positive projection prices are not treated as zero: the command
  shows valuation as unavailable or partially unavailable instead.
- If persisted healthcheck details do not include `max_positions`, the dashboard
  falls back to runtime config/env aliases such as `MAX_POSITIONS`.
- If free USDT cannot be read, the command shows
  `Free USDT: diagnostic unavailable` while still reporting capacity.
- Position classification and BUY capacity come from the bot-persisted
  healthcheck details, which are the authoritative classification snapshot in
  `docs/DATA_CONTRACT.md`. `bot.portfolio` only enriches approximate exposure
  values for symbols in those persisted material/dust buckets; Django does not
  reclassify projection rows or infer capacity from them.
- Missing healthchecks or missing position-classification counts are displayed
  as unavailable. Stale healthcheck classifications and BUY diagnostics are
  labeled as last persisted/historical, and stale values do not produce a
  current BUY availability claim.
- If the latest BUY reason is absent, the command shows
  `Latest BUY reason: unavailable`; that alone does not block BUY status.
- Active re-entry cooldown reasons render as human-readable blocked states and,
  when present, include latest SELL/cooldown metadata from healthcheck details.
- Persisted reconciliation `inventory_warnings` from the latest healthcheck are
  shown only when they contain `WARNING`/`CRITICAL` diagnostics; `/buy_status`
  does not reconstruct those warnings from accounting tables.
- Long symbol lists are compacted. If the response exceeds Telegram's
  4096-character text limit, a compact fallback preserves capacity, position
  counts, PnL, latest BUY details, and status; secondary detail is omitted.
  Dynamic multiline text is escaped before rendering so HTML stays balanced.

These inventory warnings are intentionally read-only display diagnostics: the
dashboard and Telegram commands render bot-persisted reconciliation output,
avoid rebuilding accounting state, and never call Binance while formatting the
message.

### Daily Trading Audit

Daily Trading Audit is currently a bot-owned reporting surface. Django should
consume or display it only after the bot-side output is stable and documented in
the shared data contract; the dashboard should not become the owner of audit
computation.

Future trapped-capital, holding-efficiency, and time-based exit dry-run modules
belong in the same read-only reporting pattern: Django may display stable
bot-owned or contract-defined outputs, but should not infer new accounting truth
from portfolio projections or ad hoc historical reconstruction.

Run tests:

```bash
python manage.py test core
pytest
```

`pytest` and `pytest-django` are declared in `requirements.txt` for local validation.

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

Dashboard Disk Usage is separate from the public liveness endpoint. It is
read from the latest `bot.bot_healthcheck.details.disk_usage` payload, shows the
payload source, filesystem, used percent, free GB, and status, and degrades to
`Unavailable` when the bot-persisted payload is missing or malformed. Django
does not measure VPS disk directly, does not run shell commands, does not call
the VPS over SSH, and must not show Django/Render host filesystem usage as VPS
health. The bot healthcheck is expected to produce the VPS disk payload.
Telegram `/health` reuses the same bot-owned disk status for mobile operator
review.

## Detected Stack

- Django 5.2 LTS dependency line
- Python runtime pinned for Render through `.python-version`
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

The workflow assets below are versioned intentionally and are part of the
development quality system:

```text
AGENTS.md
.codex/skills/
.codex/subagents/
```

## Documentation Governance

Major documentation files should expose lightweight version metadata:

- `doc_version`
- `schema_version`
- `last_verified_at`

Operational/runtime logs should expose version context when changed:

- `app_version`
- `schema_version`
- `strategy_version`

Future operational tooling should generate DER diagrams, schema snapshots,
schema diffs, and column/type exports to reduce ambiguity between runtime DB
state and markdown contracts.

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
