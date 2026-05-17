from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone

from core.trading_models import LotClosure, PositionLot, TradeOperation


UNVERSIONED = "unversioned"
DEFAULT_CHURN_THRESHOLD_MINUTES = 60
HOLD_BUCKET_LABELS = ("<15m", "15m-1h", "1h-4h", "4h-24h", ">24h")


@dataclass(frozen=True)
class OperationalKpiFilters:
	date_from: object = None
	date_to: object = None
	strategy_version: str = ""
	symbol: str = ""
	churn_threshold_minutes: int = DEFAULT_CHURN_THRESHOLD_MINUTES


@dataclass
class OperationalKpiReadModel:
	context: dict
	queries: list
	assumptions: list


def get_operational_kpis_context(params=None):
	filters = _parse_filters(params)
	context = _empty_context(filters)
	try:
		operations = _load_operations(filters)
		sell_operations = {
			row["id"]: row
			for row in operations
			if row["side"] == "SELL" and not row["manual_correction"]
		}
		closure_rows = list(
			LotClosure.objects
			.filter(trade_operation_id__in=sell_operations.keys())
			.values("trade_operation_id", "lot_id", "realized_pnl")
		) if sell_operations else []
		lot_ids = {row["lot_id"] for row in closure_rows if row.get("lot_id")}
		opened_lots = dict(
			PositionLot.objects
			.filter(lot_id__in=lot_ids)
			.values_list("lot_id", "opened_at")
		) if lot_ids else {}
		calculated = _calculate_operational_kpis(
			closure_rows=closure_rows,
			sell_operations=sell_operations,
			opened_lots=opened_lots,
			operations=operations,
			churn_threshold_minutes=filters.churn_threshold_minutes,
		)
		context.update(calculated)
	except DatabaseError as exc:
		context["data_error"] = f"Operational KPI data unavailable: {exc}"
	return OperationalKpiReadModel(
		context=context,
		queries=[
			"bot.trade_operations: bulk FILLED BUY/SELL read with optional date/symbol filters",
			"bot.lot_closures: closure rows for eligible SELL operation ids",
			"bot.position_lots: opened_at for linked closure lot ids",
		],
		assumptions=[
			"Operational KPIs are analytics, not audited accounting.",
			"Missing strategy_version is grouped as unversioned.",
			"Manual/accounting-only operations are excluded from trading-quality metrics.",
			"Normalized fees use trade_operations.fee_amount_in_quote only.",
		],
	)


def _load_operations(filters):
	query = TradeOperation.objects.filter(status="FILLED", side__in=["SELL", "BUY"])
	if filters.symbol:
		query = query.filter(symbol=filters.symbol)
	if filters.date_from:
		start = timezone.make_aware(datetime.combine(filters.date_from, time.min))
		query = query.filter(Q(executed_at__gte=start) | Q(executed_at__isnull=True, created_at__gte=start))
	if filters.date_to:
		end = timezone.make_aware(datetime.combine(filters.date_to, time.max))
		query = query.filter(Q(executed_at__lte=end) | Q(executed_at__isnull=True, created_at__lte=end))
	rows = query.order_by("symbol", "executed_at", "created_at", "id").values(
		"id", "symbol", "side", "executed_at", "created_at", "fee_amount_in_quote", "raw_payload"
	)
	operations = []
	for row in rows:
		payload = row.get("raw_payload") or {}
		strategy_version = _strategy_version(payload)
		if filters.strategy_version and strategy_version != filters.strategy_version:
			continue
		operations.append({
			"id": row["id"],
			"symbol": row["symbol"],
			"side": row["side"],
			"timestamp": row.get("executed_at") or row.get("created_at"),
			"fee_amount_in_quote": row.get("fee_amount_in_quote"),
			"strategy_version": strategy_version,
			"manual_correction": _is_manual_correction(payload),
			"sell_reason": payload.get("sell_reason"),
		})
	return operations


