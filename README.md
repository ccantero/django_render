---
doc_id: readme
doc_version: 1.1.34
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-10-25
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
touch-sized layout with iOS safe-area padding. The shared version footer stays
visible in that standalone presentation.
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

`requirements.txt` also declares security floors for Django, Django REST
Framework, and their runtime `sqlparse` and `urllib3` dependency paths. The
project intentionally has no lockfile, so deployments must install from the
tracked requirements file and should be audited after dependency resolution.

### Static files

Source assets live in `static/`: `core/`, `currencyconverter/`, `profile/`,
and `favicon.ico`. Django admin assets are not stored in that tree.
`collectstatic` copies them from the installed Django package. `staticfiles/`
is `STATIC_ROOT` and is gitignored.

With `CC_DEBUG=true`, `runserver` serves static files through Django's
finders, so a local collect is not required for development. With
`CC_DEBUG=false`, WhiteNoise serves `staticfiles/` using
`CompressedStaticFilesStorage`: original file names plus sibling `.gz` files,
and no hashed manifest. Django 5.2 reads that backend from
`STORAGES["staticfiles"]`.

The Render web service currently uses the following **Build Command**, configured
in the Render dashboard (not in this repository):

```bash
pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --no-input && python manage.py showmigrations
```

`Procfile` defines only the web start command; there is no `render.yaml`.
The build installs dependencies, applies Django migrations, generates static
assets, and displays migration status. Keep `collectstatic` in the Build Command:
production WhiteNoise serves the generated `staticfiles/` directory, which is
intentionally not committed to Git. Removing that step would leave production
without the required CSS, JavaScript, and admin static assets.

The Build Command is managed outside Git, so verify it remains configured in
Render before deploying changes to static asset handling.

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

### Deployed application version

The running app version is separate from the `doc_version` headers in this
repository. The only app-version source is the root `VERSION` file, which
contains SemVer 2.0.0 core `MAJOR.MINOR.PATCH`. The initial value is `1.0.0`:
there was no canonical app version or git tag before that file, the app is
already in production, and the per-document `doc_version` numbers are not an
app release sequence.

