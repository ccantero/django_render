from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape


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
			"estimated_value_usdt": quantity * price,
		})
	return rows, unavailable


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
