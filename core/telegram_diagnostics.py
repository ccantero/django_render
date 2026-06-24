import logging
import os
import re
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Avg, Q, Sum
from django.utils import timezone

from core.trading_models import (
	BotHealthcheck,
	DustDetection,
	LotClosure,
	Portfolio,
	PositionLot,
	SellDecisionEvent,
	Snapshot,
	TradeOperation,
)
from dashboard.services.telegram_buy_status_formatter import (
	build_open_positions_pnl,
	build_buy_status_exposure,
	build_cooldown_diagnostics,
	build_cooldown_lines,
	build_inventory_warning_lines,
	classify_buy_status_positions,
	render_buy_status_message,
)
from dashboard.services.telegram_portfolio_status import (
	PortfolioEquityChartRenderer,
	PortfolioEquityHistoryBuilder,
	build_portfolio_status,
	render_portfolio_status,
)


logger = logging.getLogger(__name__)

DIAGNOSTIC_COMMANDS = {
	"/help",
	"/health",
	"/position",
	"/last_sell",
	"/why_not_sell",
	"/buy_status",
	"/portfolio_status",
}
REJECTED_SELL_EVENTS = [
	"sell_signal_rejected",
	"sell_order_skipped",
	"sell_skipped_not_profitable",
]
SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}$")
SELL_REASON_PRESENTATION = {
	"stop_loss_not_reached": ("Holding", "Stop loss has not been reached. Current loss is still inside the configured stop-loss threshold.", "No action. Continue monitoring."),
	"take_profit_not_reached": ("Holding", "Take profit has not been reached yet.", "No action. Continue monitoring."),
	"rounded_quantity_zero": ("Dust / Unsellable", "Quantity rounds to zero after exchange step-size rules.", "Review as dust. Ignore, wait until reusable, or handle through manual correction if drift exists."),
	"quantity_below_min_notional": ("Dust / Below minNotional", "Position value is below Binance minimum notional.", "Review as dust. It may become reusable if future buys increase the balance."),
	"quantity_below_min_qty": ("Dust / Below minQty", "Quantity is below Binance minimum quantity.", "Review as dust."),
	"insufficient_binance_balance": ("Drift / Review needed", "Binance SPOT balance is lower than open lots.", "Review for manual/external operation, Earn movement, fee residual, or incomplete sell."),
	"no_open_lots": ("No accounting inventory", "No open FIFO lots exist for this symbol.", "No sell is possible from bot accounting."),
	"exchange_filter_missing": ("Metadata issue", "Exchange filter metadata is unavailable.", "Review exchange metadata/scanner cache."),
	"read_only": ("Read-only", "Bot is in READ_ONLY mode.", "No live orders will be submitted."),
	"strategy_hold": ("Holding", "Strategy decided to hold.", "No action."),
}
DUST_REASON_PRESENTATION = {
	"manual_external_operation": ("Manual / external operation", "Binance balance changed outside the normal bot BUY/SELL flow.", "Review Binance history. If intentional and material, create the proper manual correction. If tiny dust, review/ignore."),
	"possible_incomplete_sell": ("Possible incomplete sell", "Bot lots and Binance SPOT may not fully reconcile after a SELL.", "Review urgently. Check recent SELL, lot closures, and Binance balance."),
	"earn_or_external_transfer": ("Earn / external transfer", "Asset may have moved outside immediately tradable SPOT inventory.", "Review Binance Earn/SPOT movement. Do not auto-correct without confirmation."),
	"below_min_notional": ("Below minNotional", "Position is too small to sell under Binance filters.", "Usually no action. Review/ignore or wait until future buys make it reusable."),
	"balance_without_lot_coverage": ("Binance balance without bot lot", "Binance has SPOT inventory not represented in bot FIFO lots.", "If this should become bot-managed inventory, request CREATE_EXTERNAL_LOT."),
	"lot_balance_drift": ("Lot / balance drift", "Open lots and Binance SPOT balance differ.", "Review drift direction. Use CREATE_EXTERNAL_LOT if Binance > lots, or CLOSE_LOTS_EXTERNAL_SELL if lots > Binance."),
}
BUY_COOLDOWN_REASON_PRESENTATION = {
	"loss_reentry_cooldown_active": "Re-entry blocked after loss/stop-loss cooldown",
	"take_profit_reentry_cooldown_active": "Re-entry blocked after take-profit cooldown",
	"sell_reentry_cooldown_active": "Re-entry blocked after recent sell cooldown",
}


