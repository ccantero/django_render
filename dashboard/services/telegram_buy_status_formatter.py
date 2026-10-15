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
DUST_MIN_NOTIONAL_USDT = Decimal("5")
DUST_SYMBOL_DISPLAY_LIMIT = 5
UNKNOWN_VALUE_SYMBOL_DISPLAY_LIMIT = 12
MATERIAL_UNAVAILABLE_SYMBOL_DISPLAY_LIMIT = 12
TELEGRAM_TEXT_LIMIT = 4096


def classify_buy_status_positions(portfolio_rows):
	material_rows = []
	dust_rows = []
	unknown_symbols = []
	for row in portfolio_rows or []:
		symbol = getattr(row, "symbol", "")
		valued_row = _valued_row_from_portfolio(row)
		if valued_row is None:
			unknown_symbols.append(symbol)
			continue
		if valued_row["estimated_value_usdt"] >= DUST_MIN_NOTIONAL_USDT:
			material_rows.append(valued_row)
		elif valued_row["estimated_value_usdt"] > 0:
			dust_rows.append(valued_row)
		else:
			unknown_symbols.append(symbol)
	return {
		"material_rows": material_rows,
		"dust_rows": dust_rows,
		"unknown_symbols": unknown_symbols,
	}


def build_buy_status_exposure(material_symbols, dust_symbols, portfolio_rows):
	material_symbols = list(material_symbols or [])
	dust_symbols = list(dust_symbols or [])
	rows_by_symbol = {getattr(row, "symbol", None): row for row in portfolio_rows}

	material_unavailable = []
	dust_unavailable = []
	material_rows = []
	dust_rows = []
	for symbol in dict.fromkeys(material_symbols + dust_symbols):
		source_bucket = "material" if symbol in material_symbols else "dust"
		row = rows_by_symbol.get(symbol)
		if row is None:
			if source_bucket == "material":
				material_unavailable.append(symbol)
			else:
				dust_unavailable.append(symbol)
			continue
		valued_row = _valued_row_from_portfolio(row)
		if valued_row is None:
			if source_bucket == "material":
				material_unavailable.append(symbol)
			else:
				dust_unavailable.append(symbol)
		elif source_bucket == "material":
			material_rows.append(valued_row)
		else:
			dust_rows.append(valued_row)
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
	open_positions_pnl=None,
	realized_today=None,
	latest_buy_error_class=None,
	latest_buy_error_code=None,
	unknown_value_symbols=None,
	cooldown_lines=None,
	inventory_warning_lines=None,
	classification_stale=False,
	latest_buy_historical=False,
):
	positions_heading = "Positions (last persisted; stale)" if classification_stale else "Positions"
	latest_heading = "Last persisted BUY (historical; healthcheck stale)" if latest_buy_historical else "Latest BUY"
	lines = [
		f"<b>{escape(str(emoji))} BUY status</b>",
		"",
		"<b>Capacity</b>",
		f"- Effective positions: <code>{_fmt_count(effective_positions)} / {_fmt_count(max_positions)}</code>",
		f"- Remaining slots: <code>{_fmt_count(remaining_capacity)}</code>",
		f"- Free USDT: <code>{_fmt_usdt(free_usdt) if free_usdt is not None else 'diagnostic unavailable'}</code>",
		"",
		f"<b>{positions_heading}</b>",
		f"- Raw: <code>{_fmt_count(raw_count)}</code>",
		f"- Material: <code>{_fmt_count(material_count)}</code>",
		f"- Dust: <code>{_fmt_count(dust_count)}</code>",
		f"- Unknown value: <code>{_fmt_count(unknown_count)}</code>",
		"",
		_material_heading(exposure, stale=classification_stale),
	]

	if exposure["material_rows"]:
		material_rows, omitted_material_rows = _configured_material_rows(
			exposure["material_rows"], max_positions,
		)
		for row in material_rows:
			lines.append(
				f"- {escape(str(row['symbol']))} ~ {_fmt_usdt(row['estimated_value_usdt'])}"
				f" | {_pnl_label(row)}"
			)
		if omitted_material_rows:
			lines.append(f"- ... and {omitted_material_rows} more")
	else:
		material_rows = []
		omitted_material_rows = 0
		lines.append("- none")
	if exposure["material_unavailable_symbols"]:
		lines.append(
			"- Valuation unavailable: <code>"
			f"{_fmt_symbol_list(exposure['material_unavailable_symbols'], MATERIAL_UNAVAILABLE_SYMBOL_DISPLAY_LIMIT)}</code>"
		)

	lines.extend([
		"",
		"<b>PnL</b>",
		f"- Open positions: <code>{_pnl_summary_label(open_positions_pnl)}</code>",
		f"- Realized today (UTC): <code>{_pnl_summary_label(realized_today)}</code>",
		"",
		f"<b>{'Dust exposure (last persisted; stale)' if classification_stale else 'Dust exposure'}</b>",
		f"- Dust positions: <code>{_fmt_count(dust_count)}</code>",
		f"- Estimated dust exposure: <code>{_dust_total_label(exposure)}</code>",
	])
	if dust_count is not None and _to_decimal(dust_count) is not None and _to_decimal(dust_count) <= 5:
		lines.append(f"- Symbols: <code>{_fmt_symbol_list([row['symbol'] for row in exposure['dust_rows']] + exposure['dust_unavailable_symbols'], DUST_SYMBOL_DISPLAY_LIMIT)}</code>")
	elif exposure["dust_rows"] or exposure["dust_unavailable_symbols"]:
		dust_symbol_count = len(exposure["dust_rows"]) + len(exposure["dust_unavailable_symbols"])
		lines.append(f"- Symbols: {dust_symbol_count} not listed (compact dust summary)")
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
			f"- Valuation unavailable: <code>{_fmt_symbol_list(unknown_symbols, UNKNOWN_VALUE_SYMBOL_DISPLAY_LIMIT)}</code>",
		])

	if inventory_warning_lines:
		lines.extend([
			"",
			f"<b>{'Last persisted inventory warnings (historical; healthcheck stale)' if classification_stale else 'Inventory warnings'}</b>",
			*inventory_warning_lines,
		])

	lines.extend([
		"",
		f"<b>{latest_heading}</b>",
		f"- State: <code>{_safe_html_text(latest_buy_state)}</code>",
		f"- Reason: <code>{_safe_html_text(latest_buy_reason)}</code>",
		f"- Candidate: <code>{_safe_html_text(latest_buy_symbol)}</code>",
	])
	if latest_buy_error_class:
		lines.append(f"- Error class: <code>{_safe_html_text(latest_buy_error_class)}</code>")
	if latest_buy_error_code:
		lines.append(f"- Error code: <code>{_safe_html_text(latest_buy_error_code)}</code>")
	if read_only:
		lines.append("- Read-only: <code>true</code>")

	lines.extend(["", "<b>Status</b>"])
	lines.extend(_safe_html_line(line) for line in status_lines)
	if cooldown_lines:
		lines.extend([""] + cooldown_lines)
	message = "\n".join(lines)
	if len(message) <= TELEGRAM_TEXT_LIMIT:
		return message
	return _compact_buy_status_message(
		emoji=emoji,
		effective_positions=effective_positions,
		max_positions=max_positions,
		remaining_capacity=remaining_capacity,
		free_usdt=free_usdt,
		raw_count=raw_count,
		material_count=material_count,
		dust_count=dust_count,
		unknown_count=unknown_count,
		open_positions_pnl=open_positions_pnl,
		realized_today=realized_today,
		latest_buy_state=latest_buy_state,
		latest_buy_reason=latest_buy_reason,
		latest_buy_symbol=latest_buy_symbol,
		latest_buy_error_class=latest_buy_error_class,
		latest_buy_error_code=latest_buy_error_code,
		read_only=read_only,
		status_lines=status_lines,
		exposure=exposure,
		material_rows=material_rows,
		omitted_material_rows=omitted_material_rows,
		classification_stale=classification_stale,
		latest_buy_historical=latest_buy_historical,
	)