def _calculate_operational_kpis(
	closure_rows,
	sell_operations,
	opened_lots,
	operations,
	churn_threshold_minutes,
):
	closures_by_sell = {}
	for closure in closure_rows:
		sell = sell_operations.get(closure["trade_operation_id"])
		if not sell or sell.get("manual_correction"):
			continue
		closures_by_sell.setdefault(sell["id"], []).append(closure)

	strategy_rows = {}
	hold_seconds = []
	fee_rows_by_symbol = {}
	gross_realized_pnl = Decimal("0")
	total_fees = Decimal("0")
	gross_profit = Decimal("0")

	for sell_id, closures in closures_by_sell.items():
		sell = sell_operations[sell_id]
		version = sell["strategy_version"]
		row = strategy_rows.setdefault(version, {
			"strategy_version": version,
			"closed_trades_count": 0,
			"closures_count": 0,
			"gross_realized_pnl": Decimal("0"),
			"total_normalized_fees": Decimal("0"),
			"win_count": 0,
			"hold_seconds": [],
			"churn_count": 0,
			"eligible_filled_sell_count": 0,
			"churn_frequency": None,
		})
		trade_realized = sum((_to_decimal(c.get("realized_pnl")) or Decimal("0") for c in closures), Decimal("0"))
		fee = _to_decimal(sell.get("fee_amount_in_quote")) or Decimal("0")
		row["closed_trades_count"] += 1
		row["closures_count"] += len(closures)
		row["gross_realized_pnl"] += trade_realized
		row["total_normalized_fees"] += fee
		row["win_count"] += int(trade_realized > 0)
		gross_realized_pnl += trade_realized
		total_fees += fee
		if trade_realized > 0:
			gross_profit += trade_realized

		symbol_row = fee_rows_by_symbol.setdefault(sell["symbol"], {
			"symbol": sell["symbol"],
			"closed_trades_count": 0,
			"gross_profit": Decimal("0"),
			"gross_realized_pnl": Decimal("0"),
			"total_normalized_fees": Decimal("0"),
		})
		symbol_row["closed_trades_count"] += 1
		symbol_row["gross_realized_pnl"] += trade_realized
		symbol_row["total_normalized_fees"] += fee
		if trade_realized > 0:
			symbol_row["gross_profit"] += trade_realized

		for closure in closures:
			opened_at = opened_lots.get(closure.get("lot_id"))
			if not opened_at or not sell.get("timestamp"):
				continue
			duration_seconds = (sell["timestamp"] - opened_at).total_seconds()
			if duration_seconds < 0:
				continue
			hold_seconds.append(duration_seconds)
			row["hold_seconds"].append(duration_seconds)

	churn = _calculate_churn(operations, churn_threshold_minutes)
	for churn_row in churn["by_strategy_version"]:
		version_row = strategy_rows.setdefault(churn_row["strategy_version"], {
			"strategy_version": churn_row["strategy_version"],
			"closed_trades_count": 0,
			"closures_count": 0,
			"gross_realized_pnl": Decimal("0"),
			"total_normalized_fees": Decimal("0"),
			"win_count": 0,
			"hold_seconds": [],
			"churn_count": 0,
			"eligible_filled_sell_count": 0,
			"churn_frequency": None,
		})
		version_row["churn_count"] = churn_row["same_symbol_reentry_count"]
		version_row["eligible_filled_sell_count"] = churn_row["eligible_filled_sell_count"]
		version_row["churn_frequency"] = churn_row["same_symbol_reentry_frequency"]

	strategy_summary = []
	for row in strategy_rows.values():
		net_pnl = row["gross_realized_pnl"] - row["total_normalized_fees"]
		strategy_summary.append({
			"strategy_version": row["strategy_version"],
			"closed_trades_count": row["closed_trades_count"],
			"closures_count": row["closures_count"],
			"net_realized_pnl": net_pnl,
			"win_rate": _ratio_percent(row["win_count"], row["closed_trades_count"]),
			"average_hold_duration": _average_duration(row["hold_seconds"]),
			"eligible_filled_sell_count": row["eligible_filled_sell_count"],
			"churn_count": row["churn_count"],
			"churn_frequency": row["churn_frequency"],
			"total_normalized_fees": row["total_normalized_fees"],
			"fee_efficiency": _safe_fee_ratio(row["total_normalized_fees"], _positive_only(row["gross_realized_pnl"])),
		})
	strategy_summary.sort(key=lambda row: row["strategy_version"])

	net_realized_pnl = gross_realized_pnl - total_fees
	fee_by_symbol = []
	for row in fee_rows_by_symbol.values():
		net = row["gross_realized_pnl"] - row["total_normalized_fees"]
		fee_by_symbol.append({
			**row,
			"net_realized_pnl": net,
			"fees_over_gross_profit": _safe_fee_ratio(row["total_normalized_fees"], row["gross_profit"]),
			"fees_over_absolute_net_pnl": _safe_fee_ratio(row["total_normalized_fees"], abs(net)),
		})
	fee_by_symbol.sort(key=lambda row: row["symbol"])

	return {
		"strategy_summary": strategy_summary,
		"hold_time": _build_hold_time_summary(hold_seconds),
		"churn": churn,
		"fee_efficiency": {
			"total_normalized_fees": total_fees,
			"gross_profit": gross_profit,
			"net_realized_pnl": net_realized_pnl,
			"fees_over_gross_profit": _safe_fee_ratio(total_fees, gross_profit),
			"fees_over_absolute_net_pnl": _safe_fee_ratio(total_fees, abs(net_realized_pnl)),
			"average_fee_per_closed_trade": (
				total_fees / Decimal(len(closures_by_sell))
				if closures_by_sell else None
			),
			"by_symbol": fee_by_symbol,
		},
	}