def diagnostic_response(text, chat_id, user_id=None):
	command, args = _parse_command(text)
	if command not in DIAGNOSTIC_COMMANDS:
		return None

	logger.info(
		"Telegram diagnostics command",
		extra={"command": command, "chat_id": chat_id, "user_id": user_id},
	)

	if not is_authorized_telegram_actor(chat_id, user_id):
		return "Unauthorized diagnostics request."

	if command == "/health":
		return format_health()
	if command == "/help":
		return format_help()
	if command == "/buy_status":
		return format_buy_status()
	if command == "/portfolio_status":
		return format_portfolio_status()

	symbol = args[0] if args else ""
	if not is_valid_symbol(symbol):
		return "Invalid symbol. Use uppercase letters/numbers, max 20 chars."

	if command == "/position":
		return format_position(symbol)
	if command == "/last_sell":
		return format_last_sell(symbol)
	if command == "/why_not_sell":
		return format_why_not_sell(symbol)

	return None


def is_authorized_telegram_actor(chat_id, user_id=None):
	allowed_chat_ids = _setting_id_set("TELEGRAM_ALLOWED_CHAT_IDS")
	allowed_user_ids = _setting_id_set("TELEGRAM_ALLOWED_USER_IDS")
	chat_id = str(chat_id)
	user_id = str(user_id) if user_id is not None else None

	if chat_id in allowed_chat_ids:
		return True
	if user_id and user_id in allowed_user_ids:
		return True
	return False


def is_valid_symbol(symbol):
	return bool(SYMBOL_RE.fullmatch(symbol or ""))


def format_health():
	latest = BotHealthcheck.objects.order_by("-created_at", "-id").first()
	if latest is None:
		return "<b>⚪ Bot health</b>\n\nStatus: <code>unknown</code>"

	now = timezone.now()
	created_at = latest.created_at
	age = now - created_at if created_at else None
	stale_after_minutes = getattr(settings, "HEALTHCHECK_STALE_MINUTES", 15)
	status_text = (latest.status or "unknown").lower()

	if status_text in {"error", "failed", "critical"}:
		emoji = "🔴"
		status_label = "error"
	elif age is not None and age.total_seconds() > stale_after_minutes * 60:
		emoji = "🟡"
		status_label = "stale"
	elif status_text in {"ok", "healthy", "success"}:
		emoji = "🟢"
		status_label = "healthy"
	else:
		emoji = "⚪"
		status_label = "unknown"

	details = latest.details or {}
	counts = [
		details.get("positions_count"),
		details.get("material_positions_count"),
		details.get("dust_positions_count"),
		details.get("unknown_value_positions_count"),
	]

	lines = [
		f"<b>{emoji} Bot health</b>",
		"",
		f"Status: <code>{h(status_label)}</code>",
		f"Latest: <code>{h(format_dt(created_at))}</code>",
		f"Age: <code>{h(format_age(age))}</code>",
		f"Run: <code>{h(details.get('run_id') or getattr(latest, 'run_id', None) or 'N/A')}</code>",
	]
	if any(value is not None for value in counts):
		lines.append(
			"raw/material/dust/unknown: "
			f"<code>{h('/'.join(fmt_count(value) for value in counts))}</code>"
		)
	return "\n".join(lines)


def format_help():
	return "\n".join([
		"<b>🤖 Bot commands</b>",
		"",
		"<b>General</b>",
		"• /start — greet the user",
		"• /help — show this guide",
		"",
		"<b>Status</b>",
		"• /health — bot heartbeat and position counts",
		"• /buy_status — BUY capacity and blockers",
		"• /portfolio_status — portfolio performance summary",
		"",
		"<b>Symbol diagnostics</b>",
		"• /position SYMBOL — quantity, value, and drift",
		"• /last_sell SYMBOL — latest SELL diagnostic",
		"• /why_not_sell SYMBOL — latest skipped/rejected SELL reason",
		"",
		"<b>Legacy</b>",
		"• /getmyinvest — placeholder, not implemented yet",
		"",
		"Example: <code>/position XRPUSDT</code>",
	])


