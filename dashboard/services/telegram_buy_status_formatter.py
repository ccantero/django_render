from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape


COOLDOWN_TYPE_LABELS = {
	"loss": "loss",
	"take_profit": "take profit",
	"sell": "recent sell",
	"generic_sell": "recent sell",
}
COOLDOWN_CLASSIFICATION_SOURCE_LABELS = {
	"explicit_sell_reason": "explicit sell reason",
	"realized_pnl": "realized PnL",
	"generic_sell": "generic sell",
}
SELL_REASON_SOURCE_LABELS = {
	"raw_payload": "raw_payload",
	"nearby_sell_decision_event": "nearby sell decision event",
	"realized_pnl_fallback": "realized PnL fallback",
	"unavailable": "unavailable",
}


def build_buy_status_exposure(material_symbols, dust_symbols, portfolio_rows):
	material_symbols = list(material_symbols or [])
	dust_symbols = list(dust_symbols or [])
	rows_by_symbol = {getattr(row, "symbol", None): row for row in portfolio_rows}

	material_rows, material_unavailable = _valued_rows(material_symbols, rows_by_symbol)
	dust_rows, dust_unavailable = _valued_rows(dust_symbols, rows_by_symbol)
	material_rows.sort(key=lambda row: row["estimated_value_usdt"], reverse=True)

	return {
		"material_rows": material_rows,
		"material_total": _sum_values(material_rows) if not material_unavailable else None,
		"material_unavailable_symbols": material_unavailable,
		"dust_rows": dust_rows,
		"dust_total": _sum_values(dust_rows) if not dust_unavailable else None,
		"dust_unavailable_symbols": dust_unavailable,
	}


def render_buy_status_message(
	*,
	emoji,
	raw_count,
	material_count,
	dust_count,
	unknown_count,
	effective_positions,
	max_positions,
	remaining_capacity,
	free_usdt,
	latest_buy_state,
	latest_buy_reason,
	latest_buy_symbol,
	read_only,
	exposure,
	status_lines,
	latest_buy_error_class=None,
	latest_buy_error_code=None,
	unknown_value_symbols=None,
	cooldown_lines=None,
	inventory_warning_lines=None,
):
	lines = [
		f"<b>{escape(str(emoji))} BUY status</b>",
		"",
		"<b>Capacity</b>",
		f"- Effective positions: <code>{_fmt_count(effective_positions)} / {_fmt_count(max_positions)}</code>",
		f"- Remaining slots: <code>{_fmt_count(remaining_capacity)}</code>",
		f"- Free USDT: <code>{_fmt_usdt(free_usdt) if free_usdt is not None else 'diagnostic unavailable'}</code>",
		"",
		"<b>Positions</b>",
		f"- Raw: <code>{_fmt_count(raw_count)}</code>",
		f"- Material: <code>{_fmt_count(material_count)}</code>",
		f"- Dust: <code>{_fmt_count(dust_count)}</code>",
		f"- Unknown value: <code>{_fmt_count(unknown_count)}</code>",
		"",
		_material_heading(exposure),
	]

	if exposure["material_rows"]:
		for row in exposure["material_rows"][:8]:
			lines.append(
				f"- {escape(str(row['symbol']))} ~ {_fmt_usdt(row['estimated_value_usdt'])}"
				f" | {_pnl_label(row)}"
			)
		if len(exposure["material_rows"]) > 8:
			lines.append(f"- ... and {len(exposure['material_rows']) - 8} more")
	else:
		lines.append("- none")
	if exposure["material_unavailable_symbols"]:
		lines.append(
			"- Valuation unavailable: <code>"
			f"{_fmt_symbol_list(exposure['material_unavailable_symbols'])}</code>"
		)

	lines.extend([
		"",
		"<b>Dust exposure</b>",
		f"- Dust positions: <code>{_fmt_count(dust_count)}</code>",
		f"- Estimated dust exposure: <code>{_dust_total_label(exposure)}</code>",
	])
	if dust_count is not None and _to_decimal(dust_count) is not None and _to_decimal(dust_count) <= 5:
		lines.append(f"- Symbols: <code>{_fmt_symbol_list([row['symbol'] for row in exposure['dust_rows']] + exposure['dust_unavailable_symbols'])}</code>")
	lines.append("- Dust positions are non-blocking")

	unknown_symbols = list(dict.fromkeys(
		list(unknown_value_symbols or [])
		+ exposure["material_unavailable_symbols"]
		+ exposure["dust_unavailable_symbols"]
	))
	if unknown_symbols:
		lines.extend([
			"",
			"<b>Unknown value</b>",
			f"- Valuation unavailable: <code>{_fmt_symbol_list(unknown_symbols)}</code>",
		])

	if inventory_warning_lines:
		lines.extend([
			"",
			"<b>Inventory warnings</b>",
			*inventory_warning_lines,
		])

	lines.extend([
		"",
		"<b>Latest BUY</b>",
		f"- State: <code>{escape(str(latest_buy_state or 'unavailable'))}</code>",
		f"- Reason: <code>{escape(str(latest_buy_reason or 'unavailable'))}</code>",
		f"- Candidate: <code>{escape(str(latest_buy_symbol or 'unavailable'))}</code>",
	])
	if latest_buy_error_class:
		lines.append(f"- Error class: <code>{escape(str(latest_buy_error_class))}</code>")
	if latest_buy_error_code:
		lines.append(f"- Error code: <code>{escape(str(latest_buy_error_code))}</code>")
	if read_only:
		lines.append("- Read-only: <code>true</code>")

	lines.extend(["", "<b>Status</b>"])
	lines.extend(status_lines)
	if cooldown_lines:
		lines.extend([""] + cooldown_lines)
	return "\n".join(lines)


