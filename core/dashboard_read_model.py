from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import DatabaseError
from django.db.models import Count, Sum
from django.utils import timezone

from core.models import (
	AppSetting,
	BotControl,
)
from core.trading_models import (
	Healthcheck,
	LotClosure,
	PortfolioPosition,
	PositionLot,
	TradeOperation,
)


FALLBACK_THRESHOLDS = {
	"drift_qty_tolerance": Decimal("0.00000001"),
	"dust_min_notional_usdt": Decimal("5"),
	"healthcheck_stale_minutes": 15,
}
SETTING_KEYS = {
	"drift_qty_tolerance": "DRIFT_QTY_TOLERANCE",
	"dust_min_notional_usdt": "DUST_MIN_NOTIONAL_USDT",
	"healthcheck_stale_minutes": "HEALTHCHECK_STALE_MINUTES",
}
FILLED_STATUSES = {"FILLED", "SUCCESS"}
ERROR_STATUSES = {"ERROR", "FAILED", "FAILURE"}


@dataclass
class DashboardReadModel:
	context: dict
	queries: list[str]
	assumptions: list[str]


def get_dashboard_context():
	thresholds = _read_external_thresholds()
	context = {
		"bot_control": _get_bot_control(),
		"health": _empty_health(),
		"summary": _empty_summary(),
		"positions": [],
		"trades": [],
		"alerts": [],
		"thresholds": thresholds,
		"data_error": None,
	}

	try:
		portfolio_rows = list(PortfolioPosition.objects.all().order_by("symbol"))
		open_lots = _open_lots_by_symbol()
		positions, drift_alerts, dust_alerts, total_value = _build_positions(portfolio_rows, open_lots, thresholds)
		trades = list(TradeOperation.objects.all().order_by("-executed_at", "-created_at", "-id")[:20])
		health = _build_health(thresholds)
		invariant_alerts = _build_invariant_alerts(thresholds)
		rejected_alerts = _build_rejected_operation_alerts()

		alerts = _threshold_alerts(thresholds)
		alerts.extend(_health_alerts(health))
		alerts.extend(drift_alerts)
		alerts.extend(dust_alerts)
		alerts.extend(invariant_alerts)
		alerts.extend(rejected_alerts)

		context.update({
			"health": health,
			"summary": {
				"portfolio_positions_count": sum(1 for row in portfolio_rows if _positive(row.quantity)),
				"open_lot_symbols_count": len(open_lots),
				"total_value": total_value,
				"drift_alerts_count": len(drift_alerts),
				"dust_alerts_count": len(dust_alerts),
			},
			"positions": positions,
			"trades": trades,
			"alerts": alerts,
		})
	except DatabaseError as exc:
		context["data_error"] = str(exc)
		context["alerts"].append({
			"level": "warning",
			"title": "Tablas compartidas no disponibles",
			"detail": "El dashboard no pudo leer las tablas del bot. Verificar conexión, schema y columnas del contrato.",
		})

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


def _open_lots_by_symbol():
	rows = (
		PositionLot.objects
		.filter(remaining_quantity__gt=0)
		.values("symbol", "asset")
		.annotate(open_quantity=Sum("remaining_quantity"), open_lot_count=Count("id"))
		.order_by("symbol")
	)
	return {row["symbol"]: row for row in rows}


def _build_positions(portfolio_rows, open_lots, thresholds):
	portfolio_by_symbol = {row.symbol: row for row in portfolio_rows}
	all_symbols = sorted(set(portfolio_by_symbol) | set(open_lots))
	positions = []
	drift_alerts = []
	dust_alerts = []
	total_value = Decimal("0")
	drift_tolerance = thresholds["drift_qty_tolerance"]["value"]
	dust_min_notional = thresholds["dust_min_notional_usdt"]["value"]

	for symbol in all_symbols:
		portfolio = portfolio_by_symbol.get(symbol)
		lot = open_lots.get(symbol)
		portfolio_quantity = portfolio.quantity if portfolio else Decimal("0")
		lot_quantity = lot["open_quantity"] if lot else Decimal("0")
		quantity_diff = portfolio_quantity - lot_quantity
		current_price = portfolio.current_price if portfolio else None
		position_value = None
		unrealized_pnl = None

		if current_price is not None and portfolio:
			position_value = portfolio_quantity * current_price
			total_value += position_value

		if portfolio and portfolio.entry_price is not None and current_price is not None:
			unrealized_pnl = (current_price - portfolio.entry_price) * portfolio_quantity

		has_drift = drift_tolerance is not None and abs(quantity_diff) > drift_tolerance
		if has_drift:
			drift_alerts.append({
				"level": "danger",
				"title": f"Drift en {symbol}",
				"detail": "La cantidad de portfolio difiere de la suma de lots abiertos.",
			})

		if current_price is not None and dust_min_notional is not None:
			lot_value = lot_quantity * current_price
			if Decimal("0") < lot_value < dust_min_notional:
				dust_alerts.append({
					"level": "warning",
					"title": f"Dust candidato en {symbol}",
					"detail": f"Valor estimado menor a {dust_min_notional} USDT.",
				})

		positions.append({
			"symbol": symbol,
			"asset": portfolio.asset if portfolio else lot.get("asset"),
			"portfolio_quantity": portfolio_quantity,
			"lot_quantity": lot_quantity,
			"quantity_diff": quantity_diff,
			"has_drift": has_drift,
			"entry_price": portfolio.entry_price if portfolio else None,
			"current_price": current_price,
			"position_value": position_value,
			"unrealized_pnl": unrealized_pnl,
			"open_lot_count": lot["open_lot_count"] if lot else 0,
			"updated_at": portfolio.updated_at if portfolio else None,
		})

	return positions, drift_alerts, dust_alerts, total_value


