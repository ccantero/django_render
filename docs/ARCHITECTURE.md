---
doc_id: architecture
doc_version: 1.1.25
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-10-30
source_repo: django_render
---

# Django Dashboard — Architecture

## 1. Purpose

The Django project is the operational dashboard for the Binance Python Bot.

It provides visibility, review, and request workflows over bot-owned database tables. It is not a trading engine.

---

## 2. System Boundary

### Dashboard responsibilities

- Read bot health and trading state.
- Display bot-owned VPS disk usage from latest healthcheck details for operator disk-pressure visibility.
- Display portfolio, lots, trades, fees, drift, and dust detections.
- Serve allowlisted read-only Telegram diagnostics for mobile operators,
  including bot health with bot-healthcheck VPS Disk Usage, conservative BUY capacity
  status from persisted bot state plus
  runtime-config fallback for max-position limits when the read model omits
  them, and portfolio status with snapshot-backed historical changes plus an
  on-demand in-memory 7-day equity PNG when enough history exists.
- Display read-only operational performance KPIs from realized lot closures and filled trade operations.
- Display filtered Operational Trading KPIs v2 from read-only trade operations, lot closures, and linked lot open times.
- Display future trapped-capital, holding-efficiency, and dry-run exit
  diagnostics only after the bot or shared data contract exposes stable
  read-only outputs for them.
- Display grouped dust/residual signals with operator guidance.
- Record manual review state.
- Create explicit `PENDING` manual correction requests.

### Dashboard non-responsibilities

- No Binance trading.
- No BUY/SELL execution.
- No FIFO accounting mutation.
- No direct correction of lots.
- No direct mutation of bot accounting tables.
- No inventory remediation scripts executed from Django.
- No alert routing as a dependency for the bot.

---

## 3. Recommended App Structure

### Current app structure

```text
django_render/
  settings.py, urls.py, env_validation.py

core/
  home/auth-adjacent views, Telegram webhook listener, bot control endpoints,
  workflow models, and managed=False bot table mappings

dashboard/
  dashboard views, dashboard URL routes, read models, forms, and templates

currencyconverter/
  currency and exchange-rate models, UVA calculator, DRF viewsets,
  serializers, templates, and staff-only rate updates

profile/
  custom email-based user model, profile serializer/viewset,
  token login, admin, and permissions

investments/
  Invest model exists, but the app is not currently installed
```

The dashboard app split is in place. The remaining preferred evolution is:

```text
core/
  auth/base/shared utilities

dashboard/
  views.py
  dashboard_read_model.py
  dust_read_model.py
  templates/dashboard/
  forms.py

bot_shared/
  managed=False models for bot-owned tables

bot_control/
  optional safe control-plane UI
```

Moving bot-owned models out of `core` remains P2 tech debt, not an immediate blocker.

---

## 4.0 Public PWA Boundary

The public UVA calculator and exchange-rate pages share one PWA scope:
`/currencyconverter/`, with the calculator as its start URL. The authenticated
`/dashboard/` route is outside that scope. The service worker handles public
GET requests only and does not cache authenticated dashboard data.
The calculator template reuses the shared base and calculation view, but adds
page-scoped responsive CSS: ordinary browsers retain the shared navigation;
standalone display mode hides it and presents the calculator as a padded,
single-column touch interface. The shared `.app-version` footer stays visible
in that mode.
The results area displays the official USD and UVA quotes used by the current
calculation.

The service worker is network-first. Navigations and `/version/` are fetched
with `cache: 'no-store'`, and the worker script itself is not stored in the
Cache API. Activate deletes caches other than `calculadora-uva-v2`. Offline
fallback can still show the last calculator HTML, whose footer is the version
captured with that response. A controlled page also refreshes the footer from
`/version/`, which is not cached.

## 4. Data Access Pattern

The dashboard reads a shared database.

```text
Bot writes bot.* tables
Dashboard reads bot.* tables
Dashboard may insert PENDING manual correction requests
Bot applies corrections
```