def format_buy_status():
	realized_today = _safe_realized_pnl_today()
	latest = BotHealthcheck.objects.order_by("-created_at", "-id").first()
	if latest is None:
		return render_buy_status_message(
			emoji="⚪",
			raw_count=None,
			material_count=None,
			dust_count=None,
			unknown_count=None,
			effective_positions=None,
			max_positions=None,
			remaining_capacity=None,
			free_usdt=None,
			latest_buy_state="unavailable",
			latest_buy_reason="unavailable",
			latest_buy_symbol="unavailable",
			read_only=False,
			exposure=build_buy_status_exposure([], [], []),
			status_lines=["⚪ Diagnostic unavailable: latest healthcheck missing"],
			realized_today=realized_today,
			unknown_value_symbols=[],
		)

	details = latest.details or {}
	classification = _buy_classification_from_details(details)
	if not classification["has_healthcheck_counts"]:
		classification = _buy_classification_from_portfolio()

	raw_count = classification["raw_count"]
	material_count = classification["material_count"]
	dust_count = classification["dust_count"]
	unknown_count = classification["unknown_count"]
	max_positions = _resolve_max_positions(details)
	free_usdt = _details_first(details, [
		"free_usdt",
		"available_usdt",
		"free_capital_usdt",
		"available_capital_usdt",
		"capital.free_usdt",
		"balances.USDT.free",
	])
	latest_buy_decision = latest_buy_decision_from_details(details)
	latest_buy_reason = latest_buy_reason_from_details(details)
	if latest_buy_reason is None:
		latest_buy_reason = latest_buy_rejection_reason()
	effective_positions = _effective_positions(material_count, unknown_count)
	remaining_capacity = details.get("remaining_buy_capacity")
	if remaining_capacity is None:
		remaining_capacity = _remaining_capacity(max_positions, effective_positions)
	read_only = _resolve_read_only(details)
	state_label, emoji, reason = interpret_buy_state(
		raw_count=raw_count,
		material_count=material_count,
		max_positions=max_positions,
		free_usdt=free_usdt,
		unknown_count=unknown_count,
		read_only=read_only,
		min_required_buy_amount=_resolve_min_required_buy_amount(details),
		latest_buy_decision=latest_buy_decision,
		latest_buy_reason=latest_buy_reason,
		latest_buy_error=_latest_buy_error(details),
	)

	exposure_symbols = list(dict.fromkeys(classification["material_symbols"] + classification["dust_symbols"]))
	try:
		portfolio_rows = list(Portfolio.objects.filter(symbol__in=exposure_symbols)) if exposure_symbols else []
	except DatabaseError:
		logger.debug("Could not read portfolio rows for Telegram BUY status exposure")
		portfolio_rows = []
	exposure = build_buy_status_exposure(
		classification["material_symbols"],
		classification["dust_symbols"],
		portfolio_rows,
	)
	status_lines = _buy_status_lines(
		remaining_capacity=remaining_capacity,
		latest_buy_state=latest_buy_decision,
		latest_buy_reason=latest_buy_reason,
		read_only=read_only,
		state_label=state_label,
	)
	human_reason = BUY_COOLDOWN_REASON_PRESENTATION.get(str(latest_buy_reason or "").strip().lower())
	cooldown_lines = []
	if human_reason:
		cooldown_lines = build_cooldown_lines(build_cooldown_diagnostics(details, human_reason))
	return render_buy_status_message(
		emoji=emoji,
		raw_count=raw_count,
		material_count=material_count,
		dust_count=dust_count,
		unknown_count=unknown_count,
		effective_positions=effective_positions,
		max_positions=max_positions,
		remaining_capacity=remaining_capacity,
		free_usdt=free_usdt,
		latest_buy_state=latest_buy_decision,
		latest_buy_reason=latest_buy_reason,
		latest_buy_symbol=details.get("latest_buy_symbol"),
		read_only=read_only,
		exposure=exposure,
		status_lines=status_lines,
		open_positions_pnl=build_open_positions_pnl(exposure),
		realized_today=realized_today,
		latest_buy_error_class=details.get("latest_buy_error_class"),
		latest_buy_error_code=details.get("latest_buy_error_code"),
		unknown_value_symbols=classification["unknown_symbols"],
		cooldown_lines=cooldown_lines,
		inventory_warning_lines=build_inventory_warning_lines(
			((details.get("reconciliation") or {}).get("inventory_warnings"))
			if isinstance(details.get("reconciliation"), dict)
			else []
		),
	)


def format_portfolio_status():
	realized_today = _safe_realized_pnl_today()
	realized_drivers = _safe_realized_pnl_by_symbol_today()
	free_usdt = None
	now = timezone.now()
	stale_after = timedelta(
		minutes=getattr(settings, "HEALTHCHECK_STALE_MINUTES", 15),
	)
	try:
		latest = BotHealthcheck.objects.order_by("-created_at", "-id").first()
		details = latest.details or {} if latest is not None else {}
		created_at = getattr(latest, "created_at", None)
		if created_at is not None and now - created_at <= stale_after:
			free_usdt = _details_first(details, [
				"free_usdt",
				"available_usdt",
				"free_capital_usdt",
				"available_capital_usdt",
				"capital.free_usdt",
				"balances.USDT.free",
			])
	except DatabaseError:
		logger.debug("Could not read free USDT for Telegram portfolio status")

	try:
		open_lots = list(
			PositionLot.objects
			.filter(remaining_quantity__gt=0)
			.order_by("symbol", "opened_at", "lot_id")
		)
	except DatabaseError:
		logger.debug("Could not read open lots for Telegram portfolio status")
		open_lots = None

	portfolio_rows = None
	if open_lots is not None:
		symbols = list(dict.fromkeys(lot.symbol for lot in open_lots))
		try:
			portfolio_rows = list(Portfolio.objects.filter(symbol__in=symbols)) if symbols else []
		except DatabaseError:
			logger.debug("Could not read portfolio prices for Telegram portfolio status")

	equity_history = {"changes": {"24h": None, "7d": None, "30d": None}, "chart_points": []}
	try:
		snapshot_rows = list(
			Snapshot.objects
			.filter(
				source="bot_cycle",
				created_at__gte=now - timedelta(days=35),
				created_at__lte=now,
			)
			.order_by("created_at", "id")
		)
		equity_history = PortfolioEquityHistoryBuilder(as_of=now).build(snapshot_rows)
	except DatabaseError:
		logger.debug("Could not read snapshots for Telegram portfolio status")

	summary = build_portfolio_status(
		open_lots=open_lots,
		portfolio_rows=portfolio_rows,
		free_usdt=free_usdt,
		realized_today=realized_today,
		realized_drivers=realized_drivers,
		equity_history=equity_history,
		as_of=now,
		stale_after=stale_after,
	)
	text = render_portfolio_status(summary)
	photo = None
	if summary.get("chart_available"):
		try:
			photo = PortfolioEquityChartRenderer().render_png(summary.get("chart_points") or [])
		except Exception:
			logger.debug("Could not render Telegram portfolio equity chart", exc_info=True)
			if "Chart: unavailable" not in text:
				text = text + "\nChart: unavailable, generation failed"
	return {"text": text, "photo": photo}


