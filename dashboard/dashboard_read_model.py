from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import List

from django.db import DatabaseError
from django.db.models import Count, Sum
from django.utils import timezone

from dashboard.dust_read_model import get_dust_overview_context
from core.models import BotControl
from core.trading_models import BotHealthcheck, LotClosure, Portfolio, PositionLot, TradeOperation


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
		"valuation_consistency": _empty_valuation_consistency(),
		"fee_summary": _empty_fee_summary(),
		"quote_fee_summary": _empty_quote_fee_summary(),
		"performance_kpis": _empty_performance_kpis(),
		"latest_trade": None,
		"recent_operations": [],
		"reconciliation": _empty_reconciliation(),
		"dust_summary": _empty_dust_summary(),
		"data_error": None,
		"is_demo": False,
	}

	try:
		portfolio_rows = list(Portfolio.objects.all().order_by("symbol"))
		context["portfolio_summary"] = _build_portfolio_summary(portfolio_rows)
	except DatabaseError as exc:
		_add_data_error(context, "portfolio", exc)
		portfolio_rows = []

	try:
		context["bot_status"] = _build_bot_status()
	except DatabaseError as exc:
		_add_data_error(context, "bot status", exc)

	try:
		context["fee_summary"] = _build_fee_summary()
	except DatabaseError as exc:
		_add_data_error(context, "fees", exc)

	try:
		context["quote_fee_summary"] = _build_quote_fee_summary()
	except DatabaseError as exc:
		_add_data_error(context, "USDT fees", exc)

	try:
		context["performance_kpis"] = _build_performance_kpis()
	except DatabaseError as exc:
		_add_data_error(context, "performance KPIs", exc)

	try:
		context["recent_operations"] = _build_recent_operations()
		context["latest_trade"] = _build_latest_trade()
	except DatabaseError as exc:
		_add_data_error(context, "latest trade", exc)

	try:
		open_lots = _open_lots_by_symbol()
		context["reconciliation"] = _build_reconciliation(portfolio_rows, open_lots)
		context["valuation_consistency"] = _build_valuation_consistency(portfolio_rows, open_lots)
	except DatabaseError as exc:
		_add_data_error(context, "reconciliation", exc)

	context["dust_summary"] = get_dust_overview_context()
	if context["dust_summary"].get("data_error"):
		_add_data_error(context, "dust detections", context["dust_summary"]["data_error"])

	return DashboardReadModel(
		context=context,
		queries=_important_queries(),
		assumptions=_assumptions(),
	)