def _build_health(thresholds):
	latest = Healthcheck.objects.order_by("-updated_at", "-id").first()
	if latest is None:
		return _empty_health()

	now = timezone.now()
	age = now - latest.updated_at if latest.updated_at else None
	status = (latest.status or "").upper()
	stale_minutes = thresholds["healthcheck_stale_minutes"]["value"]
	is_stale = (
		stale_minutes is not None
		and age is not None
		and age > timedelta(minutes=stale_minutes)
	)
	state = "unknown"

	if status in ERROR_STATUSES or latest.last_error:
		state = "error"
	elif is_stale:
		state = "stale"
	elif status in {"OK", "HEALTHY", "SUCCESS", "RUNNING"}:
		state = "healthy"

	return {
		"row": latest,
		"state": state,
		"age": age,
		"is_stale": is_stale,
		"stale_minutes": stale_minutes,
	}


def _empty_health():
	return {
		"row": None,
		"state": "unknown",
		"age": None,
		"is_stale": False,
		"stale_minutes": None,
	}


def _health_alerts(health):
	row = health["row"]
	if row is None:
		return [{
			"level": "warning",
			"title": "Sin healthcheck",
			"detail": "No hay heartbeat disponible para inferir salud operativa.",
		}]
	if health["state"] == "error":
		return [{
			"level": "danger",
			"title": "Healthcheck con error",
			"detail": row.last_error or "El último estado reportado indica error.",
		}]
	if health["is_stale"]:
		return [{
			"level": "warning",
			"title": "Healthcheck viejo",
			"detail": f"El último heartbeat supera {health['stale_minutes']} minutos.",
		}]
	return []


def _build_invariant_alerts(thresholds):
	alerts = []
	drift_tolerance = thresholds["drift_qty_tolerance"]["value"]
	negative_lots_count = PositionLot.objects.filter(remaining_quantity__lt=0).count()
	if negative_lots_count:
		alerts.append({
			"level": "danger",
			"title": "Lots con cantidad negativa",
			"detail": f"{negative_lots_count} lot(s) tienen remaining_quantity menor a cero.",
		})

	closure_qty_by_operation = {
		row["trade_operation_id"]: row["closed_quantity"]
		for row in LotClosure.objects
		.values("trade_operation_id")
		.annotate(closed_quantity=Sum("closed_quantity"))
	}
	filled_sells = TradeOperation.objects.filter(side="SELL", status__in=FILLED_STATUSES)
	for op in filled_sells.only("id", "symbol", "executed_base_qty")[:50]:
		if drift_tolerance is None:
			continue
		executed_qty = op.executed_base_qty or Decimal("0")
		closed_qty = closure_qty_by_operation.get(op.id, Decimal("0")) or Decimal("0")
		if abs(executed_qty - closed_qty) > drift_tolerance:
			alerts.append({
				"level": "danger",
				"title": f"SELL sin cierre completo en {op.symbol}",
				"detail": f"Operación {op.id}: ejecutado {executed_qty}, cerrado por lots {closed_qty}.",
			})

	opened_lots_by_operation = {
		row["opened_by_trade_operation_id"]: row["lot_count"]
		for row in PositionLot.objects
		.exclude(opened_by_trade_operation_id__isnull=True)
		.values("opened_by_trade_operation_id")
		.annotate(lot_count=Count("id"))
	}
	filled_buys = TradeOperation.objects.filter(side="BUY", status__in=FILLED_STATUSES)
	for op in filled_buys.only("id", "symbol")[:50]:
		if opened_lots_by_operation.get(op.id, 0) == 0:
			alerts.append({
				"level": "warning",
				"title": f"BUY sin lot abierto en {op.symbol}",
				"detail": f"Operación {op.id}: no se encontraron lots abiertos por esa operación.",
			})

	return alerts


