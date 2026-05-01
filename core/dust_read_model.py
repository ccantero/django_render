from dataclasses import dataclass
from decimal import Decimal
from typing import List

from django.db import DatabaseError, ProgrammingError
from django.db.models import Case, Count, IntegerField, Sum, Value, When

from core.trading_models import DustDetection


REQUIRED_DETAIL_FIELDS = (
	"detected_at",
	"symbol",
	"event_type",
	"severity",
	"estimated_value_usdt",
	"quantity_delta",
	"reason",
	"run_id",
)
OPTIONAL_DETAIL_FIELDS = (
	"estimated_delta_value_usdt",
	"suggested_action",
)


@dataclass
class DustReadModel:
	context: dict
	queries: List[str]
	assumptions: List[str]


def get_dust_dashboard_context(filters=None):
	filters = filters or {}
	context = {
		"data_error": None,
		"detections": [],
		"filters": _clean_filters(filters),
		"filter_options": {
			"symbols": [],
			"severities": [],
			"event_types": [],
		},
		"summary": _empty_summary(),
	}

	try:
		context["filter_options"] = _build_filter_options()
		queryset = _filtered_detections(context["filters"])
		context["summary"] = _build_summary(queryset)
		context["detections"], context["optional_columns"] = _list_detections(
			queryset,
			limit=200,
			include_optional=True,
		)
	except DatabaseError as exc:
		context["data_error"] = str(exc)

	return DustReadModel(
		context=context,
		queries=_important_queries(),
		assumptions=_assumptions(),
	)


def get_dust_overview_context():
	context = {
		"critical_count": 0,
		"warning_count": 0,
		"latest_run_id": None,
		"latest_detection": None,
		"top_detections": [],
		"data_error": None,
	}

	try:
		queryset = _apply_default_ordering(DustDetection.objects.all())
		context.update(_build_summary(queryset))
		context["latest_detection"] = _latest_detection()
		context["top_detections"], _ = _list_detections(
			queryset,
			limit=5,
			include_optional=False,
		)
	except DatabaseError as exc:
		context["data_error"] = str(exc)

	return context


def _clean_filters(filters):
	return {
		"symbol": (filters.get("symbol") or "").strip(),
		"severity": (filters.get("severity") or "").strip(),
		"event_type": (filters.get("event_type") or "").strip(),
	}


def _filtered_detections(filters):
	queryset = DustDetection.objects.all()
	if filters["symbol"]:
		queryset = queryset.filter(symbol=filters["symbol"])
	if filters["severity"]:
		queryset = queryset.filter(severity=filters["severity"])
	if filters["event_type"]:
		queryset = queryset.filter(event_type=filters["event_type"])

	return _apply_default_ordering(queryset)


def _apply_default_ordering(queryset):
	severity_rank = Case(
		When(severity="critical", then=Value(2)),
		When(severity="warning", then=Value(1)),
		default=Value(0),
		output_field=IntegerField(),
	)
	return queryset.alias(severity_rank=severity_rank).order_by(
		"-severity_rank",
		"-estimated_value_usdt",
		"-detected_at",
	)


def _latest_detection():
	return (
		DustDetection.objects
		.only("detected_at", "symbol", "reason", "severity")
		.order_by("-detected_at", "-id")
		.first()
	)


def _list_detections(queryset, limit, include_optional):
	fields = REQUIRED_DETAIL_FIELDS
	optional_columns = {
		"estimated_delta_value_usdt": False,
		"suggested_action": False,
	}
	if include_optional:
		fields = REQUIRED_DETAIL_FIELDS + OPTIONAL_DETAIL_FIELDS
		optional_columns = {
			"estimated_delta_value_usdt": True,
			"suggested_action": True,
		}

	try:
		return list(queryset.only(*fields)[:limit]), optional_columns
	except (DatabaseError, ProgrammingError):
		if not include_optional:
			raise
		return list(queryset.only(*REQUIRED_DETAIL_FIELDS)[:limit]), {
			"estimated_delta_value_usdt": False,
			"suggested_action": False,
		}


def _build_summary(queryset=None):
	if queryset is None:
		queryset = DustDetection.objects.all()
	severity_rows = (
		queryset.order_by()
		.filter(severity__in=["critical", "warning"])
		.values("severity")
		.annotate(total=Count("id"))
	)
	counts = {"critical": 0, "warning": 0}
	for row in severity_rows:
		counts[row["severity"]] = row["total"]

	latest = queryset.only("run_id", "detected_at").order_by("-detected_at", "-id").first()

	return {
		"critical_count": counts["critical"],
		"warning_count": counts["warning"],
		"total_estimated_value_usdt": (
			queryset.aggregate(
				total=Sum("estimated_value_usdt"),
			)["total"]
			or Decimal("0")
		),
		"latest_run_id": latest.run_id if latest else None,
	}


def _empty_summary():
	return {
		"critical_count": 0,
		"warning_count": 0,
		"total_estimated_value_usdt": Decimal("0"),
		"latest_run_id": None,
	}


def _build_filter_options():
	return {
		"symbols": _distinct_values("symbol"),
		"severities": _distinct_values("severity"),
		"event_types": _distinct_values("event_type"),
	}


def _distinct_values(field_name):
	return list(
		DustDetection.objects
		.exclude(**{f"{field_name}__isnull": True})
		.exclude(**{field_name: ""})
		.order_by(field_name)
		.values_list(field_name, flat=True)
		.distinct()
	)


def _important_queries():
	return [
		"bot.dust_detections: latest rows ordered by severity, estimated_value_usdt, detected_at",
		"bot.dust_detections: COUNT(*) grouped by severity for critical and warning",
		"bot.dust_detections: SUM(estimated_value_usdt) as an approximate nullable-safe total",
		"bot.dust_detections: latest run_id ordered by detected_at desc",
	]


def _assumptions():
	return [
		"Dashboard reads bot.dust_detections only; it never mutates bot-owned tables.",
		"estimated_value_usdt is approximate and is not interpreted as PnL.",
		"severity ordering treats critical as higher priority than warning for display.",
	]
