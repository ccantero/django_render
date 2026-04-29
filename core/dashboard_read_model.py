from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import List

from django.db import DatabaseError
from django.db.models import Count, Sum
from django.utils import timezone

from core.models import BotControl
from core.trading_models import BotHealthcheck, Portfolio, PositionLot, TradeOperation


DRIFT_TOLERANCE = Decimal("0.00000001")
DUST_MIN_VALUE = Decimal("5")
HEALTHCHECK_STALE_AFTER = timedelta(minutes=15)


@dataclass
class DashboardReadModel:
	context: dict
	queries: List[str]
	assumptions: List[str]


def get_dashboard_context():
	context = {
		"bot_control": _get_bot_control(),
		"bot_status": _empty_bot_status(),
		"portfolio_summary": _empty_portfolio_summary(),
		"latest_trade": None,
		"reconciliation": _empty_reconciliation(),
		"data_error": None,
	}

	try:
		portfolio_rows = list(Portfolio.objects.all().order_by("symbol"))
		open_lots = _open_lots_by_symbol()

		context.update({
			"bot_status": _build_bot_status(),
			"portfolio_summary": _build_portfolio_summary(portfolio_rows),
			"latest_trade": _build_latest_trade(),
			"reconciliation": _build_reconciliation(portfolio_rows, open_lots),
		})
	except DatabaseError as exc:
		context["data_error"] = str(exc)

	return DashboardReadModel(
		context=context,
		queries=_important_queries(),
		assumptions=_assumptions(),
	)


def _get_bot_control():
	try:
		return BotControl.get_solo()
	except DatabaseError:
		return None


def _build_bot_status():
	latest = BotHealthcheck.objects.order_by("-created_at", "-id").first()
	if latest is None:
		return _empty_bot_status()

	created_at = latest.created_at
	is_stale = (
		created_at is not None
		and timezone.now() - created_at > HEALTHCHECK_STALE_AFTER
	)

	return {
		"row": latest,
		"status": latest.status,
		"probe_message": latest.probe_message,
		"created_at": created_at,
		"read_only": _details_read_only(latest.details),
		"is_stale": is_stale,
		"stale_after_minutes": 15,
	}


def _empty_bot_status():
	return {
		"row": None,
		"status": None,
		"probe_message": None,
		"created_at": None,
		"read_only": None,
		"is_stale": False,
		"stale_after_minutes": 15,
	}


def _details_read_only(details):
	if not isinstance(details, dict):
		return None
	return details.get("read_only")


def _build_portfolio_summary(portfolio_rows):
	total_estimated_value = Decimal("0")
	material_positions_count = 0
	dust_positions_count = 0

	for row in portfolio_rows:
		value = _position_value(row.quantity, row.current_price)
		if value is None:
			continue

		total_estimated_value += value
		if value >= DUST_MIN_VALUE:
			material_positions_count += 1
		elif value > Decimal("0"):
			dust_positions_count += 1

	return {
		"rows_count": len(portfolio_rows),
		"total_estimated_value": total_estimated_value,
		"material_positions_count": material_positions_count,
		"dust_positions_count": dust_positions_count,
	}


def _empty_portfolio_summary():
	return {
		"rows_count": 0,
		"total_estimated_value": Decimal("0"),
		"material_positions_count": 0,
		"dust_positions_count": 0,
	}


def _build_latest_trade():
	row = TradeOperation.objects.order_by("-executed_at", "-created_at", "-id").first()
	if row is None:
		return {"row": None, "gross_quote": None, "net_quote": None}
	return {
		"row": row,
		"gross_quote": row.gross_quote,
		"net_quote": row.net_quote,
	}


def _open_lots_by_symbol():
	rows = (
		PositionLot.objects
		.filter(remaining_quantity__gt=0)
		.values("symbol")
		.annotate(open_quantity=Sum("remaining_quantity"), open_lot_count=Count("lot_id"))
		.order_by("symbol")
	)
	return {row["symbol"]: row for row in rows}


def _build_reconciliation(portfolio_rows, open_lots):
	warnings = []
	checked_count = 0
	portfolio_by_symbol = {row.symbol: row for row in portfolio_rows}

	for symbol in sorted(set(portfolio_by_symbol) | set(open_lots)):
		portfolio = portfolio_by_symbol.get(symbol)
		open_lot = open_lots.get(symbol)
		portfolio_quantity = portfolio.quantity if portfolio else Decimal("0")
		open_quantity = open_lot["open_quantity"] if open_lot else Decimal("0")
		diff = portfolio_quantity - open_quantity
		is_material = _is_material(portfolio)

		if is_material:
			checked_count += 1
			if abs(diff) > DRIFT_TOLERANCE:
				warnings.append({
					"symbol": symbol,
					"portfolio_quantity": portfolio_quantity,
					"open_lot_quantity": open_quantity,
					"diff": diff,
				})

	return {
		"status": "warning" if warnings else "ok",
		"warning_count": len(warnings),
		"warnings": warnings,
		"checked_count": checked_count,
		"tolerance": DRIFT_TOLERANCE,
	}


def _empty_reconciliation():
	return {
		"status": "ok",
		"warning_count": 0,
		"warnings": [],
		"checked_count": 0,
		"tolerance": DRIFT_TOLERANCE,
	}


def _is_material(portfolio):
	if portfolio is None:
		return False
	value = _position_value(portfolio.quantity, portfolio.current_price)
	return value is not None and value >= DUST_MIN_VALUE


def _position_value(quantity, current_price):
	if quantity is None or current_price is None:
		return None
	return quantity * current_price


def _important_queries():
	return [
		"bot.bot_healthcheck: latest row ordered by created_at desc",
		"bot.portfolio: count rows and sum Decimal quantity * current_price",
		"bot.trade_operations: latest row ordered by executed_at/created_at/id desc",
		"bot.position_lots: SUM(quantity_open) WHERE quantity_open > 0 GROUP BY symbol",
	]


def _assumptions():
	return [
		"Dashboard writes only to django.core_botcontrol via the existing Stop/Resume controls.",
		"portfolio is used only as a projection/read model.",
		"position_lots remains the accounting source of truth for open inventory.",
		"Drift is surfaced as a dashboard warning; no trading action is executed.",
	]
