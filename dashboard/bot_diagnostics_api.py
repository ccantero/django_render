"""Small, read-only HTTP diagnostics for persisted bot evidence."""

import hmac
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Count, Max, Min, Sum
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.trading_models import BotHealthcheck, DustDetection, Portfolio, PositionLot


DIAGNOSTICS_AUTH_SCOPE = "bot-diagnostics-read-only"
MAX_TOKEN_LENGTH = 512
DEFAULT_STALE_MINUTES = 15


class DiagnosticsPrincipal:
	"""Non-user principal used only by the two diagnostics API views."""

	is_authenticated = True
	is_anonymous = False
	is_active = True
	is_staff = False

	def __str__(self):
		return "bot-diagnostics-client"


class DiagnosticsBearerAuthentication(BaseAuthentication):
	"""Authenticate against a dedicated, endpoint-scoped deployment secret."""

	def authenticate(self, request):
		authorization = request.META.get("HTTP_AUTHORIZATION", "")
		if not authorization:
			return None

		parts = authorization.split()
		if len(parts) != 2 or parts[0].lower() != "bearer":
			raise AuthenticationFailed("Invalid diagnostics credentials.")

		provided = parts[1]
		if len(provided) > MAX_TOKEN_LENGTH:
			raise AuthenticationFailed("Invalid diagnostics credentials.")

		expected = str(getattr(settings, "BOT_DIAGNOSTICS_API_TOKEN", "") or "").strip()
		if len(expected) < 32 or not hmac.compare_digest(provided, expected):
			raise AuthenticationFailed("Invalid diagnostics credentials.")

		return DiagnosticsPrincipal(), DIAGNOSTICS_AUTH_SCOPE

	def authenticate_header(self, request):
		return "Bearer"


class ReadOnlyDiagnosticsAPIView(APIView):
	authentication_classes = (DiagnosticsBearerAuthentication,)
	permission_classes = (IsAuthenticated,)
	http_method_names = ("get", "head", "options")

	def finalize_response(self, request, response, *args, **kwargs):
		response = super().finalize_response(request, response, *args, **kwargs)
		response["Cache-Control"] = "no-store"
		response["Pragma"] = "no-cache"
		response["X-Content-Type-Options"] = "nosniff"
		return response


def _as_decimal(value):
	if value is None or isinstance(value, bool):
		return None
	try:
		parsed = value if isinstance(value, Decimal) else Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return None
	return parsed if parsed.is_finite() else None


def _decimal_text(value):
	parsed = _as_decimal(value)
	return format(parsed, "f") if parsed is not None else None


def _iso(value):
	return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _stale_minutes():
	try:
		minutes = int(getattr(settings, "HEALTHCHECK_STALE_MINUTES", DEFAULT_STALE_MINUTES))
		return max(0, minutes)
	except (TypeError, ValueError):
		return DEFAULT_STALE_MINUTES


def _freshness(timestamp, observed_at):
	if timestamp is None or not hasattr(timestamp, "tzinfo"):
		return "unknown"
	try:
		age = observed_at - timestamp
	except (TypeError, ValueError):
		return "unknown"
	if age < timedelta(0):
		return "unknown"
	return "stale" if age > timedelta(minutes=_stale_minutes()) else "fresh"


def _age_seconds(timestamp, observed_at):
	if _freshness(timestamp, observed_at) == "unknown":
		return None
	return max(0, int((observed_at - timestamp).total_seconds()))


def _latest_healthcheck():
	return BotHealthcheck.objects.order_by("-created_at", "-id").first()


def _health_payload(row, observed_at):
	created_at = getattr(row, "created_at", None) if row is not None else None
	status = getattr(row, "status", None) if row is not None else None
	freshness = _freshness(created_at, observed_at)
	return {
		"source": "bot.bot_healthcheck",
		"status": str(status).strip().lower()[:32] if status else "unavailable",
		"observed_at": _iso(observed_at),
		"healthcheck_at": _iso(created_at),
		"age_seconds": _age_seconds(created_at, observed_at),
		"freshness": freshness if row is not None else "unavailable",
	}


def _json_safe_integer(value):
	parsed = _as_decimal(value)
	if parsed is None or parsed != parsed.to_integral_value():
		return None
	try:
		return int(parsed)
	except (OverflowError, ValueError):
		return None