def get_demo_dashboard_context():
	now = timezone.now()
	context = {
		"bot_control": SimpleNamespace(is_paused=False),
		"bot_status": {
			"row": SimpleNamespace(),
			"status": "ok",
			"probe_message": "Demo heartbeat received",
			"created_at": now,
			"read_only": True,
			"is_stale": False,
			"stale_after_minutes": 15,
		},
		"portfolio_summary": {
			"rows_count": 3,
			"total_estimated_value": Decimal("1842.73"),
			"material_positions_count": 2,
			"dust_positions_count": 1,
		},
		"valuation_consistency": {
			"portfolio_value": Decimal("1842.73"),
			"lots_value": Decimal("1842.73"),
			"drift_value": Decimal("0"),
			"portfolio_missing_price_count": 0,
			"lots_missing_price_count": 0,
			"missing_price_count": 0,
			"has_missing_prices": False,
			"portfolio_rows_count": 3,
			"open_lots_symbol_count": 2,
			"dust_positions_count": 1,
		},
		"fee_summary": {
			"asset_count": 2,
			"fill_count": 7,
			"rows": [
				{"asset": "USDT", "total": Decimal("3.42"), "fill_count": 5},
				{"asset": "BNB", "total": Decimal("0.0018"), "fill_count": 2},
			],
		},
		"quote_fee_summary": {
			"total_fees_usdt": Decimal("3.42"),
			"total_operations": 5,
			"by_side": {
				"BUY": {"total_fee_usdt": Decimal("2.10"), "operations_count": 3},
				"SELL": {"total_fee_usdt": Decimal("1.32"), "operations_count": 2},
			},
		},
		"performance_kpis": {
			**_empty_performance_kpis(),
			"gross_realized_pnl": Decimal("128.55"),
			"total_fees_usdt": Decimal("3.42"),
			"net_realized_pnl": Decimal("125.13"),
			"closures_count": 6,
			"winning_closures_count": 4,
			"losing_closures_count": 2,
			"breakeven_closures_count": 0,
			"win_rate": Decimal("66.66666666666666666666666667"),
			"average_win": Decimal("42.25"),
			"average_loss": Decimal("-20.225"),
			"profit_factor": Decimal("4.177997527812113720642768850"),
			"gross_deployed_capital": Decimal("2500.00"),
			"bot_realized_pnl": Decimal("128.55"),
			"pnl_by_symbol": [
				{"symbol": "ETHUSDT", "realized_pnl": Decimal("92.50"), "closures_count": 3},
				{"symbol": "BTCUSDT", "realized_pnl": Decimal("36.05"), "closures_count": 3},
			],
			"pnl_by_day": [
				{"date": now.date(), "realized_pnl": Decimal("128.55"), "closures_count": 6},
			],
		},
		"latest_trade": {
			"row": SimpleNamespace(
				side="BUY",
				symbol="ETHUSDT",
				status="FILLED",
				executed_base_qty=Decimal("0.25000000"),
				executed_at=now - timedelta(minutes=8),
			),
			"gross_quote": Decimal("812.40"),
			"net_quote": Decimal("812.40"),
		},
		"recent_operations": [
			SimpleNamespace(
				side="BUY",
				symbol="ETHUSDT",
				status="FILLED",
				executed_base_qty=Decimal("0.25000000"),
				gross_quote=Decimal("812.40"),
				net_quote=Decimal("812.40"),
				executed_at=now - timedelta(minutes=8),
				created_at=now - timedelta(minutes=8),
			),
			SimpleNamespace(
				side="SELL",
				symbol="BTCUSDT",
				status="FILLED",
				executed_base_qty=Decimal("0.00500000"),
				gross_quote=Decimal("360.10"),
				net_quote=Decimal("358.95"),
				executed_at=now - timedelta(hours=2),
				created_at=now - timedelta(hours=2),
			),
		],
		"reconciliation": {
			"status": "ok",
			"warning_count": 0,
			"warnings": [],
			"checked_count": 2,
			"tolerance": DRIFT_TOLERANCE,
		},
		"dust_summary": {
			"total_detections": 3,
			"critical_count": 1,
			"warning_count": 2,
			"info_count": 0,
			"latest_run_id": "demo-run-001",
			"latest_detected_at": now - timedelta(minutes=3),
			"top_grouped_detections": [
				{
					"symbol": "BNBUSDT",
					"asset": "BNB",
					"severity": "warning",
					"event_type": "dust_candidate_detected",
					"reason": "below_min_notional",
					"detections_count": 2,
					"latest_detected_at": now - timedelta(minutes=3),
					"latest_run_id": "demo-run-001",
					"latest_estimated_value_usdt": Decimal("1.42"),
					"latest_estimated_delta_value_usdt": Decimal("0"),
					"latest_suggested_action": "monitor",
					"display_reason": "Below min notional",
					"operator_label": "Below min notional",
					"operator_badge": "badge-info",
					"detail_querystring": "symbol=BNBUSDT&asset=BNB&reason=below_min_notional&event_type=dust_candidate_detected&severity=warning",
				},
			],
			"active_operational_issues": [
				{
					"symbol": "BNBUSDT",
					"severity": "warning",
					"latest_detected_at": now - timedelta(minutes=3),
					"latest_estimated_value_usdt": Decimal("1.42"),
					"latest_estimated_delta_value_usdt": Decimal("0"),
					"display_reason": "Below min notional",
					"operator_badge": "badge-info",
					"detail_querystring": "symbol=BNBUSDT&asset=BNB&reason=below_min_notional&event_type=dust_candidate_detected&severity=warning",
				},
			],
			"total_estimated_value_usdt": Decimal("1.42"),
			"data_error": None,
		},
		"data_error": None,
		"is_demo": True,
		"dashboard_user_label": "Public demo",
	}
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


