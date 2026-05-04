# Django Dashboard — Project State

## Current State

The Django dashboard is operational as a DB consumer for the Binance Python Bot.

Implemented capabilities:

- Authenticated dashboard pages
- Bot status card
- Portfolio summary
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
- Tests for dashboard pages, permissions, form validation, and drift quantity prefill

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

- `core` app has grown too broad and should eventually be split.
- DB grants for public/Supabase roles need review.
- Dashboard still lacks normalized Fees (USDT) card if not yet merged.
- Alerting is not implemented in dashboard and should likely be bot-owned.
- More filters/pagination may be needed as dust detections grow.

---

## Recommended Next Steps

1. Run full Django tests.
2. Manually test correction request creation from dust detail.
3. Verify rows appear in `bot.manual_corrections`.
4. Apply a test correction from the bot CLI in a controlled environment.
5. Harden DB grants.
6. Add bot-owned Telegram/Pushover alerting.
7. Plan app split: `dashboard`, `bot_shared`, `core`.