def _compact_buy_status_message(**values):
	"""Keep operational fields in a bounded fallback; never truncate raw HTML."""
	def safe(value, fallback="unavailable", limit=160):
		text = " ".join(str(value or fallback).split())
		return escape(text[:limit])

	def build_message(shown_rows):
		omitted_count = values["omitted_material_rows"] + len(values["material_rows"]) - len(shown_rows)
		lines = [
			f"<b>{safe(values['emoji'], limit=8)} BUY status</b>",
			"",
			"<b>Capacity</b>",
			f"- Effective positions: <code>{_bounded_count(values['effective_positions'])} / {_bounded_count(values['max_positions'])}</code>",
			f"- Remaining slots: <code>{_bounded_count(values['remaining_capacity'])}</code>",
			f"- Free USDT: <code>{safe(_fmt_usdt(values['free_usdt']) if values['free_usdt'] is not None else 'diagnostic unavailable', limit=64)}</code>",
			"",
			f"<b>{'Positions (last persisted; stale)' if values['classification_stale'] else 'Positions'}</b>",
			f"- Raw: <code>{_bounded_count(values['raw_count'])}</code>",
			f"- Material: <code>{_bounded_count(values['material_count'])}</code>",
			f"- Dust: <code>{_bounded_count(values['dust_count'])}</code>",
			f"- Unknown value: <code>{_bounded_count(values['unknown_count'])}</code>",
			"",
			_compact_material_heading(values["exposure"], values["classification_stale"]),
		]
		lines.extend(_compact_material_row(row) for row in shown_rows)
		if not shown_rows and not values["exposure"]["material_unavailable_symbols"]:
			lines.append("- none")
		if values["exposure"]["material_unavailable_symbols"]:
			lines.append(
				"- Valuation unavailable: <code>"
				f"{_fmt_symbol_list(values['exposure']['material_unavailable_symbols'], MATERIAL_UNAVAILABLE_SYMBOL_DISPLAY_LIMIT)}</code>"
			)
		if omitted_count:
			lines.append(
				f"- … {omitted_count} material position(s) omitted; Telegram/configured display limit"
			)
		lines.extend([
			"",
			"<b>PnL</b>",
			f"- Open positions: <code>{_safe_html_text(_pnl_summary_label(values['open_positions_pnl']), limit=64)}</code>",
			f"- Realized today (UTC): <code>{_safe_html_text(_pnl_summary_label(values['realized_today']), limit=64)}</code>",
			"",
			f"<b>{'Last persisted BUY (historical; healthcheck stale)' if values['latest_buy_historical'] else 'Latest BUY'}</b>",
			f"- State: <code>{safe(values['latest_buy_state'])}</code>",
			f"- Reason: <code>{safe(values['latest_buy_reason'])}</code>",
			f"- Candidate: <code>{safe(values['latest_buy_symbol'])}</code>",
		])
		if values['latest_buy_error_class']:
			lines.append(f"- Error class: <code>{safe(values['latest_buy_error_class'])}</code>")
		if values['latest_buy_error_code']:
			lines.append(f"- Error code: <code>{safe(values['latest_buy_error_code'])}</code>")
		if values['read_only']:
			lines.append("- Read-only: <code>true</code>")
		lines.extend(["", "<b>Status</b>"])
		lines.extend(f"- {safe(line, fallback='', limit=240)}" for line in values['status_lines'][:5])
		lines.append("… Additional diagnostics omitted to fit Telegram's 4096-character limit.")
		return "\n".join(lines)

	shown_rows = []
	message = build_message(shown_rows)
	for row in values["material_rows"]:
		candidate = build_message(shown_rows + [row])
		if len(candidate) > TELEGRAM_TEXT_LIMIT:
			break
		shown_rows.append(row)
		message = candidate
	while len(message) > TELEGRAM_TEXT_LIMIT and shown_rows:
		shown_rows.pop()
		message = build_message(shown_rows)
	return message