def _capacity_payload(health_row, symbol, observed_at):
	if health_row is None:
		return {
			"source": "bot.bot_healthcheck.details",
			"freshness": "unavailable",
			"capacity_status": "unavailable",
			"symbol_classification": "unavailable",
			"global": None,
			"historical_global": None,
		}

	created_at = getattr(health_row, "created_at", None)
	freshness = _freshness(created_at, observed_at)
	details = getattr(health_row, "details", None)
	details = details if isinstance(details, dict) else {}
	classification = details.get("position_classification")
	source = classification if isinstance(classification, dict) else details
	classification_available = any(
		key in source for key in ("material_symbols", "dust_symbols", "unknown_value_symbols")
	)
	symbol_class = "unavailable"
	if classification_available:
		if symbol in (source.get("material_symbols") if isinstance(source.get("material_symbols"), list) else []):
			symbol_class = "material"
		elif symbol in (source.get("dust_symbols") if isinstance(source.get("dust_symbols"), list) else []):
			symbol_class = "dust"
		elif symbol in (source.get("unknown_value_symbols") if isinstance(source.get("unknown_value_symbols"), list) else []):
			symbol_class = "unknown_value"
		else:
			symbol_class = "not_listed"

	global_values = {
		key: _json_safe_integer(details.get(key, source.get(key)))
		for key in (
			"positions_count",
			"material_positions_count",
			"dust_positions_count",
			"unknown_value_positions_count",
			"effective_positions_count",
		)
	}
	global_values["max_positions"] = _json_safe_integer(
		details.get("max_positions", details.get("max_open_positions"))
	)
	global_values["remaining_buy_capacity"] = _json_safe_integer(
		details.get("remaining_buy_capacity", source.get("remaining_buy_capacity"))
	)
	if not any(value is not None for value in global_values.values()):
		global_values = None
	global_status = (
		"unavailable" if global_values is None
		else "partial" if any(value is None for value in global_values.values())
		else "available"
	)
	capacity_status = "unavailable"
	if freshness == "stale":
		capacity_status = "historical"
	elif freshness == "fresh" and global_status == "partial":
		capacity_status = "partial_as_of_healthcheck"
	elif freshness == "fresh" and global_status == "available":
		capacity_status = "current_as_of_healthcheck"

	return {
		"source": "bot.bot_healthcheck.details",
		"healthcheck_at": _iso(created_at),
		"freshness": freshness,
		"capacity_status": capacity_status,
		"symbol_classification": symbol_class if freshness == "fresh" else "unavailable",
		"global_status": global_status if freshness == "fresh" else "unavailable",
		"global": global_values if freshness == "fresh" else None,
		"historical_global": global_values if freshness == "stale" else None,
	}


def _database_unavailable(observed_at):
	return JsonResponse(
		{
			"error": {
				"code": "evidence_unavailable",
				"message": "Persisted bot evidence is temporarily unavailable.",
			},
			"observed_at": _iso(observed_at),
		},
		status=503,
	)


class BotHealthAPIView(ReadOnlyDiagnosticsAPIView):
	"""Expose a bounded, sanitized view of the latest persisted healthcheck."""

	def get(self, request):
		observed_at = timezone.now()
		try:
			row = _latest_healthcheck()
		except DatabaseError:
			return _database_unavailable(observed_at)
		return JsonResponse({"healthcheck": _health_payload(row, observed_at)})