def build_inventory_warning_lines(warnings, limit=3):
	relevant = [
		warning for warning in list(warnings or [])
		if isinstance(warning, dict)
		and str(warning.get("severity") or "").strip().upper() in {"WARNING", "CRITICAL"}
	]
	lines = [_format_inventory_warning(warning) for warning in relevant[:limit]]
	if len(relevant) > limit:
		lines.append(f"- +{len(relevant) - limit} more")
	return lines


def count_relevant_inventory_warnings(warnings):
	return sum(
		1 for warning in list(warnings or [])
		if isinstance(warning, dict)
		and str(warning.get("severity") or "").strip().upper() in {"WARNING", "CRITICAL"}
	)


def build_cooldown_diagnostics(details, human_reason=None):
	details = details if isinstance(details, dict) else {}
	latest_sell_timestamp = details.get("latest_sell_executed_at") or details.get("latest_sell_timestamp")
	realized_pnl = _to_decimal(details.get("latest_sell_realized_pnl"))
	classification_source = _normalized_text(details.get("cooldown_classification_source"))
	cooldown_type = _normalized_text(details.get("cooldown_type"))
	reason = details.get("latest_sell_reason")
	has_context = any(
		value not in (None, "")
		for value in [
			details.get("latest_sell_operation_id"),
			details.get("latest_sell_symbol"),
			latest_sell_timestamp,
			reason,
			details.get("latest_sell_reason_source"),
			details.get("latest_sell_realized_pnl"),
			cooldown_type,
			details.get("cooldown_minutes"),
			details.get("cooldown_elapsed_minutes"),
			details.get("cooldown_remaining_minutes"),
			classification_source,
		]
	)
	cooldown_explanation = None
	if (
		reason in (None, "")
		and realized_pnl is not None
		and realized_pnl < 0
		and classification_source == "realized_pnl"
	):
		cooldown_explanation = "Cooldown triggered from negative realized PnL"

	return {
		"human_reason": human_reason,
		"has_context": has_context,
		"latest_sell_operation_id": details.get("latest_sell_operation_id"),
		"latest_sell_operation_label": _context_label(details.get("latest_sell_operation_id"), has_context),
		"latest_sell_symbol": details.get("latest_sell_symbol"),
		"latest_sell_symbol_label": _context_label(details.get("latest_sell_symbol"), has_context),
		"latest_sell_timestamp": latest_sell_timestamp,
		"latest_sell_timestamp_label": _context_label(latest_sell_timestamp, has_context),
		"latest_sell_reason": reason,
		"latest_sell_reason_label": _nullable_reason_label(reason, has_context),
		"latest_sell_reason_source": details.get("latest_sell_reason_source"),
		"latest_sell_reason_source_label": _source_label(details.get("latest_sell_reason_source")),
		"latest_sell_realized_pnl": realized_pnl,
		"latest_sell_realized_pnl_label": _fmt_usdt(realized_pnl) if realized_pnl is not None else _context_label(None, has_context),
		"cooldown_type": cooldown_type,
		"cooldown_type_label": COOLDOWN_TYPE_LABELS.get(cooldown_type, _context_label(cooldown_type, has_context)),
		"cooldown_minutes": _to_decimal(details.get("cooldown_minutes")),
		"cooldown_minutes_label": _fmt_minutes(details.get("cooldown_minutes")),
		"cooldown_elapsed_minutes": _to_decimal(details.get("cooldown_elapsed_minutes")),
		"cooldown_elapsed_minutes_label": _fmt_minutes(details.get("cooldown_elapsed_minutes")),
		"cooldown_remaining_minutes": _to_decimal(details.get("cooldown_remaining_minutes")),
		"cooldown_remaining_minutes_label": _fmt_minutes(details.get("cooldown_remaining_minutes")),
		"cooldown_classification_source": classification_source,
		"cooldown_classification_source_label": COOLDOWN_CLASSIFICATION_SOURCE_LABELS.get(
			classification_source,
			_context_label(classification_source, has_context),
		),
		"cooldown_explanation": cooldown_explanation,
	}