def _add_data_error(context, section, exc):
	message = f"{section}: {exc}"
	if context["data_error"]:
		context["data_error"] = f"{context['data_error']} | {message}"
	else:
		context["data_error"] = message


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


def _build_valuation_consistency(portfolio_rows, open_lots):
	portfolio_value = Decimal("0")
	lots_value = Decimal("0")
	portfolio_missing_price_count = 0
	lots_missing_price_count = 0
	portfolio_by_symbol = {row.symbol: row for row in portfolio_rows}

	for row in portfolio_rows:
		value = _position_value(row.quantity, row.current_price)
		if value is None:
			portfolio_missing_price_count += 1
			continue
		portfolio_value += value

	for symbol, open_lot in open_lots.items():
		portfolio = portfolio_by_symbol.get(symbol)
		current_price = portfolio.current_price if portfolio else None
		value = _position_value(open_lot["open_quantity"], current_price)
		if value is None:
			lots_missing_price_count += 1
			continue
		lots_value += value

	missing_price_count = portfolio_missing_price_count + lots_missing_price_count
	return {
		"portfolio_value": portfolio_value,
		"lots_value": lots_value,
		"drift_value": portfolio_value - lots_value,
		"portfolio_missing_price_count": portfolio_missing_price_count,
		"lots_missing_price_count": lots_missing_price_count,
		"missing_price_count": missing_price_count,
		"has_missing_prices": missing_price_count > 0,
		"portfolio_rows_count": len(portfolio_rows),
		"open_lots_symbol_count": len(open_lots),
		"dust_positions_count": _build_portfolio_summary(portfolio_rows)["dust_positions_count"],
	}


def _empty_valuation_consistency():
	return {
		"portfolio_value": Decimal("0"),
		"lots_value": Decimal("0"),
		"drift_value": Decimal("0"),
		"portfolio_missing_price_count": 0,
		"lots_missing_price_count": 0,
		"missing_price_count": 0,
		"has_missing_prices": False,
		"portfolio_rows_count": 0,
		"open_lots_symbol_count": 0,
		"dust_positions_count": 0,
	}


def _build_fee_summary():
	rows = (
		TradeOperation.objects
		.filter(fee_amount__isnull=False)
		.values("fee_asset")
		.annotate(total=Sum("fee_amount"), fill_count=Sum("fill_count"))
		.order_by("fee_asset")
	)
	fee_rows = [
		{
			"asset": row["fee_asset"] or "unknown",
			"total": row["total"] or Decimal("0"),
			"fill_count": row["fill_count"] or 0,
		}
		for row in rows
	]
	return {
		"asset_count": len(fee_rows),
		"fill_count": sum(row["fill_count"] for row in fee_rows),
		"rows": fee_rows,
	}


def _empty_fee_summary():
	return {
		"asset_count": 0,
		"fill_count": 0,
		"rows": [],
	}


def _build_quote_fee_summary():
	rows = (
		TradeOperation.objects
		.filter(status="FILLED", quote_asset="USDT")
		.values("side")
		.annotate(
			total_fee_usdt=Sum("fee_amount_in_quote"),
			operations_count=Count("*"),
		)
		.order_by("side")
	)
	by_side = _empty_quote_fee_summary()["by_side"]
	total_fees_usdt = Decimal("0")
	total_operations = 0

	for row in rows:
		side = row["side"] or "unknown"
		total_fee_usdt = row["total_fee_usdt"] or Decimal("0")
		operations_count = row["operations_count"] or 0
		total_fees_usdt += total_fee_usdt
		total_operations += operations_count

		if side in by_side:
			by_side[side] = {
				"total_fee_usdt": total_fee_usdt,
				"operations_count": operations_count,
			}

	return {
		"total_fees_usdt": total_fees_usdt,
		"total_operations": total_operations,
		"by_side": by_side,
	}


def _empty_quote_fee_summary():
	return {
		"total_fees_usdt": Decimal("0"),
		"total_operations": 0,
		"by_side": {
			"BUY": {"total_fee_usdt": Decimal("0"), "operations_count": 0},
			"SELL": {"total_fee_usdt": Decimal("0"), "operations_count": 0},
		},
	}


