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
- Bot status card
- Portfolio summary
- Valuation consistency showing portfolio projection value, open-lots accounting value, drift, and missing price counts
- Latest trade/recent operations card
- Drift visibility between portfolio and lots
- Fees by asset card
- Dust / residual dashboard sourced from `bot.dust_detections`
- Dust signal detail page
- Manual review buttons:
  - mark ignored
  - review later
- Manual correction request workflow through `bot.manual_corrections`
- Manual correction list and detail pages
- Staff-only creation of correction requests
- Operator guidance labels for dust/drift signals
- Tests for dashboard pages, permissions, form validation, valuation consistency, and drift quantity prefill
- DRF schema and Swagger UI through drf-spectacular
- Project-level environment validation for required settings
- Public Django app liveness endpoint at `/health/` for external keepalive checks

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
- Dashboard still lacks normalized Fees (USDT) card if not yet merged.
- Alerting is not implemented in dashboard and should likely be bot-owned.
- More filters/pagination may be needed as dust detections grow.
- `/health/` only confirms that the Django web process is reachable; it is not a bot/database health check.

---

## Recommended Next Steps

1. Run full Django tests.
2. Manually test correction request creation from dust detail.
3. Verify rows appear in `bot.manual_corrections`.
4. Apply a test correction from the bot CLI in a controlled environment.
5. Harden DB grants.
6. Add bot-owned Telegram/Pushover alerting.
7. Plan the remaining app split for `bot_shared` and optional `bot_control`.
