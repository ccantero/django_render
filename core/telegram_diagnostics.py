import logging
import re
from decimal import Decimal
from html import escape

from django.conf import settings
from django.db.models import Avg, Sum
from django.utils import timezone

from core.trading_models import (
	BotHealthcheck,
	DustDetection,
	Portfolio,
	PositionLot,
	SellDecisionEvent,
)


logger = logging.getLogger(__name__)

DIAGNOSTIC_COMMANDS = {"/health", "/position", "/last_sell", "/why_not_sell"}
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
			f"<code>{h('/'.join(str(value if value is not None else 'N/A') for value in counts))}</code>"
		)
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
		f"Portfolio qty: <code>{h(fmt(portfolio_qty))}</code>",
		f"Open lots: <code>{h(fmt(open_qty))}</code>",
		f"Price: <code>{h(fmt(current_price))}</code>",
		f"Value: <code>{h(fmt(estimated_value))} USDT</code>",
		f"Entry: <code>{h(fmt(entry_price))}</code>",
		f"Drift: <code>{h(fmt(drift))}</code>",
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
		f"Entry: <code>{h(fmt(getattr(event, 'entry_price', None)))}</code>",
		f"Current: <code>{h(fmt(getattr(event, 'current_price', None)))}</code>",
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
	if value is None:
		return "N/A"
	return str(value)


def fmt_percent(value):
	if value is None:
		return "N/A"
	return f"{value}%"


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