def _safe_realized_pnl_today():
	try:
		utc_day = timezone.now().astimezone(datetime_timezone.utc).date()
		return realized_pnl_for_day(utc_day)
	except DatabaseError:
		logger.debug("Could not read realized PnL for Telegram BUY status")
		return None


def _safe_realized_pnl_by_symbol_today():
	try:
		utc_day = timezone.now().astimezone(datetime_timezone.utc).date()
		return realized_pnl_by_symbol_for_day(utc_day)
	except DatabaseError:
		logger.debug("Could not read realized PnL drivers for Telegram portfolio status")
		return None


def realized_pnl_for_day(day):
	start = datetime.combine(day, time.min, tzinfo=datetime_timezone.utc)
	end = start + timedelta(days=1)
	operation_ids = (
		TradeOperation.objects
		.filter(
			Q(executed_at__gte=start, executed_at__lt=end)
			| Q(
				executed_at__isnull=True,
				created_at__gte=start,
				created_at__lt=end,
			)
		)
		.values_list("id", flat=True)
	)
	result = LotClosure.objects.filter(
		trade_operation_id__in=operation_ids,
	).aggregate(total=Sum("realized_pnl"))
	return result["total"] or Decimal("0")


def realized_pnl_by_symbol_for_day(day):
	start = datetime.combine(day, time.min, tzinfo=datetime_timezone.utc)
	end = start + timedelta(days=1)
	operation_ids = (
		TradeOperation.objects
		.filter(
			Q(executed_at__gte=start, executed_at__lt=end)
			| Q(
				executed_at__isnull=True,
				created_at__gte=start,
				created_at__lt=end,
			)
		)
		.values_list("id", flat=True)
	)
	rows = (
		LotClosure.objects
		.filter(trade_operation_id__in=operation_ids)
		.values("symbol")
		.annotate(total=Sum("realized_pnl"))
		.order_by("symbol")
	)
	return [
		{"symbol": row["symbol"], "pnl_usdt": row["total"]}
		for row in rows
		if row.get("symbol") and row.get("total") is not None
	]


def format_position(symbol):
	portfolio = Portfolio.objects.filter(symbol=symbol).first()
	lot_summary = PositionLot.objects.filter(
		symbol=symbol,
		remaining_quantity__gt=0,
	).aggregate(
		open_quantity=Sum("remaining_quantity"),
		entry_price=Avg("entry_price"),
	)
	latest_dust = (
		DustDetection.objects
		.filter(symbol=symbol)
		.order_by("-detected_at", "-created_at", "-id")
		.first()
	)

	portfolio_qty = getattr(portfolio, "quantity", None)
	open_qty = lot_summary.get("open_quantity") or Decimal("0")
	current_price = getattr(portfolio, "current_price", None)
	entry_price = getattr(portfolio, "entry_price", None) or lot_summary.get("entry_price")
	estimated_value = _decimal_product(portfolio_qty, current_price)
	drift = _decimal_diff(portfolio_qty, open_qty)

	lines = [
		f"<b>📍 Position — {h(symbol)}</b>",
		"",
		f"Portfolio qty: <code>{h(fmt_qty(portfolio_qty))}</code>",
		f"Open lots: <code>{h(fmt_qty(open_qty))}</code>",
		f"Price: <code>{h(fmt_price(current_price))}</code>",
		f"Value: <code>{h(fmt_usdt(estimated_value))}</code>",
		f"Entry: <code>{h(fmt_price(entry_price))}</code>",
		f"Drift: <code>{h(fmt_drift(drift))}</code>",
	]
	if latest_dust:
		lines.extend([
			"",
			"<b>Latest dust/drift</b>",
			f"Type: <code>{h(getattr(latest_dust, 'event_type', None))}</code>",
			f"Reason: <code>{h(getattr(latest_dust, 'reason', None))}</code>",
			f"When: <code>{h(format_dt(getattr(latest_dust, 'detected_at', None)))}</code>",
		])
	return "\n".join(lines)