def _build_performance_kpis():
	closure_rows = list(
		LotClosure.objects
		.values("trade_operation_id", "realized_pnl")
		.order_by("trade_operation_id", "id")
	)
	operation_ids = {
		row["trade_operation_id"]
		for row in closure_rows
		if row.get("trade_operation_id") is not None
	}
	operations = {}
	if operation_ids:
		for row in (
			TradeOperation.objects
			.filter(id__in=operation_ids)
			.values("id", "symbol", "client_order_id", "raw_payload", "executed_at", "created_at")
		):
			operations[row["id"]] = {
				"symbol": row.get("symbol") or "unknown",
				"manual_correction": _is_manual_correction_operation(row),
				"timestamp": row.get("executed_at") or row.get("created_at"),
			}

	fee_rows = (
		TradeOperation.objects
		.filter(status="FILLED", quote_asset="USDT")
		.values("fee_amount_in_quote")
	)
	buy_rows = (
		TradeOperation.objects
		.filter(status="FILLED", side="BUY")
		.values("gross_quote")
	)
	return _calculate_performance_kpis(closure_rows, operations, fee_rows, buy_rows)


def _calculate_performance_kpis(closure_rows, operation_rows, fee_rows, buy_rows):
	total_fees_usdt = sum(
		(row.get("fee_amount_in_quote") or Decimal("0"))
		for row in fee_rows
	)
	gross_deployed_capital = sum(
		(row.get("gross_quote") or Decimal("0"))
		for row in buy_rows
	)

	gross_realized_pnl = Decimal("0")
	gross_profit = Decimal("0")
	gross_loss = Decimal("0")
	win_count = 0
	loss_count = 0
	breakeven_count = 0
	closures_count = 0
	bot_realized_pnl = Decimal("0")
	manual_adjustment_pnl = Decimal("0")
	manual_corrections_split_available = False
	pnl_by_symbol = {}
	pnl_by_day = {}

	for row in closure_rows:
		realized_pnl = row.get("realized_pnl")
		if realized_pnl is None:
			continue

		closures_count += 1
		gross_realized_pnl += realized_pnl
		if realized_pnl > 0:
			win_count += 1
			gross_profit += realized_pnl
		elif realized_pnl < 0:
			loss_count += 1
			gross_loss += realized_pnl
		else:
			breakeven_count += 1

		operation = operation_rows.get(row.get("trade_operation_id"), {})
		if operation.get("manual_correction"):
			manual_adjustment_pnl += realized_pnl
			manual_corrections_split_available = True
		else:
			bot_realized_pnl += realized_pnl

		symbol = operation.get("symbol") or "unknown"
		symbol_row = pnl_by_symbol.setdefault(
			symbol,
			{"symbol": symbol, "realized_pnl": Decimal("0"), "closures_count": 0},
		)
		symbol_row["realized_pnl"] += realized_pnl
		symbol_row["closures_count"] += 1

		timestamp = operation.get("timestamp")
		if timestamp is not None:
			day = timezone.localtime(timestamp).date() if timezone.is_aware(timestamp) else timestamp.date()
			day_row = pnl_by_day.setdefault(
				day,
				{"date": day, "realized_pnl": Decimal("0"), "closures_count": 0},
			)
			day_row["realized_pnl"] += realized_pnl
			day_row["closures_count"] += 1

	decided_count = win_count + loss_count
	win_rate = None
	if decided_count:
		win_rate = Decimal(win_count) / Decimal(decided_count) * Decimal("100")

	average_win = gross_profit / Decimal(win_count) if win_count else None
	average_loss = gross_loss / Decimal(loss_count) if loss_count else None
	profit_factor = None
	if gross_loss != 0:
		profit_factor = gross_profit / abs(gross_loss)

	return {
		"gross_realized_pnl": gross_realized_pnl,
		"total_fees_usdt": total_fees_usdt,
		"net_realized_pnl": gross_realized_pnl - total_fees_usdt,
		"closures_count": closures_count,
		"winning_closures_count": win_count,
		"losing_closures_count": loss_count,
		"breakeven_closures_count": breakeven_count,
		"win_rate": win_rate,
		"average_win": average_win,
		"average_loss": average_loss,
		"profit_factor": profit_factor,
		"gross_deployed_capital": gross_deployed_capital,
		"bot_realized_pnl": bot_realized_pnl,
		"manual_adjustment_pnl": manual_adjustment_pnl,
		"manual_corrections_split_available": manual_corrections_split_available,
		"manual_corrections_note": (
			"Manual/accounting corrections are split only when identifiable from trade operation metadata; otherwise realized PnL remains included in totals."
		),
		"fee_limitations_note": (
			"USDT fees use fee_amount_in_quote for FILLED USDT-quote operations. Fees that cannot be normalized to USDT are excluded."
		),
		"pnl_by_symbol": sorted(
			pnl_by_symbol.values(),
			key=lambda item: item["realized_pnl"],
			reverse=True,
		),
		"pnl_by_day": sorted(
			pnl_by_day.values(),
			key=lambda item: item["date"],
		),
	}


