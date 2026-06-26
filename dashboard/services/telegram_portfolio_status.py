import binascii
import struct
import zlib
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape


MATERIAL_MIN_NOTIONAL_USDT = Decimal("5")
CANONICAL_SNAPSHOT_SOURCE = "bot_cycle"
DEFAULT_MAX_CHART_POINTS = 96
DEFAULT_CHART_OUTLIER_THRESHOLD = Decimal("0.25")
_CHART_FONT = {
	"E": ["111", "100", "100", "111", "100", "100", "111"],
	"H": ["101", "101", "101", "111", "101", "101", "101"],
	"I": ["111", "010", "010", "010", "010", "010", "111"],
	"O": ["111", "101", "101", "101", "101", "101", "111"],
	"Q": ["111", "101", "101", "101", "101", "111", "001"],
	"R": ["110", "101", "101", "110", "101", "101", "101"],
	"S": ["111", "100", "100", "111", "001", "001", "111"],
	"T": ["111", "010", "010", "010", "010", "010", "010"],
	"U": ["101", "101", "101", "101", "101", "101", "111"],
	"Y": ["101", "101", "101", "010", "010", "010", "010"],
}


def build_portfolio_status(
	*,
	open_lots,
	portfolio_rows,
	free_usdt,
	realized_today,
	realized_drivers=None,
	equity_history=None,
	as_of=None,
	stale_after=None,
):
	free_usdt = _to_decimal(free_usdt)
	realized_today = _to_decimal(realized_today)
	if open_lots is None or portfolio_rows is None:
		return _unavailable_summary(free_usdt, realized_today, realized_drivers, equity_history)

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

	open_value_usdt = None
	equity_usdt = None
	if not unavailable_symbols:
		open_value_usdt = valued_total
		if free_usdt is not None:
			equity_usdt = free_usdt + open_value_usdt

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
		"open_value_usdt": open_value_usdt,
		"unrealized_pnl_usdt": unrealized_pnl_usdt,
		"unrealized_pnl_pct": unrealized_pnl_pct,
		"realized_today": realized_today,
		"drivers_24h": {
			"realized": _driver_from_rows(realized_drivers),
			"unrealized": _unrealized_driver(contributors, _history_changes(equity_history).get("24h")),
		},
		"changes": _history_changes(equity_history),
		"chart_points": _history_chart_points(equity_history),
		"chart_available": bool(_history_chart_points(equity_history)),
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
		f"- Open value: <code>{_money(summary.get('open_value_usdt'))}</code>",
		"",
		"<b>Performance</b>",
		"",
		"<b>Portfolio equity</b>",
	]
	for label in ("24h", "7d", "30d"):
		lines.append(f"- {label}: <code>{_change(summary.get('changes', {}).get(label))}</code>")
	if not summary.get("chart_available"):
		lines.append("Chart: unavailable, not enough history")

	lines.extend([
		"",
		"<b>Today&#x27;s trading (UTC)</b>",
		f"- Realized PnL: <code>{_signed_money(summary.get('realized_today'))}</code>",
		"",
		"<b>Open positions</b>",
		f"- Unrealized now: <code>{_pnl(summary.get('unrealized_pnl_usdt'), summary.get('unrealized_pnl_pct'))}</code>",
	])

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


