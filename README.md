# Binance Bot Django Dashboard

Django dashboard for observing and operating the Binance Python Bot through a shared database contract.

The dashboard is a **consumer/operator UI**. It must not execute trading logic, call Binance for trading decisions, or mutate bot-owned accounting tables directly.

---

## Current Scope

- Authenticated dashboard overview
- Bot health/status cards
- Portfolio summary
- Recent operations/latest trade
- Fees by asset
- Drift alerts between `bot.portfolio` and `bot.position_lots`
- Dust / residual dashboard from `bot.dust_detections`
- Dust signal detail page
- Manual review actions:
  - mark ignored
  - review later
- Manual correction request workflow through `bot.manual_corrections`
- Manual correction list/detail views
- Staff-only correction request creation

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
- SELL coverage must never be inferred from `portfolio`.
- The dashboard must not directly update:
  - `bot.position_lots`
  - `bot.trade_operations`
  - `bot.trade_fills`
  - `bot.lot_closures`
  - `bot.portfolio`
- The dashboard may create `PENDING` rows in `bot.manual_corrections` only through the explicit review workflow.
- The bot-side CLI/service applies or rejects corrections.

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

---

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Run tests:

```bash
python manage.py test core
```

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