def _calculate_churn(operations, churn_threshold_minutes):
	rows_by_symbol = {}
	for operation in operations:
		if operation.get("manual_correction") or operation.get("timestamp") is None:
			continue
		rows_by_symbol.setdefault(operation["symbol"], []).append(operation)

	eligible_sells = 0
	reentries = 0
	stop_loss_reentries = 0
	by_version = {}
	threshold_seconds = churn_threshold_minutes * 60
	for symbol_rows in rows_by_symbol.values():
		symbol_rows.sort(key=lambda row: (row["timestamp"], row["id"]))
		for index, row in enumerate(symbol_rows):
			if row["side"] != "SELL":
				continue
			eligible_sells += 1
			next_buy = next((candidate for candidate in symbol_rows[index + 1:] if candidate["side"] == "BUY"), None)
			if not next_buy:
				continue
			gap_seconds = (next_buy["timestamp"] - row["timestamp"]).total_seconds()
			if gap_seconds < 0 or gap_seconds > threshold_seconds:
				continue
			reentries += 1
			if row.get("sell_reason") == "stop_loss_reached":
				stop_loss_reentries += 1
			version_row = by_version.setdefault(row["strategy_version"], {
				"strategy_version": row["strategy_version"],
				"eligible_filled_sell_count": 0,
				"same_symbol_reentry_count": 0,
				"stop_loss_reentry_churn_count": 0,
			})
			version_row["same_symbol_reentry_count"] += 1
			version_row["stop_loss_reentry_churn_count"] += int(row.get("sell_reason") == "stop_loss_reached")
		for row in symbol_rows:
			if row["side"] == "SELL":
				version_row = by_version.setdefault(row["strategy_version"], {
					"strategy_version": row["strategy_version"],
					"eligible_filled_sell_count": 0,
					"same_symbol_reentry_count": 0,
					"stop_loss_reentry_churn_count": 0,
				})
				version_row["eligible_filled_sell_count"] += 1
	for row in by_version.values():
		row["same_symbol_reentry_frequency"] = _ratio_percent(
			row["same_symbol_reentry_count"], row["eligible_filled_sell_count"]
		)
	return {
		"eligible_filled_sell_count": eligible_sells,
		"same_symbol_reentry_count": reentries,
		"same_symbol_reentry_frequency": _ratio_percent(reentries, eligible_sells),
		"stop_loss_reentry_churn_count": stop_loss_reentries,
		"by_strategy_version": sorted(by_version.values(), key=lambda row: row["strategy_version"]),
	}


def _build_hold_time_summary(seconds):
	seconds = sorted(seconds)
	buckets = {label: 0 for label in HOLD_BUCKET_LABELS}
	for value in seconds:
		if value < 15 * 60:
			buckets["<15m"] += 1
		elif value < 60 * 60:
			buckets["15m-1h"] += 1
		elif value < 4 * 60 * 60:
			buckets["1h-4h"] += 1
		elif value < 24 * 60 * 60:
			buckets["4h-24h"] += 1
		else:
			buckets[">24h"] += 1
	return {
		"average_hold_duration": _average_duration(seconds),
		"median_hold_duration": timedelta(seconds=median(seconds)) if seconds else None,
		"shortest_hold_duration": timedelta(seconds=seconds[0]) if seconds else None,
		"longest_hold_duration": timedelta(seconds=seconds[-1]) if seconds else None,
		"closed_under_15m_count": buckets["<15m"],
		"buckets": buckets,
	}


def _empty_context(filters):
	return {
		"filters": filters,
		"strategy_summary": [],
		"hold_time": _build_hold_time_summary([]),
		"churn": _calculate_churn([], filters.churn_threshold_minutes),
		"fee_efficiency": {
			"total_normalized_fees": Decimal("0"),
			"gross_profit": Decimal("0"),
			"net_realized_pnl": Decimal("0"),
			"fees_over_gross_profit": None,
			"fees_over_absolute_net_pnl": None,
			"average_fee_per_closed_trade": None,
			"by_symbol": [],
		},
		"data_error": None,
	}


def _parse_filters(params):
	params = params or {}
	return OperationalKpiFilters(
		date_from=_parse_date(params.get("date_from")),
		date_to=_parse_date(params.get("date_to")),
		strategy_version=(params.get("strategy_version") or "").strip(),
		symbol=(params.get("symbol") or "").strip().upper(),
		churn_threshold_minutes=_parse_positive_int(
			params.get("churn_threshold_minutes"),
			DEFAULT_CHURN_THRESHOLD_MINUTES,
		),
	)


def _parse_date(value):
	if not value:
		return None
	try:
		return datetime.strptime(value, "%Y-%m-%d").date()
	except (TypeError, ValueError):
		return None


def _parse_positive_int(value, default):
	try:
		parsed = int(value)
	except (TypeError, ValueError):
		return default
	return parsed if parsed > 0 else default


def _strategy_version(payload):
	value = (payload or {}).get("strategy_version")
	return str(value) if value not in (None, "") else UNVERSIONED


def _is_manual_correction(payload):
	payload = payload or {}
	return payload.get("source") == "MANUAL_CORRECTION" or payload.get("accounting_only") is True


def _to_decimal(value):
	if value is None:
		return None
	try:
		return Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return None


def _ratio_percent(numerator, denominator):
	if not denominator:
		return None
	return Decimal(numerator) * Decimal("100") / Decimal(denominator)


def _safe_fee_ratio(fees, denominator):
	if denominator is None or denominator <= 0:
		return None
	return fees * Decimal("100") / denominator


def _positive_only(value):
	return value if value > 0 else Decimal("0")


def _average_duration(seconds):
	return timedelta(seconds=sum(seconds) / len(seconds)) if seconds else None