def _compact_material_heading(exposure, stale):
	if exposure["material_total"] is None and exposure["material_unavailable_symbols"]:
		label = "Material exposure (partially unavailable)"
	else:
		total = exposure["material_total"] or Decimal("0")
		label = f"Material exposure (~{escape(_fmt_usdt_value(total)[:64])} USDT)"
	if stale:
		label += "; last persisted classification is stale"
	return f"<b>{label}</b>"


def _compact_material_row(row):
	symbol = _safe_html_text(row.get("symbol"), limit=40)
	value = _safe_html_text(_fmt_usdt(row.get("estimated_value_usdt")), limit=64)
	pnl = _safe_html_text(_pnl_label(row), limit=96)
	return f"- {symbol} ~ {value} | {pnl}"


def _configured_material_rows(rows, max_positions):
	rows = list(rows or [])
	configured = _to_decimal(max_positions)
	if configured is None or configured <= 0 or configured >= len(rows):
		return rows, 0
	limit = int(configured)
	if limit <= 0:
		return rows, 0
	return rows[:limit], max(0, len(rows) - limit)


def _safe_html_text(value, fallback="unavailable", limit=160):
	text = " ".join(str(value or fallback).split())
	return escape(text[:limit])


def _safe_html_line(value):
	return escape(" ".join(str(value or "").split()))