class PortfolioEquityHistoryBuilder:
	WINDOWS = {
		"24h": timedelta(hours=24),
		"7d": timedelta(days=7),
		"30d": timedelta(days=30),
	}
	WINDOW_TOLERANCES = {
		"24h": (timedelta(hours=18), timedelta(hours=30)),
		"7d": (timedelta(days=6), timedelta(days=8)),
		"30d": (timedelta(days=28), timedelta(days=32)),
	}
	CHART_WINDOW = timedelta(days=7)

	def __init__(
		self,
		*,
		as_of,
		max_latest_age=timedelta(hours=6),
		max_chart_points=DEFAULT_MAX_CHART_POINTS,
		chart_outlier_threshold=DEFAULT_CHART_OUTLIER_THRESHOLD,
	):
		self.as_of = as_of
		self.max_latest_age = max_latest_age
		self.max_chart_points = max_chart_points
		self.chart_outlier_threshold = chart_outlier_threshold

	def build(self, snapshot_rows):
		points = []
		for row in snapshot_rows or []:
			timestamp = getattr(row, "created_at", None)
			if timestamp is None or timestamp > self.as_of:
				continue
			if getattr(row, "source", None) != CANONICAL_SNAPSHOT_SOURCE:
				continue
			equity = _extract_snapshot_equity(getattr(row, "notes", None))
			if equity is None or equity <= 0:
				continue
			points.append({"timestamp": timestamp, "equity_usdt": equity})
		points.sort(key=lambda point: point["timestamp"])
		if not points:
			return self._empty(points)

		latest = points[-1]
		if self.as_of - latest["timestamp"] > self.max_latest_age:
			return self._empty(points)

		changes = {}
		for label, window in self.WINDOWS.items():
			historical = self._point_for_window(points, label)
			if historical is None:
				changes[label] = None
				continue
			amount = latest["equity_usdt"] - historical["equity_usdt"]
			percent = amount / historical["equity_usdt"] * Decimal("100")
			changes[label] = {"amount_usdt": amount, "percent": percent}

		chart_start = self.as_of - self.CHART_WINDOW
		chart_points = [
			point for point in points
			if chart_start <= point["timestamp"] <= self.as_of
		]
		chart_points = self._visual_chart_points(chart_points, chart_start)
		if len(chart_points) < 2:
			chart_points = []
		return {
			"changes": changes,
			"chart_points": chart_points,
			"chart_available": bool(chart_points),
			"latest_point": latest,
			"usable": True,
		}

	def _empty(self, points):
		return {
			"changes": {"24h": None, "7d": None, "30d": None},
			"chart_points": [],
			"chart_available": False,
			"latest_point": points[-1] if points else None,
			"usable": False,
		}

	def _point_for_window(self, points, label):
		target_age = self.WINDOWS[label]
		min_age, max_age = self.WINDOW_TOLERANCES[label]
		candidates = []
		for point in points:
			age = self.as_of - point["timestamp"]
			if min_age <= age <= max_age:
				candidates.append(point)
		if not candidates:
			return None
		return min(
			candidates,
			key=lambda point: (
				abs((self.as_of - point["timestamp"]) - target_age),
				point["timestamp"],
			),
		)

	def _visual_chart_points(self, points, chart_start):
		return self._filter_visual_outliers(
			self._downsample_chart_points(points, chart_start)
		)

	def _downsample_chart_points(self, points, chart_start):
		if not points:
			return []
		max_points = self.max_chart_points
		if max_points is None or max_points <= 0 or len(points) <= max_points:
			return list(points)
		total_seconds = max((self.as_of - chart_start).total_seconds(), 1)
		bucket_seconds = total_seconds / max_points
		buckets = {}
		for point in points:
			elapsed = max((point["timestamp"] - chart_start).total_seconds(), 0)
			bucket_index = min(int(elapsed / bucket_seconds), max_points - 1)
			buckets[bucket_index] = point
		return [buckets[index] for index in sorted(buckets)]

	def _filter_visual_outliers(self, points):
		if not points:
			return []
		threshold = self.chart_outlier_threshold
		if threshold is None or threshold <= 0:
			return list(points)
		filtered = []
		previous = None
		# Filtering is visual-only and uses the last accepted point as the
		# comparison baseline so rejected outliers do not influence future chart points.
		for point in points:
			equity = _to_decimal(point.get("equity_usdt"))
			if equity is None or equity <= 0:
				continue
			if previous is not None:
				change_ratio = abs(equity - previous) / previous
				if change_ratio > threshold:
					continue
			filtered.append(point)
			previous = equity
		return filtered