class ETHInventoryAPIView(ReadOnlyDiagnosticsAPIView):
	"""Expose persisted ETHUSDT projection and open-lot evidence only."""

	symbol = "ETHUSDT"

	def get(self, request):
		observed_at = timezone.now()
		try:
			health_row = _latest_healthcheck()
			spot_observation = (
				DustDetection.objects.filter(symbol=self.symbol, detected_at__isnull=False)
				.only(
					"spot_quantity",
					"open_lot_quantity",
					"price_usdt",
					"estimated_value_usdt",
					"event_type",
					"reason",
					"source",
					"detected_at",
				)
				.order_by("-detected_at", "-id")
				.first()
			)
			portfolio = (
				Portfolio.objects.filter(symbol=self.symbol)
				.only("symbol", "quantity", "entry_price", "current_price", "updated_at")
				.first()
			)
			lots = PositionLot.objects.filter(
				symbol=self.symbol,
				remaining_quantity__gt=0,
			).aggregate(
				open_quantity=Sum("remaining_quantity"),
				open_lot_count=Count("lot_id"),
				first_opened_at=Min("opened_at"),
				last_opened_at=Max("opened_at"),
			)
		except DatabaseError:
			return _database_unavailable(observed_at)
		spot_observation_at = getattr(spot_observation, "detected_at", None) if spot_observation else None
		spot_observation_recency = "unavailable"
		if spot_observation:
			spot_observation_recency = _freshness(spot_observation_at, observed_at)
			if spot_observation_recency == "fresh":
				spot_observation_recency = "recent"
		spot_quantity = _as_decimal(getattr(spot_observation, "spot_quantity", None)) if spot_observation else None

		open_quantity = _as_decimal(lots.get("open_quantity"))
		lot_count = _json_safe_integer(lots.get("open_lot_count")) or 0
		portfolio_quantity = _as_decimal(getattr(portfolio, "quantity", None)) if portfolio else None
		entry_price = _as_decimal(getattr(portfolio, "entry_price", None)) if portfolio else None
		current_price = _as_decimal(getattr(portfolio, "current_price", None)) if portfolio else None
		portfolio_updated_at = getattr(portfolio, "updated_at", None) if portfolio else None
		portfolio_freshness = _freshness(portfolio_updated_at, observed_at) if portfolio else "unavailable"
		valuation_status = "unavailable"
		estimated_value = None
		if portfolio_quantity is None or current_price is None or current_price <= 0 or portfolio_quantity < 0:
			valuation_status = "unavailable"
		else:
			estimated_value = portfolio_quantity * current_price
			valuation_status = {
				"fresh": "available",
				"stale": "stale",
				"unknown": "freshness_unknown",
				"unavailable": "freshness_unknown",
			}.get(portfolio_freshness, "freshness_unknown")

		difference = None
		if portfolio_quantity is not None and open_quantity is not None:
			difference = portfolio_quantity - open_quantity

		if portfolio is None and lot_count == 0 and spot_observation is None:
			return JsonResponse(
				{
					"error": {"code": "symbol_not_found", "message": "No persisted ETHUSDT position evidence was found."},
					"symbol": self.symbol,
					"observed_at": _iso(observed_at),
				},
				status=404,
			)

		return JsonResponse({
			"symbol": self.symbol,
			"observed_at": _iso(observed_at),
			"portfolio": {
				"source": "bot.portfolio",
				"quantity": _decimal_text(portfolio_quantity),
				"entry_price": _decimal_text(entry_price),
				"current_price": _decimal_text(current_price),
				"estimated_value_usdt": _decimal_text(estimated_value),
				"valuation_status": valuation_status,
				"updated_at": _iso(portfolio_updated_at),
				"freshness": portfolio_freshness,
			},
			"open_lots": {
				"source": "bot.position_lots",
				"quantity": _decimal_text(open_quantity),
				"count": lot_count,
				"first_opened_at": _iso(lots.get("first_opened_at")),
				"last_opened_at": _iso(lots.get("last_opened_at")),
				"freshness": "unknown",
				"freshness_reason": "Open lot rows have no update timestamp in the Django read model.",
			},
			"latest_spot_observation": {
				"source": "bot.dust_detections",
				"observed_spot_quantity": _decimal_text(spot_quantity),
				"quantity_status": "available" if spot_quantity is not None else "unavailable",
				"open_lot_quantity": _decimal_text(getattr(spot_observation, "open_lot_quantity", None)) if spot_observation else None,
				"price_usdt": _decimal_text(getattr(spot_observation, "price_usdt", None)) if spot_observation else None,
				"estimated_value_usdt": _decimal_text(getattr(spot_observation, "estimated_value_usdt", None)) if spot_observation else None,
				"event_type": str(getattr(spot_observation, "event_type", "") or "")[:64] if spot_observation else None,
				"reason": str(getattr(spot_observation, "reason", "") or "")[:256] if spot_observation else None,
				"source_label": str(getattr(spot_observation, "source", "") or "")[:64] if spot_observation else None,
				"detected_at": _iso(spot_observation_at),
				"observation_recency": spot_observation_recency,
				"current_exchange_truth": False,
			},
			"quantity_difference": {
				"portfolio_minus_open_lots": _decimal_text(difference),
				"status": "available" if difference is not None else "unavailable",
				"comparability": "not_synchronized",
			},
			"consistency": {
				"atomic": False,
				"mode": "separate_queries",
				"cross_source_comparisons": "not_synchronized",
			},
			"buy_capacity": _capacity_payload(health_row, self.symbol, observed_at),
			"active_generation": {
				"available": False,
				"status": "unavailable",
				"reason": "No position generation read model is mapped in this Django application.",
			},
			"exchange_spot": {
				"available": False,
				"status": "unavailable",
				"quantity": None,
				"estimated_value_usdt": None,
				"reason": "Django does not call Binance; persisted database evidence is not current exchange truth.",
			},
		})
