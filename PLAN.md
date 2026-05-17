# Project Plan

## Current Goal

Maintain a Django dashboard that observes and operates around Binance bot database state while preserving the hard boundary that trading logic and bot-owned accounting mutations remain outside this project.

Current governance goal: enforce the non-optional Codex workflow of planner, implementer, tester, and documentator for all future tasks.

## Priority Model

- P0: safety, correctness, and production access controls.
- P1: operator workflows and dashboard visibility needed for day-to-day use.
- P2: maintainability, scale, and architecture cleanup.
- P3: UX polish and convenience improvements.

## Completed Work

- Django project configured with `core`, `dashboard`, `currencyconverter`, and `profile` apps.
- Authenticated dashboard, dust/residual review, and manual correction request pages exist in `dashboard`.
- Home/auth-adjacent pages, Telegram webhook listener, bot-control endpoints, and bot-owned table mappings remain in `core`.
- DRF endpoints exist for user profiles and currency/exchange-rate resources.
- drf-spectacular schema and Swagger views are wired at `/api/schema` and `/api/docs`.
- Test configuration exists for Django test runner and pytest-django.
- Project documentation exists for architecture, design, project state, and the shared bot data contract.
- Strict Codex workflow files were added under `AGENTS.md`, `.codex/skills/`, and `.codex/subagents/`.
- Dashboard requires login for operational views.
- Dust / residual dashboard reads `bot.dust_detections`.
- Telegram mobile diagnostics commands read shared bot state through the existing webhook:
  `/help`, `/health`, `/buy_status`, `/position SYMBOL`, `/last_sell SYMBOL`, and `/why_not_sell SYMBOL`.
- Telegram diagnostics expose a compact `/help` guide and present skipped/rejected
  SELL explanations with a mobile-first summary before raw event details.
- Telegram mobile diagnostics now also support `/buy_status` for conservative
  BUY capacity visibility from healthcheck position classification data.
- Telegram diagnostics use compact Decimal-safe display formatting for prices,
  quantities, percentages, USDT values, and drift values.
- Manual correction request creation is staff/superuser-only.
- Manual correction request form is POST and CSRF protected.
- Dashboard does not apply manual corrections or mutate bot accounting tables directly.
- `ManualCorrection` is aligned to bot-owned `bot.manual_corrections`.
- Manual correction requests validate positive quantity and never prefill a negative correction quantity.
- Dust / drift workflow supports grouped detections, latest run metadata, detail payloads, operator guidance, ignored/review-later actions, linked correction status, and manual correction request links.
- Main dashboard dust UX now shows compact Active Operational Issues from unresolved critical/warning signals only, with info-only residuals summarized as counts/exposure while the dedicated Dust / Residuals page carries the full grouped table with filters and 25-row pagination.
- Dust correction request links are disabled in the UI when the latest detection already has a linked `PENDING` or `APPLIED` correction; bot-side duplicate validation remains authoritative.
- Main dashboard is now a concise operator console with normalized Bot Health status badges, Inventory Integrity, Performance Snapshot, latest four operations, active dust/drift issues, and informational residual counts.
- Main dashboard includes a read-only “Why positions are not selling” table that separates dust/minNotional blockers, strategy holds, and review-needed drift from latest persisted SELL diagnostics.
- Main dashboard keeps exit-status diagnostics disabled by default for latency and links to `/dashboard/exit-status/`, which uses a bounded recent diagnostics read.
- Read-only churn observability exists at `/dashboard/churn/`, with homepage summary counts for recent SELL→BUY re-entry under 15 minutes.
- `/buy_status` and dashboard BUY/cooldown cards render the three stable anti-churn re-entry cooldown reasons from latest healthcheck details.
- Position exit status now maps known SELL reasons to operator-facing labels, interpretations, and suggested actions, including anomaly handling for invalid positive-PnL stop-loss diagnostics.
- Telegram SELL diagnostics and dust/drift alert templates now favor compact human-readable interpretation plus next-step guidance while preserving raw diagnostic fields.
- Analytics dashboard exists at `/dashboard/analytics/` for read-only KPI detail, fees, PnL by symbol, and PnL by day sourced from `bot.lot_closures` and `bot.trade_operations`.
- Operational Trading KPIs v2 exists at `/dashboard/operational-kpis/` for filtered read-only strategy-version, hold-time, churn, and fee-efficiency analysis.
- Monitoring cards exist for bot status, portfolio summary, valuation consistency, latest operation/recent trade, and drift alerts.
- Tests cover dashboard access, manual correction permissions, form validation, model contract alignment, drift prefill behavior, and environment validation.
- Public `/health/` liveness endpoint exists for Render keepalive/cron pings.
- The dashboard-created `CLOSE_LOTS_EXTERNAL_SELL` request flow was validated on 2026-05-08 with an ASIACOIN / `币安人生USDT` dust-closure case: dashboard request creation, bot CLI dry-run/confirmed apply, and post-apply dashboard state review all preserved the dashboard/bot boundary.