Use `managed = False` for existing bot-owned tables.

Local development defaults to SQLite through `dj_database_url`. Production-style configuration can use PostgreSQL through `DATABASE_URL`; when PostgreSQL is detected, settings currently apply a `django,public` search path option. Bot-owned table mappings use explicit `bot` schema table names.

## 4.1 Request Flow

```text
Browser dashboard pages -> django_render.urls -> dashboard.urls -> dashboard.views -> read model/forms -> templates
Browser bot-control form -> POST /bot/stop/ or /bot/resume/ -> core.views -> core_botcontrol desired state -> same-origin redirect and flash message
JSON bot-control client -> same URLs with Accept: application/json, or without a text/html Accept -> existing JSON payload after a confirmed pause or any resume; an unconfirmed pause returns HTTP 400
Browser core pages -> django_render.urls -> core.urls -> core.views
External keepalive cron -> /health/ -> core.views.health -> JSON liveness response
Public deploy check -> /version/ -> core.views.version -> version, short commit, explicit deployed_at or null, timestamp_source, display
Telegram webhook -> /telegramapi/listener/ -> secret validation -> safe update parsing -> best-effort audit persistence/deduplication -> static `/help` or lazy diagnostic dispatch -> bounded outbound Telegram API call -> HTTP acknowledgement
Telegram portfolio chart -> read-only `bot.portfolio_snapshots` rows with `source = "bot_cycle"` and `notes.portfolio_equity_usdt` -> transport-agnostic PNG bytes -> Telegram photo or text fallback
API client -> django_render.urls -> currencyconverter/profile routers -> DRF viewsets -> serializers/models
Diagnostics API client -> django_render.urls -> dashboard.bot_diagnostics_api -> scoped bearer authentication -> bounded managed=False bot-table reads -> sanitized JSON
Swagger UI -> /api/docs -> drf-spectacular schema at /api/schema
Telegram message auditing is diagnostic-only: a database failure is logged with
safe context and does not block `/help` or a command response. `/help` checks
the allowlist in the lightweight listener and does not import the
database-backed diagnostics module. Other commands load that module lazily;
individual command failures use an operator-safe fallback response.
```

State-changing dashboard actions are protected with login, staff checks where required, POST-only decorators where present, and Django CSRF except for the Telegram webhook listener, which uses the Telegram secret-token header.

Pause and resume write only `core_botcontrol.is_paused`, `reason`, `updated_by`, and `updated_at`. `is_paused` is the desired state. The dashboard does not receive an acknowledgement from the bot and does not claim the bot has stopped or resumed. Every pause POST requires confirmation. HTML sends `confirm=yes`. JSON accepts that form field, `{"confirm":"yes"}`, or `{"confirm":true}`. Resume does not require confirmation. A missing confirmation does not write: HTML redirects with "Confirmá la solicitud de pausa antes de continuar. No se registró ningún cambio.", and any other client receives HTTP 400 `{"error":"confirmation_required","detail":"<same sentence>"}`. A search of this repository, including Telegram handlers and scripts, found no caller of `/bot/stop/`, `/bot/resume/`, or `/bot/status/` other than the dashboard form, its script, tests, and docs, so JSON has no compatibility exception. A confirmed HTML post then redirects to a safe same-origin `next` or `Referer`, falling back to `/dashboard/#control-seguro`. Targets that point at the pause, resume, or status URLs are rejected. The redirect carries "Pausa solicitada" or "Reanudación solicitada". The control card shows that requested state, the row time in America/Buenos_Aires (ART), the user email, and the reason. With JavaScript, the same POST is sent as `Accept: application/json` and the card updates in place. A failed, non-JSON, or aborted response does not submit the form again. The card shows "Resultado incierto. No se reenvió el pedido.", re-reads `GET /bot/status/`, and keeps that warning. "Reintentar el pedido" is the only later POST. While a request is in flight the pause and resume controls are disabled, and an older response sequence cannot replace a newer card state. Clients that do not advertise `text/html` keep the previous JSON object when the pause is confirmed or the call is a resume. Login and CSRF rules are unchanged, including for authenticated non-staff users. Without JavaScript, the browser submits the form once and follows the redirect.

