import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Avg, Sum
from django.utils import timezone

from core.trading_models import (
	BotHealthcheck,
	DustDetection,
	Portfolio,
	PositionLot,
	SellDecisionEvent,
	TradeOperation,
)


logger = logging.getLogger(__name__)

DIAGNOSTIC_COMMANDS = {"/health", "/position", "/last_sell", "/why_not_sell", "/buy_status"}
REJECTED_SELL_EVENTS = [
	"sell_signal_rejected",
	"sell_order_skipped",
	"sell_skipped_not_profitable",
]
SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}$")


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
	if command == "/buy_status":
		return format_buy_status()

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


def format_buy_status():
	latest = BotHealthcheck.objects.order_by("-created_at", "-id").first()
	if latest is None:
		return "\n".join([
			"<b>⚪ BUY status</b>",
			"",
			"Raw/material/dust/unknown: <code>N/A/N/A/N/A/N/A</code>",
			"Max positions: <code>N/A</code>",
			"",
			"Material: <code>none</code>",
			"Dust: <code>none</code>",
			"Unknown: <code>none</code>",
			"",
			"Free USDT: <code>N/A</code>",
			"Latest BUY reason: <code>N/A</code>",
			"",
			"BUY state: <code>unknown</code>",
			"Reason: <code>latest healthcheck missing</code>",
		])

	details = latest.details or {}
	classification = _buy_classification_from_details(details)
	if not classification["has_healthcheck_counts"]:
		classification = _buy_classification_from_portfolio()

	raw_count = classification["raw_count"]
	material_count = classification["material_count"]
	dust_count = classification["dust_count"]
	unknown_count = classification["unknown_count"]
	max_positions = _details_first(details, [
		"max_positions",
		"max_open_positions",
		"max_concurrent_positions",
		"position_limit",
		"config.max_positions",
		"config.max_open_positions",
	])
	free_usdt = _details_first(details, [
		"free_usdt",
		"available_usdt",
		"free_capital_usdt",
		"available_capital_usdt",
		"capital.free_usdt",
		"balances.USDT.free",
	])
	latest_buy_reason = latest_buy_rejection_reason()
	state_label, emoji, reason = interpret_buy_state(
		raw_count=raw_count,
		material_count=material_count,
		max_positions=max_positions,
		free_usdt=free_usdt,
		unknown_count=unknown_count,
	)

	lines = [
		f"<b>{emoji} BUY status</b>",
		"",
		"Raw/material/dust/unknown: "
		f"<code>{h('/'.join(fmt_count(value) for value in [raw_count, material_count, dust_count, unknown_count]))}</code>",
		f"Max positions: <code>{h(fmt_count(max_positions))}</code>",
		"",
		f"Material: <code>{h(fmt_symbol_list(classification['material_symbols']))}</code>",
		f"Dust: <code>{h(fmt_symbol_list(classification['dust_symbols']))}</code>",
		f"Unknown: <code>{h(fmt_symbol_list(classification['unknown_symbols']))}</code>",
		"",
		f"Free USDT: <code>{h(fmt_usdt(free_usdt))}</code>",
		f"Latest BUY reason: <code>{h(latest_buy_reason)}</code>",
		"",
		f"BUY state: <code>{h(state_label)}</code>",
		f"Reason: <code>{h(reason)}</code>",
	]
	return "\n".join(lines)


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

	explanations = explain_rejection(event)
	block = "\n".join(f"- {item}" for item in explanations)
	return "\n".join([
		f"<b>🤔 Why not sell — {h(symbol)}</b>",
		"",
		f"Event: <code>{h(getattr(event, 'event_name', None))}</code>",
		f"Reason: <code>{h(getattr(event, 'reason', None))}</code>",
		f"Stage: <code>{h(getattr(event, 'validation_stage', None))}</code>",
		f"PnL: <code>{h(fmt_percent(getattr(event, 'estimated_pnl_percent', None)))}</code>",
		"",
		"Interpretation:",
		f"<pre>{h(block)}</pre>",
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
	return {
		"raw_count": details.get("positions_count"),
		"material_count": details.get("material_positions_count"),
		"dust_count": details.get("dust_positions_count"),
		"unknown_count": details.get("unknown_value_positions_count"),
		"material_symbols": details.get("material_symbols") or [],
		"dust_symbols": details.get("dust_symbols") or [],
		"unknown_symbols": details.get("unknown_value_symbols") or [],
		"has_healthcheck_counts": any(
			details.get(key) is not None for key in [
				"positions_count",
				"material_positions_count",
				"dust_positions_count",
				"unknown_value_positions_count",
			]
		),
	}


def _buy_classification_from_portfolio():
	rows = Portfolio.objects.filter(quantity__gt=0).order_by("symbol")
	raw_count = 0
	material_symbols = []
	dust_symbols = []
	unknown_symbols = []
	for row in rows:
		raw_count += 1
		symbol = getattr(row, "symbol", "")
		quantity = getattr(row, "quantity", None)
		price = getattr(row, "current_price", None)
		value = _decimal_product(quantity, price)
		if price is None or price <= 0 or value is None:
			unknown_symbols.append(symbol)
		elif value >= Decimal("5"):
			material_symbols.append(symbol)
		elif value > 0:
			dust_symbols.append(symbol)
		else:
			unknown_symbols.append(symbol)
	return {
		"raw_count": raw_count,
		"material_count": len(material_symbols),
		"dust_count": len(dust_symbols),
		"unknown_count": len(unknown_symbols),
		"material_symbols": material_symbols,
		"dust_symbols": dust_symbols,
		"unknown_symbols": unknown_symbols,
		"has_healthcheck_counts": False,
	}


def interpret_buy_state(raw_count, material_count, max_positions, free_usdt=None, unknown_count=None):
	raw = to_decimal(raw_count)
	material = to_decimal(material_count)
	maximum = to_decimal(max_positions)
	unknown = to_decimal(unknown_count) or Decimal("0")

	if maximum is None:
		return "uncertain", "🟡", "max positions unavailable"
	if material is None or raw is None:
		return "unknown", "⚪", "position classification unavailable"
	if material >= maximum:
		return "blocked", "🔴", "material positions at max capacity"
	if raw > maximum and material < maximum:
		if material == 0:
			return "uncertain", "🟡", "no material positions, but raw dust may be confusing capacity"
		return "uncertain", "🟡", "raw positions exceed max while material positions do not; check bot BUY gating"
	if unknown > 0:
		return "uncertain", "🟡", "unknown-value positions may count as exposure"
	if free_usdt is None:
		return "uncertain", "🟡", "free capital unavailable"
	return "can probably buy", "🟢", "material positions below max and free capital data is present"


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
		return "N/A"
	if event is None:
		return "N/A"
	status = getattr(event, "status", None)
	payload = getattr(event, "raw_payload", None) or {}
	reason = None
	if isinstance(payload, dict):
		reason = payload.get("reason") or payload.get("rejection_reason") or payload.get("message")
	return reason or status or "N/A"


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
