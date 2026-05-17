# Django Dashboard — Project State

## Current State

The Django dashboard is operational as a DB consumer for the Binance Python Bot.

Detected Django apps:

- `core`: home/auth-adjacent pages, Telegram webhook listener, bot control endpoints, workflow models, and bot-owned table mappings.
- `dashboard`: dashboard pages, dashboard URLs, read models, forms, and dashboard templates.
- `currencyconverter`: UVA calculator, currency/exchange-rate models, DRF viewsets, HTML exchange-rate view, and staff-only rate update endpoint.
- `profile`: custom email-based user model, token login, profile API, admin integration, and profile permissions.
- `investments`: contains an `Invest` model, but it is not currently listed in `INSTALLED_APPS`.

Implemented capabilities:

- Authenticated dashboard pages
- Main dashboard as a concise operator console: normalized Bot Health badge, Inventory Integrity, compact Analytics link card, active issues, informational residual counts, and latest activity
- Main dashboard does not compute full-history KPI data during initial render; KPI calculations are deferred to the Analytics dashboard
- Main dashboard uses bounded homepage read paths: recent operations are fetched in a small capped window, SELL diagnostics are disabled by default, and dust overview loads only a capped recent candidate set without a homepage `COUNT(*)`
- Full exit-status diagnostics live on `/dashboard/exit-status/`, which uses a bounded recent global SELL-event window and degrades to open-lot rows marked `Diagnostics unavailable` when diagnostics cannot be read
- Main dashboard includes compact BUY/cooldown and churn summary cards sourced from latest healthcheck details and read-only recent trade history
- Read-only `/dashboard/churn/` summarizes recent SELL→BUY re-entry gaps, under-15-minute counts, and linked preceding SELL realized PnL when available
- Analytics dashboard at `/dashboard/analytics/` for performance analysis: KPIs, fees, PnL breakdowns, and historical tables
- Analytics dashboard context is cached for 60 seconds to avoid recomputing read-only full-history KPI data on every request
- Bot status card
- Portfolio summary
- Valuation consistency showing portfolio projection value, open-lots accounting value, drift, and missing price counts
- Compact latest operations table capped at four rows on the main dashboard
- Wave 8 Phase 1 performance KPI cards for net realized PnL, total USDT fees, win rate, average win/loss, profit factor, and gross deployed capital on the Analytics dashboard
- Read-only PnL by symbol and PnL by day tables on the Analytics dashboard; day grouping uses linked trade operation timestamps
- Drift visibility between portfolio and lots
- Fees by asset card
- Compact Active Operational Issues dust summary on the main dashboard, limited to unresolved critical/warning signals only; info-only residuals are summarized and are not promoted to active issues
- Compact “Why positions are not selling” table on the main dashboard, sourced from open lots and latest persisted SELL diagnostics, with dust/minNotional positions separated from strategy holds
- Main dashboard labels the SELL-candidate area as open FIFO lot exit status, explicitly distinguishes bot-managed lots from cash/SPOT-only balances, and can show projection balances excluded from SELL diagnostics because they lack open lots
- Position exit status treats SELL diagnostics as best-effort explanation metadata: if the diagnostics table/query is unavailable, the dashboard still renders open-lot rows from `position_lots` instead of failing the whole page
- Position exit rows now expose operator-facing status labels, mapped interpretations, PnL %, last diagnostic time, and suggested actions for known persisted SELL reasons
- Dedicated Dust / Residuals dashboard sourced from `bot.dust_detections` with filters and 25-row pagination
- Telegram mobile diagnostics commands on the existing webhook:
  - `/help`
  - `/health`
  - `/buy_status`
  - `/position SYMBOL`
  - `/last_sell SYMBOL`
  - `/why_not_sell SYMBOL`
- Telegram diagnostics include a compact command guide and format skipped/rejected
  SELL diagnostics with status, interpretation, suggested action, and raw event details for mobile review.
- Human-readable dust/drift alert formatting exists for notifier callers, including tiny-dust wording, urgency for incomplete SELL drift, and safe HTML escaping.
- Telegram diagnostics render compact Decimal-safe numeric values for mobile
  review while preserving read-only DB access and HTML escaping.
- `/buy_status` now reports effective positions as `material + unknown`, treats
  dust as non-blocking, falls back to runtime max-position config when the latest
  healthcheck omits it, and keeps optional diagnostic gaps from collapsing the
  whole BUY-capacity answer.
- Dust signal detail page
- Linked correction badges for dust detections using `bot.manual_corrections.source_detection_id`
- Manual review buttons:
  - mark ignored
  - review later