def build_cooldown_lines(diagnostics):
	if not diagnostics:
		return []
	lines = []
	if diagnostics.get("human_reason"):
		lines.append(f"Cooldown: <code>{escape(str(diagnostics['human_reason']))}</code>")
	if diagnostics.get("cooldown_explanation"):
		lines.append(f"- {escape(str(diagnostics['cooldown_explanation']))}")
	lines.extend([
		f"Latest SELL operation: <code>{escape(str(diagnostics['latest_sell_operation_label']))}</code>",
		f"Latest SELL symbol: <code>{escape(str(diagnostics['latest_sell_symbol_label']))}</code>",
		f"Latest SELL timestamp: <code>{escape(str(diagnostics['latest_sell_timestamp_label']))}</code>",
		f"Latest SELL reason: <code>{escape(str(diagnostics['latest_sell_reason_label']))}</code>",
		f"Reason source: <code>{escape(str(diagnostics['latest_sell_reason_source_label']))}</code>",
		f"Latest SELL realized PnL: <code>{escape(str(diagnostics['latest_sell_realized_pnl_label']))}</code>",
		f"Cooldown type: <code>{escape(str(diagnostics['cooldown_type_label']))}</code>",
		f"Classification source: <code>{escape(str(diagnostics['cooldown_classification_source_label']))}</code>",
		f"Cooldown minutes: <code>{escape(str(diagnostics['cooldown_minutes_label']))}</code>",
		f"Cooldown elapsed: <code>{escape(str(diagnostics['cooldown_elapsed_minutes_label']))}</code>",
		f"Cooldown remaining: <code>{escape(str(diagnostics['cooldown_remaining_minutes_label']))}</code>",
	])
	return lines


def _format_inventory_warning(warning):
	symbol = escape(str(warning.get("symbol") or "unknown"))
	reason = _humanize_inventory_warning_reason(warning.get("reason"))
	suffix = ""
	notional = _to_decimal(warning.get("estimated_notional_usdt"))
	if notional is not None:
		suffix = f" (~{_fmt_usdt_value(notional)} USDT)"
	elif str(warning.get("valuation_status") or "").strip().lower() == "unknown":
		suffix = " (valuation unknown)"
	return f"- {symbol}: {reason}{suffix}"