Render sets `RENDER_GIT_COMMIT` at build and runtime
([default environment variables](https://render.com/docs/environment-variables)).
The footer and `/version/` use the first 7 hex characters as SemVer build
metadata, for example `v1.0.0+a1b2c3d`. With no commit available, the label
uses `dev` (`v1.0.0+dev`). Render does not provide a deploy timestamp.
`DEPLOYED_AT` may be set to an ISO-8601 instant, but the dashboard does not
need that variable. On Render (`RENDER=true`), the timestamp is the `VERSION`
file modification time, which is the source checkout time stored in that
deploy's slug and does not move if the service restarts without a new build.
If that file cannot be read, the web process start time is used. Local runs
and tests show `unknown`. Times are displayed in `America/Buenos_Aires` with
an `ART` label.

The shared base template renders a small footer on the regular site and on
the public calculator, including standalone mode where the navigation is
hidden. A page may also refresh the label from `/version/` so a cached HTML
shell does not keep an old deploy. The public JSON is only:

```bash
curl https://<your-render-host>/version/
```

```json
{"version":"1.0.0","commit":"a1b2c3d","deployed_at":"2026-10-25T14:30:00-03:00","display":"v1.0.0+a1b2c3d · 25/10 14:30 ART"}
```

`/health/` is unchanged. The version payload does not include service IDs,
branches, hostnames, or secrets. No Render dashboard change is required.

Bump `VERSION` in the same PR that changes deployed behavior:

- MAJOR: incompatible public contract (remove or rename `/version/` fields, change the `/health/` JSON shape, remove a public URL, or break existing login or session clients).
- MINOR: backward-compatible operator-visible feature (new page, endpoint, Telegram command, or additive `/version/` field).
- PATCH: bugfix or operator-visible correction that does not add a feature or break a contract.
- Do not bump for documentation-only, test-only, or workflow-only changes. The short commit still changes on every deploy.

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
- WhiteNoise for production static files, using `STORAGES["staticfiles"]` when `CC_DEBUG` is false
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

### Optional Passkeys

Passkeys are an opt-in addition to existing email/password accounts. Set
`PASSKEYS_ENABLED=true`, `PASSKEY_RP_ID` to the relying-party hostname, and
`PASSKEY_ALLOWED_ORIGINS` to comma-separated exact HTTPS origins before
enabling in production. Run the Django migrations during a normal deploy;
they add Django-owned rate-limit, one-use enrollment-proof, and WebAuthn
challenge tables without rewriting users or bot tables.

An existing signed-in user manages credentials at `/security/passkeys/`.
Adding or revoking requires the current password; adding a later credential
also requires a dedicated, five-minute WebAuthn step-up against a key owned by
the same user. Password and passkey proofs are consumed atomically for one
registration. Device loss requires
another registered passkey or the operator's established identity-verification
and account recovery process. Email possession alone is not recovery.

`/admin/` retains Django Admin's normal password login and staff/superuser
authorization. Its login page links to passkey login, which creates a normal
Django session before Admin applies its normal staff gate. Password login is
the recovery path. Before relying on `SECURE_PROXY_SSL_HEADER`, verify that the
deployment proxy overwrites `X-Forwarded-Proto` and the app server is not
directly reachable.

For rollback, set `PASSKEYS_ENABLED=false` and redeploy; retain migrations and
credential rows. Existing accounts, sessions, passwords, permissions, and API
tokens remain in place. Verify Safari/iOS and desktop authenticator
interoperability after deployment.

For loopback-only PostgreSQL validation, run the disposable harness from an
authorized Docker account:

```bash
./scripts/run_passkey_postgres_disposable_test.sh
```

For prerequisites, result interpretation, Work Cloud limitations, and the
complete safety runbook, see
[`docs/testing/DISPOSABLE_POSTGRESQL_TESTING.md`](docs/testing/DISPOSABLE_POSTGRESQL_TESTING.md).

The harness uses `.venv/bin/python` by default. To validate a separately
audited environment, supply its absolute interpreter path through `PYTHON_BIN`;
relative paths are rejected:

```bash
PYTHON_BIN=/absolute/path/to/python \
  ./scripts/run_passkey_postgres_disposable_test.sh
```

It creates uniquely named PostgreSQL 16 Docker resources, uses an isolated
loopback-only test database, runs the PostgreSQL row-lock regression tests and
full Django suite, then removes only the resources it created. Its deployment
system check uses a long synthetic key and production-like settings with
`DEBUG` disabled, so security warnings fail validation rather than being
confused with development-mode test behavior. The test suites run with
`DEBUG=True`, matching their normal request expectations. Django clones its
explicitly named test database from an ordinary,
run-owned PostgreSQL template database that already contains the `django`
schema; no globally reusable PostgreSQL template is created. It refuses
inherited database URLs and does not load `.env`. See `IMPLEMENTATION_WORK.md`
for the remaining HTTPS Safari/iPhone smoke-test procedure.

After successful disposable database initialization and fresh migrations, the
harness reports migration consistency, deployment security checks, each
PostgreSQL concurrency case individually, the combined and repeated
concurrency runs, the full Django suite, and Django test-database cleanup as
independent `PASS`, `FAIL`, or `NOT_RUN` stages. Migration drift is still a
required failure: a known `core` drift is labeled as pre-existing
`origin/main` drift while remaining checks continue. The final result is
nonzero if any required stage fails.

The run-owned test template contains both `django` and `bot` schemas, while
the PostgreSQL search path remains `django,public`; bot tables are always
schema-qualified. Django clones that template for each test database, and a
PostgreSQL-only session fixture fails before tests if either expected schema is
absent. Its historical `django.dust_signal_reviews` table and disposable
`bot.dust_signal_reviews` fixture table are explicitly included in Django's
PostgreSQL flush set so their foreign keys to the Django-owned user table are
truncated in the same statement;
the Django-managed tables are explicitly qualified with the `django` schema to
avoid relying on connection search-path resolution. The cleanup path does not
use `CASCADE` or alter bot-table ownership. The `bot` schema and any test
tables in it are disposable only; the harness never connects to or changes an
external bot database. PostgreSQL runtime confirmation of this isolation path
remains required from an authorized Docker-capable operator.

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
