from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape


MATERIAL_MIN_NOTIONAL_USDT = Decimal("5")


def build_portfolio_status(
	*,
	open_lots,
	portfolio_rows,
	free_usdt,
	realized_today,
	as_of=None,
	stale_after=None,
):
	free_usdt = _to_decimal(free_usdt)
	realized_today = _to_decimal(realized_today)
	if open_lots is None or portfolio_rows is None:
		return _unavailable_summary(free_usdt, realized_today)

	prices = {}
	for row in portfolio_rows:
		symbol = getattr(row, "symbol", None)
		if _is_stale(getattr(row, "updated_at", None), as_of, stale_after):
			prices[symbol] = None
		else:
			prices[symbol] = _to_decimal(getattr(row, "current_price", None))
	positions = _aggregate_open_lots(open_lots)
	material_positions = []
	unavailable_symbols = []
	valued_total = Decimal("0")

	for symbol, position in sorted(positions.items()):
		current_price = prices.get(symbol)
		if current_price is None or current_price <= 0:
			unavailable_symbols.append(symbol)
			continue
		current_value = position["quantity"] * current_price
		valued_total += current_value
		if current_value < MATERIAL_MIN_NOTIONAL_USDT:
			continue
		material_positions.append({
			**position,
			"symbol": symbol,
			"current_price": current_price,
			"current_value": current_value,
		})

	invested_usdt = None
	equity_usdt = None
	if not unavailable_symbols:
		invested_usdt = valued_total
		if free_usdt is not None:
			equity_usdt = free_usdt + invested_usdt

	unrealized_pnl_usdt = None
	unrealized_pnl_pct = None
	contributors = []
	if not unavailable_symbols:
		cost_basis = Decimal("0")
		unrealized_total = Decimal("0")
		has_complete_cost_basis = True
		for position in material_positions:
			if position["cost_basis"] is None or position["cost_basis"] <= 0:
				has_complete_cost_basis = False
				break
			pnl_usdt = position["current_value"] - position["cost_basis"]
			pnl_pct = pnl_usdt / position["cost_basis"] * Decimal("100")
			cost_basis += position["cost_basis"]
			unrealized_total += pnl_usdt
			contributors.append({
				"symbol": position["symbol"],
				"pnl_usdt": pnl_usdt,
				"pnl_pct": pnl_pct,
			})
		if has_complete_cost_basis:
			unrealized_pnl_usdt = unrealized_total
			unrealized_pnl_pct = (
				unrealized_total / cost_basis * Decimal("100")
				if cost_basis > 0
				else Decimal("0")
			)

	return {
		"equity_usdt": equity_usdt,
		"free_usdt": free_usdt,
		"invested_usdt": invested_usdt,
		"unrealized_pnl_usdt": unrealized_pnl_usdt,
		"unrealized_pnl_pct": unrealized_pnl_pct,
		"realized_today": realized_today,
		"changes": {"24h": None, "7d": None, "30d": None},
		"best_contributor": max(contributors, key=lambda row: row["pnl_usdt"]) if contributors else None,
		"worst_contributor": min(contributors, key=lambda row: row["pnl_usdt"]) if contributors else None,
		"unavailable_symbols": unavailable_symbols,
	}


def render_portfolio_status(summary):
	lines = [
		"<b>📊 Portfolio status</b>",
		"",
		"<b>Total</b>",
		f"- Equity: <code>{_money(summary.get('equity_usdt'))}</code>",
		f"- Free USDT: <code>{_money(summary.get('free_usdt'))}</code>",
		f"- Open value: <code>{_money(summary.get('invested_usdt'))}</code>",
		"",
		"<b>PnL</b>",
		f"- Unrealized: <code>{_pnl(summary.get('unrealized_pnl_usdt'), summary.get('unrealized_pnl_pct'))}</code>",
		f"- Realized today (UTC): <code>{_signed_money(summary.get('realized_today'))}</code>",
		"",
		"<b>Change</b>",
	]
	for label in ("24h", "7d", "30d"):
		lines.append(f"- {label}: <code>{_change(summary.get('changes', {}).get(label))}</code>")

	lines.extend(["", "<b>Top contributors</b>"])
	best = summary.get("best_contributor")
	worst = summary.get("worst_contributor")
	lines.append(f"- Best: {_contributor(best)}")
	lines.append(f"- Worst: {_contributor(worst)}")

	unavailable_symbols = summary.get("unavailable_symbols") or []
	if unavailable_symbols:
		lines.extend([
			"",
			"Valuation unavailable: <code>"
			+ escape(", ".join(str(symbol) for symbol in unavailable_symbols))
			+ "</code>",
		])
	return "\n".join(lines)


def _aggregate_open_lots(open_lots):
	positions = {}
	for lot in open_lots:
		symbol = str(getattr(lot, "symbol", "") or "")
		quantity = _to_decimal(getattr(lot, "remaining_quantity", None))
		if not symbol or quantity is None or quantity <= 0:
			continue
		entry_price = _to_decimal(getattr(lot, "entry_price", None))
		position = positions.setdefault(
			symbol,
			{"quantity": Decimal("0"), "cost_basis": Decimal("0")},
		)
		position["quantity"] += quantity
		if entry_price is None or entry_price <= 0 or position["cost_basis"] is None:
			position["cost_basis"] = None
		else:
			position["cost_basis"] += quantity * entry_price
	return positions


def _unavailable_summary(free_usdt, realized_today):
	return {
		"equity_usdt": None,
		"free_usdt": free_usdt,
		"invested_usdt": None,
		"unrealized_pnl_usdt": None,
		"unrealized_pnl_pct": None,
		"realized_today": realized_today,
		"changes": {"24h": None, "7d": None, "30d": None},
		"best_contributor": None,
		"worst_contributor": None,
		"unavailable_symbols": [],
	}


def _money(value):
	value = _to_decimal(value)
	return f"{_decimal(value)} USDT" if value is not None else "unavailable"


def _signed_money(value):
	value = _to_decimal(value)
	return f"{_signed_decimal(value)} USDT" if value is not None else "unavailable"


def _pnl(value, percent):
	value = _to_decimal(value)
	percent = _to_decimal(percent)
	if value is None or percent is None:
		return "unavailable"
	return f"{_signed_decimal(value)} USDT ({_signed_decimal(percent)}%)"


def _change(value):
	if not isinstance(value, dict):
		return "unavailable"
	return _pnl(value.get("amount_usdt"), value.get("percent"))


def _contributor(value):
	if not value:
		return "<code>unavailable</code>"
	return (
		f"{escape(str(value['symbol']))} "
		f"<code>{_signed_decimal(value['pnl_usdt'])} USDT "
		f"({_signed_decimal(value['pnl_pct'])}%)</code>"
	)


def _decimal(value):
	return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _signed_decimal(value):
	sign = "+" if value >= 0 else "-"
	return sign + _decimal(abs(value))


def _to_decimal(value):
	if value is None or value == "":
		return None
	if isinstance(value, Decimal):
		return value
	try:
		return Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return None


def _is_stale(updated_at, as_of, stale_after):
	if as_of is None or stale_after is None:
		return False
	if updated_at is None:
		return True
	return as_of - updated_at > stale_after
