# TODO — Binance Bot Django Dashboard

---

## 🔴 P0 — Safety / Correctness

- [x] Dashboard requires login for operational views
- [x] Dust / residual dashboard reads `bot.dust_detections`
- [x] Manual correction request creation is staff/superuser-only
- [x] Manual correction request form is POST + CSRF protected
- [x] Dashboard does not apply manual corrections
- [x] Dashboard does not mutate bot accounting tables directly
- [x] ManualCorrection model aligned to bot-owned `bot.manual_corrections`
- [x] Safe positive quantity validation for manual correction requests
- [x] Never prefill negative correction quantity
- [ ] Review production DB grants for `anon` / `authenticated`
- [ ] Ensure dashboard DB user cannot write bot accounting tables

---

## 🟠 P1 — Dust / Drift Workflow

- [x] Add Dust / Residuals dashboard section
- [x] Show grouped dust detections
- [x] Show latest run id / timestamp
- [x] Show spot quantity / open lot quantity / quantity delta in detail view
- [x] Show payload details
- [x] Add operator guidance labels
- [x] Add “Do not correct from DB directly” warning
- [x] Add Mark ignored action
- [x] Add Review later action
- [x] Add Create manual correction request link
- [ ] Add filter for operator guidance category
- [ ] Add better pagination for large detection history
- [ ] Add export/download for reviewed dust signals if useful

---

## 🟠 P1 — Manual Correction Requests

- [x] Add `ManualCorrection` managed=False model
- [x] Add correction request form
- [x] Add correction request confirmation/safety page
- [x] Add pending/applied/rejected/failed correction list
- [x] Add correction detail page
- [x] Store `requested_by`
- [x] Store dashboard payload source
- [x] Compute `estimated_value_usdt`
- [x] Prefill quantity as `open_lot_quantity - spot_quantity` only when lots > spot
- [ ] Add explicit confirmation checkbox in the form text if desired
- [ ] Show linked source dust detection detail from correction detail
- [ ] Add dashboard action to mark a request as rejected only if safe and contract allows it

---

## 🟠 P1 — Monitoring / Summary Cards

- [x] Bot status card
- [x] Portfolio summary
- [x] Latest operation/recent trade card
- [x] Drift alerts
- [x] Fees by asset card
- [ ] Add normalized Fees (USDT) card from `trade_operations.fee_amount_in_quote`
- [ ] Add lots summary from `position_lots`
- [ ] Add recent rejections/skips from `order_decisions` or `trade_operations`
- [ ] Add manual corrections pending count to main dashboard

---

## 🟡 P2 — Architecture / Tech Debt

- [ ] Split dashboard functionality out of broad `core` app
- [ ] Suggested app structure:
  - `dashboard`
  - `bot_shared`
  - `bot_control`
  - `core`
- [ ] Move read-model code into dashboard-specific modules
- [ ] Keep all bot-owned models managed=False
- [ ] Avoid migrations for bot-owned tables
- [ ] Review N+1 query patterns
- [ ] Add pagination for manual correction lists
- [ ] Standardize template partials/components

---

## 🟡 P2 — Alerts / Notifications

- [ ] Do not make dashboard a required alert relay
- [ ] Implement alerting in bot project first
- [ ] Dashboard may later display alert history if bot persists alert events
- [ ] Consider Telegram/Pushover alert state cards after bot implementation

---

## 🟣 P3 — UX Improvements

- [ ] Add clearer empty states
- [ ] Add visual distinction between approximate exposure and audited financials
- [ ] Add inline help text for each dust reason
- [ ] Add action checklist in dust detail page
- [ ] Add breadcrumbs across dashboard/manual correction pages
- [ ] Improve mobile layout for operator usage

---

## 🧪 Testing

- [x] Unauthenticated user cannot create correction
- [x] Non-staff user cannot create correction
- [x] Staff user can create pending correction
- [x] Form rejects zero/negative quantity
- [x] Model fields match bot table contract
- [x] Drift prefill tests for lots > spot
- [x] Negative delta does not prefill negative quantity
- [ ] Add integration test against a Postgres-like schema if practical
- [ ] Add tests for manual correction list/detail pages
- [ ] Add tests for operator guidance fallback as “Unclassified signal” if implemented

---

## Current Status

The dashboard is ready as a safe operator UI for controlled production usage, assuming the bot-side Wave 4 backend/CLI and `bot.manual_corrections` table are deployed.

Main remaining blockers before scaling capital:

1. DB grants hardening
2. Bot-owned alerting
3. Normalized Fees (USDT) card
4. App/module split for maintainability