def format_last_sell(symbol):
	event = latest_sell_event(symbol)
	if event is None:
		return f"<b>🔴 SELL diagnostic — {h(symbol)}</b>\n\nNo SELL diagnostic found."
	return format_sell_event("🔴 SELL diagnostic", symbol, event, include_interpretation=True)


def format_why_not_sell(symbol):
	event = (
		SellDecisionEvent.objects
		.filter(symbol=symbol, event_name__in=REJECTED_SELL_EVENTS)
		.order_by("-created_at", "-id")
		.first()
	)
	if event is None:
		return f"<b>🤔 Why not sell — {h(symbol)}</b>\n\nNo rejected/skipped SELL event found."

	status, interpretation, suggested_action = sell_reason_presentation(event)
	payload = getattr(event, "payload", None) or {}
	asset = payload.get("asset") or _asset_from_symbol(symbol)
	return "\n".join([
		f"<b>🤔 Why not sell — {h(symbol)}</b>",
		"",
		f"Status: <code>{h(status)}</code>",
		f"Event: <code>{h(getattr(event, 'event_name', None))}</code>",
		f"Reason: <code>{h(getattr(event, 'reason', None))}</code>",
		f"Stage: <code>{h(getattr(event, 'validation_stage', None))}</code>",
		f"PnL: <code>{h(fmt_percent(getattr(event, 'estimated_pnl_percent', None)))}</code>",
		"",
		"Interpretation:",
		h(interpretation),
		"",
		"Suggested action:",
		h(suggested_action),
		"",
		"Details:",
		f"• Strategy: <code>{h(payload.get('strategy_name'))}</code>",
		f"• Estimated value: <code>{h(fmt_usdt(payload.get('estimated_value_usdt')))}</code>",
		f"• Open lot qty: <code>{h(fmt_qty(payload.get('open_lot_quantity')))} {h(asset)}</code>",
		f"• Last diagnostic: <code>{h(format_dt(getattr(event, 'created_at', None)))}</code>",
	])


def latest_sell_event(symbol):
	return (
		SellDecisionEvent.objects
		.filter(symbol=symbol)
		.order_by("-created_at", "-id")
		.first()
	)


def format_sell_event(title, symbol, event, include_interpretation=False):
	lines = [
		f"<b>{title} — {h(symbol)}</b>",
		"",
		f"Event: <code>{h(getattr(event, 'event_name', None))}</code>",
		f"Reason: <code>{h(getattr(event, 'reason', None))}</code>",
		f"Stage: <code>{h(getattr(event, 'validation_stage', None))}</code>",
		f"PnL: <code>{h(fmt_percent(getattr(event, 'estimated_pnl_percent', None)))}</code>",
		f"Entry: <code>{h(fmt_price(getattr(event, 'entry_price', None)))}</code>",
		f"Current: <code>{h(fmt_price(getattr(event, 'current_price', None)))}</code>",
		f"Stop: <code>{h(fmt_percent(getattr(event, 'stop_loss_threshold', None)))}</code>",
		f"Take profit: <code>{h(fmt_percent(getattr(event, 'take_profit_threshold', None)))}</code>",
		f"Profit guard: <code>{h(format_profit_guard(getattr(event, 'profit_guard_bypassed', None)))}</code>",
		f"Created: <code>{h(format_dt(getattr(event, 'created_at', None)))}</code>",
	]
	if include_interpretation:
		lines.extend(["", "Interpretation:", h(interpret_sell_event(event))])
	return "\n".join(lines)


def explain_rejection(event):
	text = " ".join(
		str(value or "").lower()
		for value in [
			getattr(event, "event_name", None),
			getattr(event, "reason", None),
			getattr(event, "validation_stage", None),
		]
	)
	explanations = []
	if "profit_guard" in text or "not_profitable" in text:
		explanations.append("Profit guard blocked")
	if "min_notional" in text or "minnotional" in text:
		explanations.append("Exchange minNotional blocked")
	if "rounded" in text and "zero" in text:
		explanations.append("Rounded quantity zero")
	if "no_open_lot" in text or "no open lot" in text:
		explanations.append("No open lots")
	if "insufficient" in text and "balance" in text:
		explanations.append("Insufficient Binance balance")
	if "read_only" in text or "readonly" in text:
		explanations.append("Read-only mode")
	if "hold" in text:
		explanations.append("Strategy hold")
	return explanations or ["Unknown"]


def sell_reason_presentation(event):
	reason = str(getattr(event, "reason", "") or "").strip().lower()
	pnl = to_decimal(getattr(event, "estimated_pnl_percent", None))
	if reason == "stop_loss_reached" and pnl is not None and pnl > 0:
		return (
			"Anomaly",
			"Invalid diagnostic state. Stop-loss should only trigger on real losses.",
			"Review bot version and stop-loss normalization.",
		)
	return SELL_REASON_PRESENTATION.get(
		reason,
		("Review", "Diagnostic reason is not mapped yet.", "Review latest sell_decision_events payload."),
	)


