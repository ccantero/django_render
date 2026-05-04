# Django Dashboard — Architecture

## 1. Purpose

The Django project is the operational dashboard for the Binance Python Bot.

It provides visibility, review, and request workflows over bot-owned database tables. It is not a trading engine.

---

## 2. System Boundary

### Dashboard responsibilities

- Read bot health and trading state.
- Display portfolio, lots, trades, fees, drift, and dust detections.
- Display grouped dust/residual signals with operator guidance.
- Record manual review state.
- Create explicit `PENDING` manual correction requests.

### Dashboard non-responsibilities

- No Binance trading.
- No BUY/SELL execution.
- No FIFO accounting mutation.
- No direct correction of lots.
- No direct mutation of bot accounting tables.
- No alert routing as a dependency for the bot.

---

## 3. Recommended App Structure

Current code may still live mostly under `core`, but the preferred evolution is:

```text
core/
  auth/base/shared utilities

dashboard/
  views.py
  read_models.py
  templates/dashboard/
  forms.py

bot_shared/
  managed=False models for bot-owned tables

bot_control/
  optional safe control-plane UI
```

This split is P2 tech debt, not an immediate blocker.

---

## 4. Data Access Pattern

The dashboard reads a shared database.

```text
Bot writes bot.* tables
Dashboard reads bot.* tables
Dashboard may insert PENDING manual correction requests
Bot applies corrections
```

Use `managed = False` for existing bot-owned tables.

---

## 5. Source of Truth Rules

- `bot.position_lots` is the accounting source of truth.
- `bot.portfolio` is a projection/read layer.
- `bot.trade_operations` is the economic operation layer.
- `bot.trade_fills` is the raw execution/audit layer.
- `bot.lot_closures` is the FIFO closure audit layer.
- `bot.dust_detections` is an observational read model.
- `bot.manual_corrections` is the manual correction request/audit workflow.

---

## 6. Dust / Drift Dashboard

The dust dashboard reads `bot.dust_detections`, groups signals, and adds operator guidance:

- Below min notional: monitor / optionally ignore
- Lots > Binance: accounting drift, needs review
- Binance > Lots: external balance, needs review
- Possible incomplete sell: inspect Binance history, then create correction request if confirmed
- Unclassified signal: inspect details before taking action

The dashboard must display uncertainty and avoid treating approximate exposure as audited PnL.

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

---

## 9. API Decision

Do not introduce a bot producer API / dashboard consumer API yet.

Current preferred integration:

```text
Shared database contract + managed=False models
```

An API may be reconsidered later for mobile clients, third-party consumers, or if the dashboard must be isolated from the database schema. It is not required for push notifications; bot-side Telegram/Pushover alerts are preferred.