def _humanize_inventory_warning_reason(reason):
	reason = str(reason or "unknown").strip()
	mapped = {
		"open_lots_without_portfolio_row": "open lots without portfolio row",
		"portfolio_row_without_open_lots": "portfolio row without open lots",
		"portfolio_lot_quantity_drift": "portfolio vs lots quantity drift",
	}
	if reason in mapped:
		return mapped[reason]
	return escape(reason.replace("_", " "))


def _valued_rows(symbols, rows_by_symbol):
	rows = []
	unavailable = []
	for symbol in symbols:
		row = rows_by_symbol.get(symbol)
		quantity = _to_decimal(getattr(row, "quantity", None)) if row is not None else None
		price = _to_decimal(getattr(row, "current_price", None)) if row is not None else None
		if quantity is None or price is None or price <= 0:
			unavailable.append(symbol)
			continue
		rows.append({
			"symbol": symbol,
			"quantity": quantity,
			"current_price": price,
			"entry_price": _to_decimal(getattr(row, "entry_price", None)),
			"estimated_value_usdt": quantity * price,
		})
	return rows, unavailable


def _pnl_label(row):
	entry_price = row.get("entry_price")
	current_price = row.get("current_price")
	quantity = row.get("quantity")
	if entry_price is None or current_price is None or quantity is None or entry_price <= 0:
		return "PnL unavailable"
	pnl_usdt = (current_price - entry_price) * quantity
	pnl_pct = ((current_price - entry_price) / entry_price) * Decimal("100")
	return f"PnL {_fmt_signed_usdt(pnl_usdt)} ({_fmt_signed_percent(pnl_pct)})"


def _material_heading(exposure):
	if exposure["material_total"] is None and exposure["material_unavailable_symbols"]:
		return "<b>Material exposure (partially unavailable)</b>"
	total = exposure["material_total"] or Decimal("0")
	return f"<b>Material exposure (~{_fmt_usdt_value(total)} USDT)</b>"


def _dust_total_label(exposure):
	if exposure["dust_unavailable_symbols"]:
		return "partially unavailable"
	return f"~{_fmt_usdt(exposure['dust_total'] or Decimal('0'))}"


def _sum_values(rows):
	return sum((row["estimated_value_usdt"] for row in rows), Decimal("0"))


def _fmt_symbol_list(values):
	values = [escape(str(value)) for value in values if value not in (None, "")]
	return ", ".join(values) if values else "none"


def _fmt_minutes(value):
	value = _to_decimal(value)
	if value is None:
		return "unknown"
	return f"{_fmt_count(value)} min"


def _fmt_count(value):
	value = _to_decimal(value)
	if value is None:
		return "N/A"
	text = format(value, "f")
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return text or "0"


def _fmt_usdt(value):
	value = _to_decimal(value)
	if value is None:
		return "N/A"
	return f"{_fmt_usdt_value(value)} USDT"


def _fmt_signed_usdt(value):
	value = _to_decimal(value)
	if value is None:
		return "N/A"
	sign = "+" if value >= 0 else "-"
	return f"{sign}{_fmt_usdt_value(abs(value))} USDT"


def _fmt_signed_percent(value):
	value = _to_decimal(value)
	if value is None:
		return "N/A"
	sign = "+" if value >= 0 else "-"
	rounded = abs(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	return f"{sign}{format(rounded, 'f')}%"


def _fmt_usdt_value(value):
	value = _to_decimal(value)
	if value is None:
		return "N/A"
	rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	return format(rounded, "f").rstrip("0").rstrip(".") or "0"


def _to_decimal(value):
	if value in (None, ""):
		return None
	try:
		return value if isinstance(value, Decimal) else Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return None


def _normalized_text(value):
	if value in (None, ""):
		return None
	return str(value).strip()


def _context_label(value, has_context):
	if value in (None, ""):
		return "unknown" if has_context else "unavailable"
	return value


def _nullable_reason_label(value, has_context):
	if value in (None, ""):
		return "not provided" if has_context else "unavailable"
	return value


def _source_label(value):
	value = _normalized_text(value)
	if value is None:
		return "unknown"
	return SELL_REASON_SOURCE_LABELS.get(value, value.replace("_", " "))