def format_dust_drift_alert(values):
	reason = str(values.get("reason") or "").strip().lower()
	label, interpretation, suggested_action = DUST_REASON_PRESENTATION.get(
		reason,
		("Review", "Diagnostic reason is not mapped yet.", "Review latest dust detection payload."),
	)
	severity = str(values.get("severity") or "info").lower()
	severity_label = {
		"critical": "🔴 Critical",
		"warning": "⚠️ Warning",
		"info": "ℹ️ Info",
	}.get(severity, "ℹ️ Info")
	title_emoji = {
		"critical": "🔴",
		"warning": "⚠️",
		"info": "ℹ️",
	}.get(severity, "ℹ️")
	estimated_value = to_decimal(values.get("estimated_value_usdt"))
	tiny_value = estimated_value is not None and estimated_value < Decimal("0.01")
	if tiny_value and severity != "critical":
		interpretation = (
			f"A tiny {values.get('asset') or 'asset'} balance difference was detected between Binance SPOT and bot accounting. "
			"The value is a tiny dust value, so this is likely operational dust unless quantity drift is material."
		)
		suggested_action = (
			"Review in dashboard. If this is already reviewed/ignored, suppress the alert through dust signal review. "
			"Do not create a manual correction unless the quantity/value is meaningful or the drift persists unexpectedly."
		)
	return "\n".join([
		f"<b>{title_emoji} Dust / drift detected — {h(values.get('symbol'))}</b>",
		"",
		f"Status: <code>{h(severity_label)}</code>",
		f"Reason: <code>{h(label if label != 'Review' else reason or label)}</code>",
		f"Estimated value: <code>{h(fmt_usdt_precise(estimated_value))}</code>",
		"",
		"Interpretation:",
		h(interpretation),
		"",
		"Suggested action:",
		h(suggested_action),
		"",
		"Details:",
		f"• Asset: <code>{h(values.get('asset'))}</code>",
		f"• Event: <code>{h(values.get('event') or values.get('event_type'))}</code>",
		f"• Run ID: <code>{h(values.get('run_id'))}</code>",
	])


def interpret_sell_event(event):
	reason = str(getattr(event, "reason", "") or "").lower()
	stage = str(getattr(event, "validation_stage", "") or "").lower()
	if "min_notional" in reason or "minnotional" in reason:
		return "⚠️ Stop-loss was detected but blocked by exchange minNotional."
	if "approved" in stage:
		return "✅ Stop-loss was allowed to sell."
	return "ℹ️ Review the diagnostic fields before acting."


def _parse_command(text):
	parts = (text or "").strip().split()
	if not parts:
		return "", []
	command = parts[0].split("@", 1)[0].lower()
	return command, parts[1:]


def _setting_id_set(name):
	value = getattr(settings, name, "")
	if isinstance(value, str):
		items = re.split(r"[\s,]+", value.strip()) if value.strip() else []
	else:
		items = value or []
	return {str(item).strip() for item in items if str(item).strip()}


def h(value):
	if value is None or value == "":
		return "N/A"
	return escape(str(value), quote=False)


def fmt(value):
	return fmt_decimal(value, places=8)


def fmt_price(value):
	return fmt_decimal(value, places=8)


def fmt_qty(value):
	return fmt_decimal(value, places=8)


def fmt_drift(value):
	return fmt_decimal(value, places=8)


def fmt_usdt(value):
	decimal_value = to_decimal(value)
	if decimal_value is None:
		return "N/A"
	if decimal_value == 0:
		return "0 USDT"
	places = 2 if abs(decimal_value) >= Decimal("1") else 4
	return f"{fmt_decimal(decimal_value, places=places)} USDT"


def fmt_usdt_precise(value):
	decimal_value = to_decimal(value)
	if decimal_value is None:
		return "N/A"
	places = 6 if abs(decimal_value) < Decimal("1") else 2
	return f"{fmt_decimal(decimal_value, places=places)} USDT"


def _asset_from_symbol(symbol):
	for suffix in ("USDT", "BUSD", "USDC", "BTC", "ETH"):
		if symbol.endswith(suffix) and len(symbol) > len(suffix):
			return symbol[:-len(suffix)]
	return symbol


def fmt_percent(value):
	decimal_value = to_decimal(value)
	if decimal_value is None:
		return "N/A"
	return f"{fmt_decimal(decimal_value, places=2)}%"


def fmt_count(value):
	decimal_value = to_decimal(value)
	if decimal_value is None:
		return "N/A"
	if decimal_value == decimal_value.to_integral_value():
		return str(decimal_value.to_integral_value())
	return fmt_decimal(decimal_value, places=8)


def fmt_symbol_list(value):
	if not value:
		return "none"
	if isinstance(value, str):
		items = [item.strip() for item in re.split(r"[\s,]+", value) if item.strip()]
	else:
		items = [str(item).strip() for item in value if str(item).strip()]
	return ", ".join(items) if items else "none"