## P0 Safety / Correctness

1. Review production DB grants for `anon` and `authenticated` roles.
2. Ensure the dashboard DB user cannot write bot accounting tables.
3. Run and keep the full test suite green before application behavior changes.
4. Continue updating `docs/DATA_CONTRACT.md` whenever bot-owned table interpretation changes.

## P1 Operator Workflow

1. Add manual corrections pending count to the main dashboard.
2. Add detailed lots summary from `position_lots`.
3. Show linked source dust detection detail from correction detail.
4. Add filter for operator guidance category.
5. Add better pagination for large detection history.
6. Continue enriching SELL diagnostics only through persisted bot-owned `sell_decision_events`; dashboard display is read-only.
7. Extend Telegram diagnostics only with additional read-only DB-backed views when the shared contract exposes them.
8. Persist a stable latest BUY decision surface from the bot so `/buy_status`
   can distinguish `no_candidate` and `execution_error` without relying on
   best-effort healthcheck detail fields.
9. Add explicit confirmation checkbox in the correction form if extra operator friction is desired.
10. Add clearer labels for Binance Small Amount Exchange / manual dust conversion cases currently represented by broader reasons such as `earn_or_external_transfer`.
11. Add dashboard action to mark a request as rejected only if the shared contract allows dashboard-side rejection.
12. Consider paginating or date-filtering performance KPI history if `bot.lot_closures` grows large.

## P2 Architecture / Tech Debt

1. Verify Docker files before relying on them for local development or deployment.
2. Continue the app split by moving bot-owned table mappings from `core` into a dedicated `bot_shared` app when that migration risk is explicitly planned.
3. Consider the remaining target app structure: `bot_shared`, `bot_control`, and `core`.
4. Keep dashboard read-model code in dashboard-specific modules.
5. Keep all bot-owned models `managed = False`.
6. Avoid migrations for bot-owned tables unless ownership intentionally changes.
7. Review N+1 query patterns.
8. Add pagination for manual correction lists.
9. Standardize template partials/components.
10. Add integration test coverage against a PostgreSQL-like schema if practical.
11. Add focused tests for manual correction list/detail pages.
12. Add or keep tests for operator guidance fallback as `Unclassified signal`.

## P2 Alerts / Notifications

1. Keep dashboard out of the critical alert relay path.
2. Implement alerting in the bot project first.
3. Display alert history in the dashboard only if the bot persists alert events.
4. Consider Telegram/Pushover alert state cards after bot-side implementation.

## P3 UX Improvements

1. Add clearer empty states.
2. Add stronger visual distinction between approximate exposure and audited financials.
3. Add inline help text for each dust reason.
4. Add an action checklist in the dust detail page.
5. Add breadcrumbs across dashboard and manual correction pages.
6. Improve mobile layout for operator usage.
7. Add export/download for reviewed dust signals if useful.

## Open Issues

- Existing Docker files appear older than the current project layout and may need validation before use.
- No Celery or Redis integration is currently present.
- No Django management commands are currently present.
- The dashboard relies on external bot-owned tables for production data.
- Some bot-owned models use `managed = False`; migrations must not be generated for those tables unless ownership intentionally changes.
- Performance KPIs are operational metrics only; fee normalization excludes non-USDT/unavailable conversions, PnL by day depends on linked trade operation timestamps, and manual corrections are split only when identifiable from operation metadata.
- Operational Trading KPIs v2 exclude identifiable manual/accounting-only corrections from trading-quality metrics, group missing strategy metadata as `unversioned`, and ignore missing timestamps for hold-time/churn calculations.
- The dashboard is ready as a safe operator UI for controlled production usage only if the bot-side backend/CLI and `bot.manual_corrections` table are deployed.
- Historical `dust_detections` rows remain visible after correction, so operator views should continue distinguishing active/latest signals from audit history.
- Dust review/ignore state suppresses paging only; detections remain persisted as audit history and do not mutate accounting state.