`/health/` is public and side-effect-free. It reports only Django web-process liveness for hosting keepalive checks; bot operational health remains sourced from `bot.bot_healthcheck` in dashboard views.

The experimental `/api/bot/health` and `/api/bot/inventory/ETHUSDT` routes
require a dedicated `BOT_DIAGNOSTICS_API_TOKEN` bearer secret of at least 32
characters, capped at 512 characters. They do not reuse Django user tokens or
session authentication. The secret is unset by default, which denies access.
The health route selects one latest `bot.bot_healthcheck` row; inventory adds
one latest ETHUSDT `bot.dust_detections` event lookup, one `bot.portfolio`
lookup, and one aggregate over positive ETHUSDT `bot.position_lots` rows. It
emits a fixed JSON allowlist, decimal strings, source timestamps, explicit
observation recency/capacity status, and `Cache-Control: no-store`; no query
accepts SQL, symbols, file paths, commands, or action parameters. Responses
never include the raw healthcheck `details` object. GET reads data; HEAD and
OPTIONS are non-mutating; unsupported write methods return 405.

This is a new internet-facing Render route when deployed and enabled. HTTPS is
required by production Django security settings. Keep the credential outside
Git and rotate it by replacing the environment secret. [Render documents
automatic edge DDoS protection](https://render.com/docs/ddos-protection), but
targeted application-level HTTP abuse is not fully covered; this Django app
has no route-level rate limiter. Failed
authentication is checked before bot-table queries. Accepted query count and
response shape are fixed, though aggregate work scales with the number of
matching ETHUSDT lot rows. Before broad public enablement, prefer an edge
allowlist or rate limit for these two paths where the deployment supports it;
otherwise assess a small app-level limiter. No Redis or rate-limit service is
added by this PoC. Work Cloud network egress, Action support, secret delivery,
and workspace domain permission are not configured or tested here.

The inventory endpoint reports `bot.portfolio` as a local projection,
`bot.position_lots` as FIFO accounting evidence, and the latest matching
`bot.dust_detections.spot_quantity` as a historical event quantity. Its
`observation_recency` is event age only, never exchange-balance validity; the
field `current_exchange_truth` remains false. The bot's `BalanceService`
fetches complete non-zero account assets into runtime memory, and the periodic
portfolio/dust paths use that data to produce projections or event records,
but no complete Spot snapshot table is persisted. The read-only inventory
comparison CLI queries Binance at runtime and reads lots/generations from
PostgreSQL without persisting the exchange snapshot. Django never describes
projection, lot, or event evidence as current Binance Spot truth.

Healthcheck capacity fields are bot-produced and retain their existing KPI
definitions. Fresh complete values are current only as of `healthcheck_at`;
stale values are exposed only under `historical_global`, with `global: null`.
Missing and partial fields remain unavailable/null; Django does not infer slot
occupancy from portfolio rows or FIFO quantities. The bot repository has an
active `position_generations` model used by its comparison tool. Django maps
that table read-only as `PositionGeneration` for Telegram `/position_modes`
and `/position_mode`. Those commands classify material symbols from active
generations only. The list also marks positive open quantity that is
generationless, linked to a `CLOSED` generation, or linked to a missing
generation id, without treating that quantity as HOLD or TRADING. This
inventory endpoint still returns `active_generation` unavailable; that payload
was not changed. Lot evidence freshness
is unknown because the mapped lot rows have no update timestamp.

Inventory reads are separate ORM statements in Django's normal autocommit
mode. PostgreSQL's default statement-level snapshots permit bot writes between
the healthcheck, event, portfolio, and lot reads. The response therefore sets
`consistency.atomic` to false and labels portfolio-versus-lot comparison as
`not_synchronized`; callers must use each source timestamp and must not treat
the response as one reconciliation snapshot. A repeatable-read transaction
was not added because this is advisory HTTP evidence, not a bot-side
reconciliation result, and the API does not need to block or coordinate bot
writes.

`/version/` is also public and side-effect-free. It reads the root `VERSION`
file, `RENDER_GIT_COMMIT`, and an explicit UTC instant from `DEPLOYED_AT` or
from `build_info.json` written by `python manage.py stamp_build`. It does not
use file modification time or process start time. The response is
`Cache-Control: no-store` and contains `version`, `commit`, `deployed_at`,
`timestamp_source` (`explicit`, `build_stamp`, or `unknown`), and `display`.
`deployed_at` is null when no explicit instant was recorded. It does not read
bot tables and does not return Render service IDs, branches, hostnames, or
secrets. The same display string is rendered by the shared base footer outside
`{% block content %}`, so pages that replace the content or footer blocks
still show it.

Authenticated dashboard Disk Usage and Telegram `/health` Disk Usage are also
side-effect-free, but they are not part of the public `/health/` liveness
endpoint. They read latest `bot.bot_healthcheck.details.disk_usage`, which the
bot is expected to produce from the VPS where audit bundles, cron logs,
retention archives, PostgreSQL, and bot logs live. Django does not measure VPS
disk directly, does not call the VPS over SSH, and does not label Django/Render
host filesystem usage as VPS health. Missing or malformed disk payloads degrade
to unavailable output.

## 4.2 External Services

Detected external calls:

- Telegram Bot API in `core.views.send_message`.

Outbound Telegram calls use the configured timeout (10 seconds by default),
require both a successful HTTP response and Telegram JSON `ok: true`, and log
safe command/update/chat/stage context for delivery failures. Tokens, webhook
secrets, full payloads, and token-bearing URLs are not logged.

The tracked `Procfile` defines the intended 512 MB Render process model:
Gunicorn with one worker, two threads, and a 30-second timeout. `preload` is
not enabled and request recycling is not configured because no local evidence
establishes retained-memory growth. Render's configured start command remains
an external deployment fact that must be verified after release.
- Banco Ciudad quote endpoint in `currencyconverter.views.get_ARSUVA_rate`.
- dolarapi.com quote endpoint in `currencyconverter.views.update_ARSUSD_rate`.

No Celery, Redis, or asynchronous worker service is currently wired in this project.

## 4.3 Static Files

`STATICFILES_DIRS` points at the repository `static/` directory, which holds
project source assets for `core`, `currencyconverter`, `profile`, and
`favicon.ico`. `STATIC_ROOT` is `staticfiles/`. That directory is collectstatic
output and is not part of the Git tree.

`WhiteNoiseMiddleware` is installed immediately after `SecurityMiddleware`.
`django_render/wsgi.py` does not wrap the application with the old
`DjangoWhiteNoise` helper. When `CC_DEBUG` is false, `STORAGES["staticfiles"]`
uses `whitenoise.storage.CompressedStaticFilesStorage`, which keeps original
filenames and writes sibling `.gz` files. Django 5.2 does not read the legacy
`STATICFILES_STORAGE` setting. Hashed manifest storage is not enabled. When
`CC_DEBUG` is true, storage stays `StaticFilesStorage` and `runserver` serves
files through the static finders.

Django admin assets are collected from `django.contrib.admin`. They are not
vendored in `static/admin`. Render serves the collected tree only after the
service Build Command runs `collectstatic`. That command is configured in the
Render dashboard; this repository has no `render.yaml` and no build script.
The owner confirmed the production configuration on 2026-10-30:

```text
Build Command: pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --no-input && python manage.py showmigrations
Start Command: gunicorn django_render.wsgi
```

`python manage.py stamp_build` no corre hoy en producción; agregarlo al Build Command está pendiente de decisión del owner.

Render command/boot readiness (including `collectstatic`) is `RUNTIME_VERIFIED`
from the owner-provided deploy log and static HEAD response recorded in
[PROJECT_STATE.md](PROJECT_STATE.md#render-commandboot-readiness). The tracked
`Procfile` flags are separate from this confirmed Render Start Command.

---

## 5. Source of Truth Rules

- `bot.position_lots` is the accounting source of truth.
- `bot.portfolio` is a projection/read layer.
- Binance Spot is live operational truth for current exchange balances, but it
  is not stored or mutated by Django.
- `bot.trade_operations` is the economic operation layer.
- `bot.trade_fills` is the raw execution/audit layer.
- `bot.lot_closures` is the FIFO closure audit layer.
- `bot.dust_detections` is an observational read model.
- `bot.sell_decision_events` is a read-only SELL diagnostics event log.
- `bot.manual_corrections` is the manual correction request/audit workflow.

---

## 6. Dust / Drift Dashboard

The dust dashboard reads `bot.dust_detections`, groups signals, and adds operator guidance:

- Below min notional: monitor / optionally ignore
- Lots > Binance: accounting drift, needs review
- Binance > Lots: external balance, needs review
- Possible incomplete sell: inspect Binance history, then create correction request if confirmed
- Unclassified signal: inspect details before taking action

Dust list/detail views also batch-read `bot.manual_corrections` by `source_detection_id` to show whether a detection has no correction, a pending correction, an applied correction, a rejected correction, or a failed correction. The dashboard uses linked `PENDING` and `APPLIED` rows only to prevent obvious duplicate clicks in the UI; duplicate matching and rejection remain bot-owned.

The main dashboard uses a defensive best-effort active issue helper over grouped latest-run dust signals. It shows unresolved critical/warning signals only, excludes reviewed/ignored/external-or-Earn and blocking-correction groups when that state is available, and keeps informational residuals in a count/exposure summary instead of promoting them to active issues. The full audit history remains on the dedicated Dust / Residuals dashboard.

For homepage latency, the overview skips SELL diagnostics by default and links
to the dedicated `/dashboard/exit-status/` page. Exit Status intentionally uses
a bounded recent global SELL-event window instead of an unbounded historical
scan, then filters open-lot symbols in Python. Recent
operations are fetched once and reused for the latest-trade card, and dust
overview uses a capped latest-run candidate set without a homepage-wide
`COUNT(*)`. Exact historical latest-per-symbol SELL lookup needs an index such
as:

```sql
CREATE INDEX CONCURRENTLY idx_sell_events_symbol_created_id
ON bot.sell_decision_events(symbol, created_at DESC, id DESC);
```

The dashboard must display uncertainty and avoid treating approximate exposure as audited PnL.

The main dashboard also compares `bot.portfolio` projection value against open `bot.position_lots` valued with `portfolio.current_price`. Missing prices are counted and shown as warnings; they are not silently converted to zero-value audited PnL.

The Wave 8 Phase 1 KPI section is read-only and deferred to the Analytics dashboard rather than computed during homepage rendering. It uses `bot.lot_closures.realized_pnl` for realized PnL, linked `bot.trade_operations.executed_at` or `created_at` for PnL-by-day grouping, `bot.trade_operations.fee_amount_in_quote` for normalized USDT fee totals, and FILLED BUY quote value as approximate gross deployed capital. Non-USDT or unavailable fee conversions are excluded from normalized totals. Manual/accounting correction PnL is split only when available trade operation metadata identifies it; otherwise it remains included in realized PnL totals with an explicit limitation note. Analytics context is cached for 60 seconds under `dashboard:analytics_context:v2` as a pickle-safe snapshot. Unmanaged bot models use app label `trading_read`, which is not installed, so caching the live model instances makes the next cache read raise `LookupError` during unpickle. The snapshot copies concrete model fields and does not keep model methods or relations. The analytics template reads dict and scalar KPI fields only. Cache read, write, and delete catch pickle, lookup, value, and connection errors. An unreadable entry is dropped and the read model is rebuilt. Errors raised while building that read model are not treated as cache misses.

The homepage asks the KPI read model for compact summary data only; detailed
PnL-by-symbol and PnL-by-day history remains an Analytics-dashboard concern.
For local investigation, `DASHBOARD_PROFILE=true` adds opt-in section-level
timings for the main dashboard read
model, and optional `DASHBOARD_PROFILE_SQL=true` logs slow SQL snippets above
`DASHBOARD_SLOW_QUERY_MS` (default `100`) without exposing credentials or DB URLs.

The main dashboard position exit status section and full Exit Status page are
read-only. They use
`bot.position_lots` as the inventory source, joins `bot.portfolio` only for
display quantity/price/value, and reads the latest `bot.sell_decision_events`
row per open-lot symbol for normalized reason explanations. Known reasons map to
operator-facing labels, interpretations, and suggested actions; unmapped reasons
fall back to review rather than pretending there is no diagnostic. It does not
call Binance, execute trades, or mutate accounting state.
If the bounded SELL diagnostic read fails, Exit Status still renders open FIFO
lots with `Diagnostics unavailable` rather than failing the request.

Latest anti-churn BUY status is read from `bot.bot_healthcheck.details` only.
The dashboard recognizes loss, take-profit, and generic SELL re-entry cooldown
reasons and displays optional persisted SELL/cooldown detail keys when present.
Extended cooldown diagnostics are rendered as observability only: latest SELL
operation id, symbol, executed timestamp, nullable reason, reason source,
realized PnL, cooldown type, classification source, elapsed minutes, and
remaining minutes come from the latest healthcheck payload. Django must not
reconstruct cooldown eligibility from trades, lots, or portfolio rows, and
missing bot metadata must degrade to conservative labels such as `unknown` or
`not provided` rather than invented explanations.
For display compatibility, legacy `cooldown_type = sell` and bot-side
`cooldown_type = generic_sell` both render as the same recent-sell cooldown
label.
Persisted reconciliation `inventory_warnings` are read from the same latest
healthcheck details payload for `/buy_status` and compact dashboard summaries;
the dashboard does not reconstruct those diagnostics from accounting tables.
Recent churn observability is a separate read-only model over filled
`trade_operations` plus linked `lot_closures` realized PnL; homepage shows only
summary counts while `/dashboard/churn/` carries the detail rows.

The same boundary applies to future Daily Trading Audit consumption: Django may
render bot-produced read-only report output after that format is stabilized in
the shared contract, but it should not recompute audit truth or become the owner
of the bot-side report.

The same architecture constraint applies to proposed trapped-capital,
capital-days, holding-efficiency, and time-based exit dry-run views. Django
should consume analytics outputs owned by the bot or explicitly defined in the
shared contract; it should not reconstruct accounting truth from ad hoc joins or
projection-only data.

For inventory mismatch investigations, Django documentation may reference the
bot-side scripts below, but the dashboard should not execute or replace them:

- `src/scripts/analyze_symbol_inventory_gap.py`
- `src/scripts/manual_correction.py`
- `src/scripts/sync_portfolio_from_api.py`

Operational Trading KPIs v2 live in a dedicated dashboard read model service at
`dashboard/services/operational_kpis.py`. The page reads filled operations in a
bulk path, linked lot closures, and linked lot opening timestamps; it does not
call Binance or mutate bot-owned accounting tables. Missing
`strategy_version` metadata is grouped as `unversioned`, identifiable
manual/accounting-only corrections are excluded from trading-quality metrics,
and missing timestamps are ignored for hold-time and churn calculations.

Dust review state is a dashboard workflow concern. Reviewed, ignored, and
external-or-Earn rows suppress repeated paging only; the underlying
`bot.dust_detections` history remains available for audit, and no accounting
mutation occurs.

---

## 7. Manual Correction Request Flow

The dashboard can create a `PENDING` `bot.manual_corrections` row.

Creation rules:

- Staff/superuser only
- POST-only
- CSRF-protected
- Positive Decimal `quantity`
- Positive Decimal `price_usdt`
- `estimated_value_usdt = quantity * price_usdt`
- `payload.source = django_dashboard`

The dashboard must not apply the correction. Application happens in the bot project through `ManualCorrectionService` or CLI.

Validated flow:

- `CLOSE_LOTS_EXTERNAL_SELL` has been validated end-to-end from dashboard request creation to bot CLI dry-run and confirmed application.
- A 2026-05-08 ASIACOIN / `币安人生USDT` case confirmed that the dashboard can preserve `source_detection_id`, operator/request metadata, and context while leaving all accounting writes to the bot.
- Binance is not called by this correction path; it is an accounting-only closure of reviewed lots.

---

## 8. Security

Required:

- Login for dashboard pages
- Staff-only correction request creation
- No secrets in templates/logs
- POST-only state changes
- CSRF protection
- DB grants hardening for public/Supabase roles

Recommended:

- Dedicated read-only dashboard DB user
- Explicit write permission only on safe dashboard/request tables

### Passkeys

The custom `profile.UserProfile` remains `AUTH_USER_MODEL`; password hashes,
IDs, staff/superuser flags, groups, permissions, and DRF token records are not
changed. `django-otp-webauthn` owns credential and user-handle models with
foreign keys to that user. `profile.PasskeyRateLimit` is Django-owned and
contains only an HMAC of the rate-limit scope/identity, a time window, and a
counter. `PasskeyEnrollmentProof` stores only HMACed one-use proof tokens,
user/session binding, proof type, and timestamps. `PasskeyEnrollmentChallenge`
stores short-lived verifier state for the enrollment step-up and is consumed
under a row lock. No credential private key material is stored by the
dashboard.

The browser login and management flows use the library's WebAuthn verification
and create ordinary Django sessions. The custom helper requires user
verification and discoverable registration. Login and registration ceremonies
are short-lived and session-bound; enrollment step-up state is server-side,
user/session-bound, and atomically consumed before verification. Password and
passkey proof tokens are independently stored HMACed and consumed together
under database row locks when an additional credential registration starts.
This does not call Django's login flow or change the authenticated user.
Exact allowed origins and RP ID are configured explicitly. Enrollment and
revocation require password reauthentication; adding another key also requires
a current user's passkey assertion. Revocation is user-scoped and POST/CSRF
protected. Rate limits use database row locks, fail closed if enforcement fails,
and prune expired rows at most once per process per five minutes.

Passkeys default off. Production enablement requires explicit HTTPS origins
and RP ID. Verify proxy forwarding sanitizes `X-Forwarded-Proto` before the
production `SECURE_PROXY_SSL_HEADER` is trusted. Admin retains Django's native
password page and permissions; the passkey login creates a normal session and
Admin itself enforces staff/superuser access. Password remains the documented
operator recovery path. Disable with `PASSKEYS_ENABLED=false`; keep migrations
and credential rows for a reversible rollback.

---

## 9. API Decision

Do not introduce a bot producer API / dashboard consumer API yet.

Current preferred integration:

```text
Shared database contract + managed=False models
```

An API may be reconsidered later for mobile clients, third-party consumers, or if the dashboard must be isolated from the database schema. It is not required for push notifications; bot-side Telegram/Pushover alerts are preferred.

---

## 10. Shared Contract Sync Policy

The bot project’s `docs/DATA_CONTRACT.md` is the canonical shared contract.
This Django repository should keep its local copy synchronized whenever
bot-owned table semantics, healthcheck payloads, diagnostic payloads, or
read-model interpretation changes. Dashboard-only notes may be additive in
other docs, but they should not redefine bot-owned semantics independently.

## 11. Documentation and Schema Governance

Documentation governance is an operational concern for this project.

Major markdown contracts should include:

- `doc_id`
- `doc_version`
- `schema_version`
- `last_verified_at`

When runtime logging or operational alerts are changed, logs should expose
version context such as:

- `app_version`
- `schema_version`
- `strategy_version`
- `docs_version`
- `run_id`

Future generated DB visibility artifacts should live under `docs/db/` and may
include `DER.md`, `schema_snapshot.sql`, and `schema_columns.csv`. These
artifacts are observational only and must not replace the shared data contract.