def fmt_decimal(value, places=8):
	decimal_value = to_decimal(value)
	if decimal_value is None:
		return "N/A"
	if decimal_value == 0:
		return "0"
	quant = Decimal("1").scaleb(-places)
	rounded = decimal_value.quantize(quant, rounding=ROUND_HALF_UP)
	text = format(rounded, "f")
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return text or "0"


def to_decimal(value):
	if value is None or value == "":
		return None
	if isinstance(value, Decimal):
		return value
	try:
		return Decimal(str(value))
	except (InvalidOperation, ValueError, TypeError):
		return None


def format_profit_guard(value):
	if value is True:
		return "bypassed"
	if value is False:
		return "active"
	return "N/A"


def format_dt(value):
	if not value:
		return "N/A"
	return timezone.localtime(value).strftime("%Y-%m-%d %H:%M UTC")


def format_age(value):
	if value is None:
		return "N/A"
	total_seconds = max(0, int(value.total_seconds()))
	minutes = total_seconds // 60
	if minutes < 60:
		return f"{minutes}m"
	hours = minutes // 60
	return f"{hours}h {minutes % 60}m"


def _decimal_product(left, right):
	if left is None or right is None:
		return None
	return left * right


def _decimal_diff(left, right):
	if left is None and right is None:
		return None
	return (left or Decimal("0")) - (right or Decimal("0"))


def _buy_classification_from_details(details):
	classification = details.get("position_classification") if isinstance(details, dict) else None
	source = classification if isinstance(classification, dict) else details if isinstance(details, dict) else {}
	return {
		"raw_count": source.get("positions_count"),
		"material_count": source.get("material_positions_count"),
		"dust_count": source.get("dust_positions_count"),
		"unknown_count": source.get("unknown_value_positions_count"),
		"material_symbols": source.get("material_symbols") or [],
		"dust_symbols": source.get("dust_symbols") or [],
		"unknown_symbols": source.get("unknown_value_symbols") or [],
		"has_healthcheck_counts": any(
			source.get(key) is not None for key in [
				"positions_count",
				"material_positions_count",
				"dust_positions_count",
				"unknown_value_positions_count",
			]
		),
	}


def _buy_classification_from_portfolio():
	rows = Portfolio.objects.filter(quantity__gt=0).order_by("symbol")
	rows = list(rows)
	classification = classify_buy_status_positions(rows)
	material_symbols = [row["symbol"] for row in classification["material_rows"]]
	dust_symbols = [row["symbol"] for row in classification["dust_rows"]]
	unknown_symbols = classification["unknown_symbols"]
	return {
		"raw_count": len(rows),
		"material_count": len(material_symbols),
		"dust_count": len(dust_symbols),
		"unknown_count": len(unknown_symbols),
		"material_symbols": material_symbols,
		"dust_symbols": dust_symbols,
		"unknown_symbols": unknown_symbols,
		"has_healthcheck_counts": False,
	}


def _resolve_max_positions(details):
	value = _details_first(details, [
		"max_positions",
		"max_open_positions",
		"max_concurrent_positions",
		"position_limit",
		"config.max_positions",
		"config.max_open_positions",
	])
	if value is not None:
		return value
	return _runtime_config_first([
		"MAX_POSITIONS",
		"MAX_OPEN_POSITIONS",
		"MAX_CONCURRENT_POSITIONS",
		"POSITION_LIMIT",
	])


def _resolve_min_required_buy_amount(details):
	value = _details_first(details, [
		"min_required_buy_amount",
		"buy_allocation_usdt",
		"buy_amount_usdt",
		"min_buy_amount_usdt",
		"config.min_required_buy_amount",
		"config.buy_allocation_usdt",
	])
	if value is not None:
		return value
	return _runtime_config_first([
		"MIN_REQUIRED_BUY_AMOUNT",
		"BUY_ALLOCATION_USDT",
		"BUY_AMOUNT_USDT",
		"MIN_BUY_AMOUNT_USDT",
	])


def _resolve_read_only(details):
	value = _details_first(details, [
		"read_only",
		"is_read_only",
		"config.read_only",
	])
	if value is not None:
		return _as_bool(value)
	return _as_bool(_runtime_config_first(["READ_ONLY"]))


def _runtime_config_first(keys):
	for key in keys:
		value = getattr(settings, key, None)
		if value not in (None, ""):
			return value
		value = os.environ.get(key)
		if value not in (None, ""):
			return value
	return None


def _as_bool(value):
	if isinstance(value, bool):
		return value
	if value is None:
		return False
	return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _effective_positions(material_count, unknown_count):
	material = to_decimal(material_count)
	unknown = to_decimal(unknown_count)
	if material is None:
		return None
	if unknown is None:
		unknown = Decimal("0")
	return material + unknown


def _remaining_capacity(max_positions, effective_positions):
	maximum = to_decimal(max_positions)
	effective = to_decimal(effective_positions)
	if maximum is None or effective is None:
		return None
	return max(maximum - effective, Decimal("0"))