def _is_manual_correction_operation(row):
	raw_payload = row.get("raw_payload")
	if isinstance(raw_payload, dict):
		source = str(raw_payload.get("source") or "").upper()
		if raw_payload.get("correction_id") or source == "MANUAL_CORRECTION":
			return True
	client_order_id = str(row.get("client_order_id") or "").lower()
	return "manual" in client_order_id or "correction" in client_order_id


def _empty_performance_kpis():
	return {
		"gross_realized_pnl": Decimal("0"),
		"total_fees_usdt": Decimal("0"),
		"net_realized_pnl": Decimal("0"),
		"closures_count": 0,
		"winning_closures_count": 0,
		"losing_closures_count": 0,
		"breakeven_closures_count": 0,
		"win_rate": None,
		"average_win": None,
		"average_loss": None,
		"profit_factor": None,
		"gross_deployed_capital": Decimal("0"),
		"bot_realized_pnl": Decimal("0"),
		"manual_adjustment_pnl": Decimal("0"),
		"manual_corrections_split_available": False,
		"manual_corrections_note": (
			"Manual/accounting corrections are split only when identifiable from trade operation metadata; otherwise realized PnL remains included in totals."
		),
		"fee_limitations_note": (
			"USDT fees use fee_amount_in_quote for FILLED USDT-quote operations. Fees that cannot be normalized to USDT are excluded."
		),
		"pnl_by_symbol": [],
		"pnl_by_day": [],
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


def _build_recent_operations(limit=5):
	return list(
		TradeOperation.objects
		.order_by("-executed_at", "-created_at", "-id")[:limit]
	)


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


def _empty_dust_summary():
	return {
		"total_detections": 0,
		"critical_count": 0,
		"warning_count": 0,
		"info_count": 0,
		"latest_run_id": None,
		"latest_detected_at": None,
		"top_grouped_detections": [],
		"active_operational_issues": [],
		"total_estimated_value_usdt": Decimal("0"),
		"data_error": None,
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
		"bot.portfolio + bot.position_lots: Decimal valuation consistency using portfolio current_price",
		"bot.trade_operations: SUM(fee_amount) GROUP BY fee_asset",
		"bot.trade_operations: SUM(fee_amount_in_quote), COUNT(*) WHERE status = FILLED AND quote_asset = USDT GROUP BY side",
		"bot.lot_closures + bot.trade_operations: realized PnL KPIs grouped by symbol/day with identifiable manual correction split",
		"bot.trade_operations: SUM(gross_quote) WHERE status = FILLED AND side = BUY for approximate gross deployed capital",
		"bot.trade_operations: latest row ordered by executed_at/created_at/id desc",
		"bot.trade_operations: latest five rows ordered by executed_at/created_at/id desc for compact operational overview",
		"bot.position_lots: SUM(quantity_open) WHERE quantity_open > 0 GROUP BY symbol",
		"bot.dust_detections: operational dust summary and top detections, read-only",
	]


def _assumptions():
	return [
		"Dashboard writes only to django.core_botcontrol via the existing Stop/Resume controls.",
		"portfolio is used only as a projection/read model.",
		"position_lots remains the accounting source of truth for open inventory.",
		"Drift is surfaced as a dashboard warning; no trading action is executed.",
		"Missing current_price values are counted and excluded from value totals.",
		"Performance KPIs are operational read-only metrics, not audited accounting statements.",
		"Non-USDT or unnormalized fees are excluded from normalized USDT fee totals.",
	]