def _build_rejected_operation_alerts():
	alerts = []
	recent = (
		TradeOperation.objects
		.exclude(status__in=FILLED_STATUSES)
		.order_by("-created_at", "-id")[:5]
	)
	for op in recent:
		alerts.append({
			"level": "warning",
			"title": f"Operación no completada: {op.symbol}",
			"detail": f"{op.side} #{op.id} estado {op.status or 'sin estado'}.",
		})
	return alerts


def _empty_summary():
	return {
		"portfolio_positions_count": 0,
		"open_lot_symbols_count": 0,
		"total_value": Decimal("0"),
		"drift_alerts_count": 0,
		"dust_alerts_count": 0,
	}


def _positive(value):
	return value is not None and value > Decimal("0")


def _read_external_thresholds():
	try:
		settings_by_key = {
			row.key: row.value
			for row in AppSetting.objects.filter(key__in=SETTING_KEYS.values())
		}
	except DatabaseError:
		settings_by_key = {}

	return {
		"drift_qty_tolerance": _read_decimal_setting(
			settings_by_key,
			SETTING_KEYS["drift_qty_tolerance"],
			FALLBACK_THRESHOLDS["drift_qty_tolerance"],
		),
		"dust_min_notional_usdt": _read_decimal_setting(
			settings_by_key,
			SETTING_KEYS["dust_min_notional_usdt"],
			FALLBACK_THRESHOLDS["dust_min_notional_usdt"],
		),
		"healthcheck_stale_minutes": _read_int_setting(
			settings_by_key,
			SETTING_KEYS["healthcheck_stale_minutes"],
			FALLBACK_THRESHOLDS["healthcheck_stale_minutes"],
		),
	}


def _read_decimal_setting(settings_by_key, key, fallback):
	value = settings_by_key.get(key)
	if value in (None, ""):
		return {"value": fallback, "source": "fallback", "key": key}
	try:
		return {"value": Decimal(value), "source": "app_settings", "key": key}
	except InvalidOperation:
		return {"value": fallback, "source": "fallback_invalid", "key": key}


def _read_int_setting(settings_by_key, key, fallback):
	value = settings_by_key.get(key)
	if value in (None, ""):
		return {"value": fallback, "source": "fallback", "key": key}
	try:
		return {"value": int(value), "source": "app_settings", "key": key}
	except ValueError:
		return {"value": fallback, "source": "fallback_invalid", "key": key}


def _threshold_alerts(thresholds):
	fallbacks = [
		config["key"]
		for config in thresholds.values()
		if config["source"] in {"fallback", "fallback_invalid"}
	]

	if not fallbacks:
		return []

	return [{
		"level": "warning",
		"title": "Configuración de alertas con fallback",
		"detail": "Se usan defaults seguros solo para visualización: " + ", ".join(fallbacks),
	}]


def _important_queries():
	return [
		"position_lots: SUM(remaining_quantity) WHERE remaining_quantity > 0 GROUP BY symbol",
		"portfolio: quantity/current_price para visualizacion y valuacion aproximada",
		"portfolio vs position_lots: diff absoluto mayor al DRIFT_QTY_TOLERANCE configurado externamente",
		"trade_operations: ultimas operaciones ordenadas por executed_at/created_at/id descendente",
		"healthcheck: ultimo registro por updated_at descendente",
		"lot_closures vs SELL filled: SUM(closed_quantity) por trade_operation_id usando tolerancia externa",
	]


def _assumptions():
	return [
		"Las tablas compartidas estan en el search_path de Django con los nombres del contrato, sin prefijo de schema.",
		"Las columnas usadas siguen los nombres conceptuales de DATA_CONTRACT.md.",
		"Los umbrales de drift, dust y stale healthcheck provienen de configuracion externa; si faltan, esas alertas no se inventan.",
		"portfolio se usa solo como proyeccion de lectura; position_lots valida cantidades reales.",
		"El valor total es aproximado y solo se calcula cuando portfolio.current_price existe.",
		"Drift y dust son alertas informativas; el dashboard no corrige ni ejecuta trading.",
	]