- Manual correction request workflow through `bot.manual_corrections`
- Manual correction list and detail pages
- Staff-only creation of correction requests
- UI-only duplicate click prevention for detections with linked `PENDING` or `APPLIED` corrections
- Operator guidance labels for dust/drift signals
- Tests for dashboard pages, permissions, form validation, valuation consistency, and drift quantity prefill
- Tests for position exit status classification, suggested action mapping, and dashboard rendering
- Tests for performance KPI Decimal calculations, null safety, zero-loss profit factor behavior, and identifiable manual correction PnL splitting
- DRF schema and Swagger UI through drf-spectacular
- Project-level environment validation for required settings
- Optional Telegram diagnostics allowlists through `TELEGRAM_ALLOWED_CHAT_IDS` and `TELEGRAM_ALLOWED_USER_IDS`
- Public Django app liveness endpoint at `/health/` for external keepalive checks

Validated operational correction path:

- On 2026-05-08, an ASIACOIN / `币安人生USDT` dust-closure case validated the dashboard-created manual correction request flow.
- Binance Small Amount Exchange removed the remaining SPOT balance while the bot still had an open FIFO lot of `0.0834` at entry price `0.3315`.
- The dashboard displayed the persisted `lot_balance_drift_detected` signal and created a `PENDING` `bot.manual_corrections` row with `correction_type = CLOSE_LOTS_EXTERNAL_SELL`.
- The request preserved dashboard provenance, requester identity, symbol, asset, quantity, price, reason, `source_detection_id`, and querystring context.
- The dashboard did not apply the correction or mutate bot accounting tables directly; the bot CLI performed dry-run review and explicit confirmed application.
- After application, validation showed no open lots and no portfolio row for the corrected symbol.

Detected infrastructure and tooling:

- Django REST Framework is present.
- pytest-django is configured in `pytest.ini`.
- Django `TestCase`, `TransactionTestCase`, and `SimpleTestCase` are used.
- SQLite is the default local database.
- PostgreSQL is supported via `DATABASE_URL` and appears in Docker Compose.
- Dockerfile and Docker Compose files are present, but should be validated before use.
- Celery was not detected.
- Redis was not detected.
- Django management commands were not detected.
- Templates exist under `core/templates`, `dashboard/templates`, and `currencyconverter/templates`.
- Static assets exist under `static/`.

---

## Important Current Boundary

The dashboard does not apply manual corrections.

It only creates `PENDING` correction requests. The bot project applies corrections using its CLI/service.

```text
Dashboard -> creates request
Bot CLI/service -> applies or rejects request
```

---

## Shared Contract

`docs/DATA_CONTRACT.md` is shared with the bot project and should remain identical in both repositories unless intentionally versioned.

Any change to bot-owned tables that affects dashboard interpretation must update `docs/DATA_CONTRACT.md` in the same change set.

---

## Recent Wave 4 Additions

- Added `ManualCorrection` managed=False model aligned to `bot.manual_corrections`.
- Added `ManualCorrectionRequestForm`.
- Added manual correction request page.
- Added manual correction list/detail pages.
- Added staff-only protection.
- Added safe initial quantity logic for `CLOSE_LOTS_EXTERNAL_SELL`:
  - uses `open_lot_quantity - spot_quantity` when lots exceed Binance spot
  - never pre-fills negative quantity
- Added operator guidance to dust dashboard.
- Added explicit “Do not correct from DB directly” warning.

---

## Known Risks / Pending Work

- Bot-owned table mappings still live in `core`; a later planned split can move them to `bot_shared`.
- DB grants for public/Supabase roles need review.
- Normalized Fees (USDT) and performance KPI cards depend on `fee_amount_in_quote`; non-USDT/unavailable conversions remain excluded by design.
- Performance KPI history currently reads available lot closures and should be revisited with pagination/date filters if closure volume becomes large.
- Gross deployed capital is an approximation based on FILLED BUY quote value and must not be presented as audited capital efficiency.
- Alerting is not implemented in dashboard and should likely be bot-owned.
- More filters/pagination may be needed as dust detections grow.
- `/health/` only confirms that the Django web process is reachable; it is not a bot/database health check.
- Historical dust/drift rows remain visible after correction, so views must keep making active/latest state and linked correction status clear.
- Reviewed/ignored/external-or-Earn dust signals suppress repeated paging only; their detections remain visible in history and do not alter bot accounting.

---

## Recommended Next Steps

1. Run full Django tests.
2. Manually test correction request creation from dust detail.
3. Verify rows appear in `bot.manual_corrections`.
4. Apply a test correction from the bot CLI in a controlled environment.
5. Harden DB grants.
6. Add bot-owned Telegram/Pushover alerting.
7. Plan the remaining app split for `bot_shared` and optional `bot_control`.
