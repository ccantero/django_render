# Django Dashboard — Design Notes

## Design Principle

The dashboard is an operator console, not a trading engine.

It should make the system observable, understandable, and auditable without hiding uncertainty or mutating accounting state directly.

---

## UX Goals

- Show the current bot status quickly.
- Surface operational risks before financial KPIs.
- Make dust/drift signals understandable to a human operator.
- Prevent accidental direct DB corrections.
- Guide users toward the manual correction workflow.
- Keep all correction requests explicit and auditable.

---

## Dashboard Sections

### Main dashboard

- Bot status
- Portfolio summary
- Latest trade
- Drift summary
- Fees by asset
- Link to Dust / Residuals

### Dust / Residuals

Source: `bot.dust_detections`

Shows:

- grouped detections
- severity
- reason
- event type
- latest run id
- approximate exposure
- estimated delta
- suggested action
- review status
- operator guidance

### Dust detail

Shows latest grouped signal details:

- spot quantity
- open lot quantity
- quantity delta
- price USDT
- estimated values
- payload
- run id
- manual review actions

### Manual corrections

Source: `bot.manual_corrections`

Shows:

- pending/applied/rejected/failed correction requests
- correction detail
- request metadata
- error message if failed
- payload

---

## Operator Guidance

Guidance should favor safety:

- Never classify unknown signals as safe.
- Use “Unclassified signal / needs review” as fallback.
- Use approximate values only for prioritization.
- Display “Do not correct from DB directly. Use manual correction workflow.”

Recommended labels:

- Below min notional
- Lots > Binance
- Binance > Lots
- Possible incomplete sell
- Unclassified signal

---

## Manual Correction Request Design

The dashboard form creates only a request.

It must show a safety confirmation:

- This does not execute Binance orders.
- This does not convert dust.
- This is an accounting correction request.
- Bot-owned service/CLI must apply it.

For `CLOSE_LOTS_EXTERNAL_SELL`, prefill quantity only when safe:

```text
quantity = open_lot_quantity - spot_quantity
only when open_lot_quantity > spot_quantity
```

Never prefill a negative quantity.

---

## Decimal and Formatting Rules

- Treat financial values as Decimal.
- Round only for display.
- Do not write rounded display values back to DB.
- Do not recalculate trading PnL in the dashboard unless the contract defines the source fields.

---

## Notifications

Notifications should be produced by the bot directly. The dashboard should display alert state but should not be a required relay for critical events.

Preferred:

```text
Bot -> Telegram/Pushover
Dashboard -> review UI
```