def latest_buy_decision_from_details(details):
	return _details_first(details, [
		"latest_buy_decision",
		"latest_buy_state",
		"buy.latest_decision",
		"buy.latest_state",
	])


def latest_buy_reason_from_details(details):
	return _details_first(details, [
		"latest_buy_reason",
		"buy.latest_reason",
	])


def _latest_buy_error(details):
	return _details_first(details, [
		"latest_buy_error",
		"latest_buy_error_class",
		"latest_buy_error_code",
		"buy.latest_error",
	])


def interpret_buy_state(
	raw_count,
	material_count,
	max_positions,
	free_usdt=None,
	unknown_count=None,
	read_only=False,
	min_required_buy_amount=None,
	latest_buy_decision=None,
	latest_buy_reason=None,
	latest_buy_error=None,
):
	raw = to_decimal(raw_count)
	material = to_decimal(material_count)
	maximum = to_decimal(max_positions)
	unknown = to_decimal(unknown_count) or Decimal("0")
	effective = _effective_positions(material_count, unknown_count)
	free = to_decimal(free_usdt)
	min_required = to_decimal(min_required_buy_amount)
	decision = str(latest_buy_decision or "").strip().lower()
	reason = str(latest_buy_reason or "").strip().lower()

	if maximum is None:
		return "diagnostic_unavailable", "⚪", "max positions unavailable"
	if material is None or raw is None or effective is None:
		return "diagnostic_unavailable", "⚪", "position classification unavailable"
	if read_only:
		return "blocked_by_read_only", "🔴", "READ_ONLY=true"
	if decision == "blocked_by_positions":
		return "blocked_by_positions", "🔴", "effective positions at max capacity"
	if decision == "blocked_by_usdt" or reason == "free_usdt_below_buy_amount":
		return "blocked_by_usdt", "🟡", "free USDT below configured buy amount"
	if decision in {"execution_error", "planned_failed", "submitted_failed"} or (
		decision in {"planned", "submitted"} and latest_buy_error
	):
		return "execution_error", "🔴", "latest BUY execution failed"
	if decision == "no_candidate" or "no_candidate" in reason:
		return "no_candidate", "⚪", "scanner did not select a candidate"
	if reason in BUY_COOLDOWN_REASON_PRESENTATION:
		return "blocked_by_cooldown", "🟡", BUY_COOLDOWN_REASON_PRESENTATION[reason]
	if effective >= maximum:
		return "blocked_by_positions", "🔴", "effective positions at max capacity"
	if free is not None and min_required is not None and free < min_required:
		return "blocked_by_usdt", "🔴", "free USDT below configured buy amount"
	return "available", "🟢", "capacity available"


def _buy_status_lines(
	*,
	remaining_capacity,
	latest_buy_state,
	latest_buy_reason,
	read_only,
	state_label,
):
	lines = []
	remaining = to_decimal(remaining_capacity)
	decision = str(latest_buy_state or "").strip().lower()
	reason = str(latest_buy_reason or "").strip().lower()

	if remaining is None:
		lines.append("⚪ Capacity diagnostic unavailable")
	elif remaining > 0:
		lines.append("✅ Capacity available")
	else:
		lines.append("⛔ No remaining BUY slots")

	if read_only:
		lines.append("⛔ Bot is in read-only mode")
	if decision == "blocked_by_usdt" or reason == "free_usdt_below_buy_amount":
		lines.append("⚠️ Insufficient free USDT for next BUY")
	if decision == "blocked_by_positions" or state_label == "blocked_by_positions":
		if "⛔ No remaining BUY slots" not in lines:
			lines.append("⛔ No remaining BUY slots")
	if decision == "no_candidate" or reason == "no_candidate":
		lines.append("ℹ️ Scanner did not select a BUY candidate")
	if decision == "execution_error" or reason == "binance_api_error":
		lines.append("⚠️ Latest BUY execution error")
	if state_label == "diagnostic_unavailable":
		lines.append("⚪ Diagnostic unavailable")
	return lines


def latest_buy_rejection_reason():
	try:
		event = (
			TradeOperation.objects
			.filter(side="BUY")
			.exclude(status__in=["FILLED", "filled"])
			.order_by("-executed_at", "-created_at", "-id")
			.first()
		)
	except (DatabaseError, AttributeError):
		return None
	if event is None:
		return None
	status = getattr(event, "status", None)
	payload = getattr(event, "raw_payload", None) or {}
	reason = None
	if isinstance(payload, dict):
		reason = payload.get("reason") or payload.get("rejection_reason") or payload.get("message")
	return reason or status


def _details_first(details, keys):
	for key in keys:
		value = _details_get(details, key)
		if value is not None and value != "":
			return value
	return None


def _details_get(details, key):
	current = details
	for part in key.split("."):
		if not isinstance(current, dict) or part not in current:
			return None
		current = current[part]
	return current