class PortfolioEquityChartRenderer:
	def __init__(self, width=720, height=360):
		self.width = width
		self.height = height

	def render_png(self, points):
		if len(points or []) < 2:
			return None
		width = self.width
		height = self.height
		margin_left = 56
		margin_right = 24
		margin_top = 44
		margin_bottom = 48
		pixels = bytearray([255, 255, 255] * width * height)
		plot_left = margin_left
		plot_right = width - margin_right
		plot_top = margin_top
		plot_bottom = height - margin_bottom

		self._draw_text(pixels, width, height, 56, 18, "EQUITY HISTORY", (17, 24, 39), scale=2)
		self._line(pixels, width, plot_left, plot_bottom, plot_right, plot_bottom, (148, 163, 184))
		self._line(pixels, width, plot_left, plot_top, plot_left, plot_bottom, (148, 163, 184))
		for idx in range(1, 4):
			y = plot_top + (plot_bottom - plot_top) * idx // 4
			self._line(pixels, width, plot_left, y, plot_right, y, (241, 245, 249))

		timestamps = [point["timestamp"] for point in points]
		values = [_to_decimal(point["equity_usdt"]) for point in points]
		min_value = min(values)
		max_value = max(values)
		if min_value == max_value:
			min_value -= Decimal("1")
			max_value += Decimal("1")
		start = min(timestamps)
		end = max(timestamps)
		total_seconds = max((end - start).total_seconds(), 1)
		value_range = max_value - min_value
		coords = []
		for point, value in zip(points, values):
			x_ratio = Decimal(str((point["timestamp"] - start).total_seconds() / total_seconds))
			y_ratio = (value - min_value) / value_range
			x = plot_left + int(x_ratio * (plot_right - plot_left))
			y = plot_bottom - int(y_ratio * (plot_bottom - plot_top))
			coords.append((x, y))
		for left, right in zip(coords, coords[1:]):
			self._line(pixels, width, left[0], left[1], right[0], right[1], (37, 99, 235), thickness=3)
		return self._png_bytes(width, height, pixels)

	def _set_pixel(self, pixels, width, height, x, y, color):
		if 0 <= x < width and 0 <= y < height:
			offset = (y * width + x) * 3
			pixels[offset:offset + 3] = bytes(color)

	def _line(self, pixels, width, x0, y0, x1, y1, color, thickness=1):
		height = self.height
		dx = abs(x1 - x0)
		dy = -abs(y1 - y0)
		sx = 1 if x0 < x1 else -1
		sy = 1 if y0 < y1 else -1
		err = dx + dy
		while True:
			for ox in range(-(thickness // 2), thickness // 2 + 1):
				for oy in range(-(thickness // 2), thickness // 2 + 1):
					self._set_pixel(pixels, width, height, x0 + ox, y0 + oy, color)
			if x0 == x1 and y0 == y1:
				break
			e2 = 2 * err
			if e2 >= dy:
				err += dy
				x0 += sx
			if e2 <= dx:
				err += dx
				y0 += sy

	def _draw_text(self, pixels, width, height, x, y, text, color, scale=1):
		cursor = x
		for char in str(text).upper():
			if char == " ":
				cursor += 4 * scale
				continue
			glyph = _CHART_FONT.get(char)
			if glyph is None:
				cursor += 4 * scale
				continue
			for row_index, row in enumerate(glyph):
				for column_index, bit in enumerate(row):
					if bit != "1":
						continue
					for ox in range(scale):
						for oy in range(scale):
							self._set_pixel(
								pixels,
								width,
								height,
								cursor + column_index * scale + ox,
								y + row_index * scale + oy,
								color,
							)
			cursor += (len(glyph[0]) + 1) * scale

	def _png_bytes(self, width, height, pixels):
		raw = bytearray()
		row_width = width * 3
		for y in range(height):
			raw.append(0)
			start = y * row_width
			raw.extend(pixels[start:start + row_width])
		chunks = [
			self._chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
			self._chunk(b"IDAT", zlib.compress(bytes(raw), level=9)),
			self._chunk(b"IEND", b""),
		]
		return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)

	def _chunk(self, chunk_type, data):
		crc = binascii.crc32(chunk_type + data) & 0xFFFFFFFF
		return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _unavailable_summary(free_usdt, realized_today, realized_drivers=None, equity_history=None):
	return {
		"equity_usdt": None,
		"free_usdt": free_usdt,
		"open_value_usdt": None,
		"unrealized_pnl_usdt": None,
		"unrealized_pnl_pct": None,
		"realized_today": realized_today,
		"drivers_24h": {
			"realized": _driver_from_rows(realized_drivers),
			"unrealized": None,
		},
		"changes": _history_changes(equity_history),
		"chart_points": _history_chart_points(equity_history),
		"chart_available": bool(_history_chart_points(equity_history)),
		"best_contributor": None,
		"worst_contributor": None,
		"unavailable_symbols": [],
	}


def _history_changes(equity_history):
	if not isinstance(equity_history, dict):
		return {"24h": None, "7d": None, "30d": None}
	return equity_history.get("changes") or {"24h": None, "7d": None, "30d": None}


def _history_chart_points(equity_history):
	if not isinstance(equity_history, dict):
		return []
	return equity_history.get("chart_points") or []


def _extract_snapshot_equity(notes):
	if not isinstance(notes, dict):
		return None
	# Canonical historical equity is only
	# bot.portfolio_snapshots.notes.portfolio_equity_usdt.
	return _to_decimal(notes.get("portfolio_equity_usdt"))


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


def _driver(value):
	if not value:
		return "<code>unavailable</code>"
	if value.get("status") == "none":
		return "<code>none</code>"
	return (
		f"{escape(str(value['symbol']))} "
		f"<code>{_signed_decimal(value['pnl_usdt'])} USDT</code>"
	)


def _driver_from_rows(rows):
	if rows is None:
		return None
	if not rows:
		return {"status": "none"}
	candidates = []
	for row in rows:
		symbol = row.get("symbol") if isinstance(row, dict) else getattr(row, "symbol", None)
		pnl_usdt = row.get("pnl_usdt") if isinstance(row, dict) else getattr(row, "pnl_usdt", None)
		pnl_usdt = _to_decimal(pnl_usdt)
		if not symbol or pnl_usdt is None or pnl_usdt == 0:
			continue
		candidates.append({"symbol": symbol, "pnl_usdt": pnl_usdt})
	if not candidates:
		return {"status": "none"}
	return max(candidates, key=lambda row: (abs(row["pnl_usdt"]), str(row["symbol"])))


def _unrealized_driver(contributors, change_24h):
	if not contributors:
		return None
	if isinstance(change_24h, dict):
		change_amount = _to_decimal(change_24h.get("amount_usdt"))
		if change_amount is not None and change_amount < 0:
			return min(contributors, key=lambda row: row["pnl_usdt"])
		if change_amount is not None and change_amount > 0:
			return max(contributors, key=lambda row: row["pnl_usdt"])
	return max(contributors, key=lambda row: (abs(row["pnl_usdt"]), str(row["symbol"])))


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