def _bounded_count(value):
	return _fmt_count(value)[:64]


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


def _valued_row_from_portfolio(row):
	quantity = _to_decimal(getattr(row, "quantity", None)) if row is not None else None
	price = _to_decimal(getattr(row, "current_price", None)) if row is not None else None
	if quantity is None or price is None or not quantity.is_finite() or not price.is_finite() or price <= 0:
		return None
	return {
		"symbol": getattr(row, "symbol", ""),
		"quantity": quantity,
		"current_price": price,
		"entry_price": _to_decimal(getattr(row, "entry_price", None)),
		"estimated_value_usdt": quantity * price,
	}


def _pnl_label(row):
	pnl = _position_pnl(row)
	if pnl is None:
		return "PnL unavailable"
	pnl_usdt, pnl_pct = pnl
	return f"PnL {_fmt_signed_usdt(pnl_usdt)} ({_fmt_signed_percent(pnl_pct)})"


def build_open_positions_pnl(exposure):
	if (exposure or {}).get("material_unavailable_symbols"):
		return None
	total = Decimal("0")
	for row in (exposure or {}).get("material_rows", []):
		pnl = _position_pnl(row)
		if pnl is None:
			return None
		total += pnl[0]
	return total


def _position_pnl(row):
	entry_price = row.get("entry_price")
	current_price = row.get("current_price")
	quantity = row.get("quantity")
	if entry_price is None or current_price is None or quantity is None or entry_price <= 0:
		return None
	pnl_usdt = (current_price - entry_price) * quantity
	pnl_pct = ((current_price - entry_price) / entry_price) * Decimal("100")
	return pnl_usdt, pnl_pct


def _pnl_summary_label(value):
	value = _to_decimal(value)
	if value is None:
		return "unavailable"
	sign = "+" if value >= 0 else "-"
	rounded = abs(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	return f"{sign}{format(rounded, 'f')} USDT"


def _material_heading(exposure, stale=False):
	if exposure["material_total"] is None and exposure["material_unavailable_symbols"]:
		label = "Material exposure (partially unavailable)"
		return f"<b>{label}; last persisted classification is stale</b>" if stale else f"<b>{label}</b>"
	total = exposure["material_total"] or Decimal("0")
	label = f"Material exposure (~{_fmt_usdt_value(total)} USDT)"
	return f"<b>{label}; last persisted classification is stale</b>" if stale else f"<b>{label}</b>"


def _dust_total_label(exposure):
	if exposure["dust_unavailable_symbols"]:
		return "partially unavailable"
	return f"~{_fmt_usdt(exposure['dust_total'] or Decimal('0'))}"


def _sum_values(rows):
	return sum((row["estimated_value_usdt"] for row in rows), Decimal("0"))


def _fmt_symbol_list(values, limit):
	values = [str(value) for value in values if value not in (None, "")]
	if not values:
		return "none"
	shown = [escape(value) for value in values[:limit]]
	if len(values) > limit:
		shown.append(f"… +{len(values) - limit} more")
	return ", ".join(shown)


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
		decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return None
	return decimal_value if decimal_value.is_finite() else None


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
