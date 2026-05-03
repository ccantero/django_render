from dataclasses import dataclass
from decimal import Decimal
import json
from typing import List
from urllib.parse import urlencode

from django.db import DatabaseError, connection
from django.db.models import (
	Case,
	CharField,
	Count,
	DecimalField,
	IntegerField,
	Max,
	Q,
	Value,
	When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import DustSignalReview
from core.trading_models import DustDetection


GROUP_FIELDS = (
	"symbol",
	"asset",
	"severity",
	"event_type",
	"reason",
)
DEFAULT_GROUP_LIMIT = 50
GROUP_CANDIDATE_LIMIT = 200
TOP_RISK_LIMIT = 3
DETAIL_ROWS_LIMIT = 100
NULL_GROUP_VALUE = "__null__"
GROUP_KEY_FIELDS = (
	"symbol_key",
	"asset_key",
	"severity_key",
	"event_type_key",
	"reason_key",
)
GROUP_INTERNAL_FIELDS = GROUP_KEY_FIELDS + (
	"severity_priority",
	"latest_estimated_value_sort",
)


@dataclass
class DustReadModel:
	context: dict
	queries: List[str]
	assumptions: List[str]


def get_dust_dashboard_context(filters=None):
	filters = filters or {}
	clean_filters = _clean_filters(filters)
	context = {
		"data_error": None,
		"dust_error": None,
		"grouped_detections": [],
		"top_risk_signals": [],
		"active_filters": [],
		"filters": clean_filters,
		"filter_options": {
			"symbols": [],
			"severities": [],
			"event_types": [],
			"reasons": [],
			"review_statuses": [],
		},
		"summary": _empty_summary(),
	}

	try:
		queryset = _dashboard_queryset(context["filters"])
		context["filter_options"] = _build_filter_options(queryset)
		context["grouped_detections"] = _grouped_detections(queryset)
		context["grouped_detections"] = _with_review_state(context["grouped_detections"])
		context["grouped_detections"] = _filter_by_review_status(
			context["grouped_detections"],
			context["filters"]["review_status"],
		)
		context["summary"] = _build_summary(queryset, context["grouped_detections"])
		context["top_risk_signals"] = _top_risk_signals(context["grouped_detections"])
		context["active_filters"] = _active_filters(context["filters"])
	except DatabaseError as exc:
		context["dust_error"] = "Query too slow"
		context["data_error"] = f"Query too slow: {exc}"
		context["summary"] = _empty_summary()
		context["grouped_detections"] = []

	return DustReadModel(
		context=context,
		queries=_important_queries(),
		assumptions=_assumptions(),
	)


def get_dust_detail_context(filters=None):
	filters = _clean_group_filters(filters or {})
	context = {
		"data_error": None,
		"dust_error": None,
		"filters": filters,
		"group_identity": _group_identity(filters),
		"group_summary": None,
		"review": None,
		"review_status": DustSignalReview.STATUS_PENDING,
		"review_status_choices": DustSignalReview.STATUS_CHOICES,
		"raw_detections": [],
		"back_querystring": _group_querystring(filters),
	}

	try:
		queryset = _filtered_group_detections(filters)
		grouped_rows = _grouped_detections(queryset, limit=1)
		context["group_summary"] = grouped_rows[0] if grouped_rows else None
		context["review"] = _review_for_identity(filters)
		if context["review"]:
			context["review_status"] = context["review"].status
		context["raw_detections"] = _latest_raw_detections(queryset)
	except DatabaseError as exc:
		context["dust_error"] = "Query too slow"
		context["data_error"] = f"Query too slow: {exc}"

	return DustReadModel(
		context=context,
		queries=_detail_queries(),
		assumptions=_assumptions(),
	)


def get_dust_overview_context():
	context = {
		"critical_count": 0,
		"warning_count": 0,
		"info_count": 0,
		"latest_run_id": None,
		"latest_detected_at": None,
		"top_grouped_detections": [],
		"total_detections": 0,
		"total_estimated_value_usdt": Decimal("0"),
		"data_error": None,
	}

	try:
		queryset = _latest_run_queryset()
		context["top_grouped_detections"] = _grouped_detections(queryset)
		context["top_grouped_detections"] = _with_review_state(context["top_grouped_detections"])
		context.update(_build_summary(queryset, context["top_grouped_detections"]))
	except DatabaseError as exc:
		context["data_error"] = f"Query too slow: {exc}"

	return context


def _clean_filters(filters):
	return {
		"symbol": (filters.get("symbol") or "").strip(),
		"severity": (filters.get("severity") or "").strip(),
		"event_type": (filters.get("event_type") or "").strip(),
		"reason": (filters.get("reason") or "").strip(),
		"review_status": (filters.get("review_status") or "").strip(),
	}


def _clean_group_filters(filters):
	return {
		"symbol": _clean_group_value(filters.get("symbol")),
		"asset": _clean_group_value(filters.get("asset")),
		"reason": _clean_group_value(filters.get("reason")),
		"event_type": _clean_group_value(filters.get("event_type")),
		"severity": _clean_group_value(filters.get("severity")),
	}


def _clean_group_value(value):
	value = (value or "").strip()
	if value == NULL_GROUP_VALUE or value == "":
		return None
	return value


def _filtered_detections(filters):
	queryset = DustDetection.objects.all()
	if filters["symbol"]:
		queryset = queryset.filter(symbol=filters["symbol"])
	if filters["severity"]:
		queryset = queryset.filter(severity=filters["severity"])
	if filters["event_type"]:
		queryset = queryset.filter(event_type=filters["event_type"])
	if filters["reason"]:
		queryset = queryset.filter(reason=filters["reason"])

	return queryset


def _dashboard_queryset(filters):
	queryset = _filtered_detections(filters)
	if _has_filters(filters):
		return queryset

	latest_run = _latest_run_id()
	if latest_run:
		return queryset.filter(run_id=latest_run)
	return queryset.none()


def _latest_run_queryset():
	latest_run = _latest_run_id()
	if latest_run:
		return DustDetection.objects.filter(run_id=latest_run)
	return DustDetection.objects.none()


def _has_filters(filters):
	return any(filters.get(key) for key in ("symbol", "severity", "event_type", "reason"))


def _latest_run_id():
	return (
		DustDetection.objects
		.only("run_id")
		.order_by("-detected_at", "-id")
		.values_list("run_id", flat=True)
		.first()
	)


def _filtered_group_detections(filters):
	queryset = DustDetection.objects.all()
	for field_name in GROUP_FIELDS:
		value = filters.get(field_name)
		if value is None:
			queryset = queryset.filter(**{f"{field_name}__isnull": True})
		else:
			queryset = queryset.filter(**{field_name: value})
	return queryset


def update_dust_signal_review(filters, status, note, user):
	filters = _clean_group_filters(filters or {})
	review_identity = _review_identity(filters)
	if status not in dict(DustSignalReview.STATUS_CHOICES):
		status = DustSignalReview.STATUS_PENDING
	try:
		review, _ = DustSignalReview.objects.get_or_create(
			symbol=review_identity["symbol"],
			asset=review_identity["asset"],
			reason=review_identity["reason"],
			event_type=review_identity["event_type"],
			severity=review_identity["severity"],
			defaults={"status": DustSignalReview.STATUS_PENDING},
		)
	except DatabaseError:
		return None
	review.status = status
	review.note = note or ""
	review.reviewed_by = user
	review.reviewed_at = (
		timezone.now()
		if status != DustSignalReview.STATUS_PENDING
		else None
	)
	review.save(update_fields=["status", "note", "reviewed_by", "reviewed_at", "updated_at"])
	return review


def _severity_priority_expression():
	severity_rank = Case(
		When(severity="critical", then=Value(0)),
		When(severity="warning", then=Value(1)),
		When(severity="info", then=Value(2)),
		default=Value(3),
		output_field=IntegerField(),
	)
	return severity_rank


def _latest_detection_row(queryset):
	return (
		queryset
		.only("run_id", "detected_at", "estimated_value_usdt")
		.order_by("-detected_at", "-id")
		.first()
	)


def _grouped_detections(queryset, limit=DEFAULT_GROUP_LIMIT):
	grouped_rows = list(
		queryset
		.annotate(**_group_key_expressions())
		.values(*GROUP_FIELDS, *GROUP_KEY_FIELDS)
		.annotate(
			detections_count=Count("id"),
			latest_detected_at=Max("detected_at"),
			severity_priority=_severity_priority_expression(),
		)
		.order_by(
			"severity_priority",
			"-latest_detected_at",
			"symbol",
		)[:GROUP_CANDIDATE_LIMIT]
	)
	latest_rows = _latest_rows_for_groups(queryset, grouped_rows)
	rows = [_merge_group_with_latest(row, latest_rows) for row in grouped_rows]
	rows.sort(key=_group_sort_key)
	return [_clean_grouped_row(row) for row in rows[:limit]]


def _latest_rows_for_groups(queryset, grouped_rows):
	if not grouped_rows:
		return {}

	group_filter = Q()
	for row in grouped_rows:
		group_filter |= _group_filter_q(row)

	rows = (
		queryset
		.filter(group_filter)
		.only(
			"run_id",
			"symbol",
			"asset",
			"severity",
			"event_type",
			"reason",
			"detected_at",
			"estimated_value_usdt",
			"estimated_delta_value_usdt",
			"suggested_action",
		)
	)
	if connection.vendor == "postgresql":
		rows = rows.order_by(
			"symbol",
			"asset",
			"severity",
			"event_type",
			"reason",
			"-detected_at",
			"-id",
		).distinct(*GROUP_FIELDS)
	else:
		rows = rows.order_by("-detected_at", "-id")

	latest_rows = {}
	for row in rows:
		key = _group_key_from_obj(row)
		if key not in latest_rows:
			latest_rows[key] = row
	return latest_rows


def _group_filter_q(row):
	query = Q()
	for field_name in GROUP_FIELDS:
		value = row.get(field_name)
		if value is None:
			query &= Q(**{f"{field_name}__isnull": True})
		else:
			query &= Q(**{field_name: value})
	return query


def _group_key_from_row(row):
	return tuple(row.get(field_name) for field_name in GROUP_FIELDS)


def _group_key_from_obj(row):
	return tuple(getattr(row, field_name) for field_name in GROUP_FIELDS)


def _merge_group_with_latest(row, latest_rows):
	latest = latest_rows.get(_group_key_from_row(row))
	row["latest_run_id"] = latest.run_id if latest else None
	row["latest_estimated_value_usdt"] = latest.estimated_value_usdt if latest else None
	row["latest_estimated_delta_value_usdt"] = (
		latest.estimated_delta_value_usdt if latest else None
	)
	row["latest_suggested_action"] = latest.suggested_action if latest else None
	return row


def _group_sort_key(row):
	return (
		row.get("severity_priority", 3),
		-(row.get("latest_estimated_value_usdt") or Decimal("0")),
		-(row.get("latest_detected_at").timestamp() if row.get("latest_detected_at") else 0),
		row.get("symbol") or "",
	)


def _top_risk_signals(grouped_rows, limit=TOP_RISK_LIMIT):
	return sorted(
		grouped_rows,
		key=lambda row: (
			row.get("latest_estimated_value_usdt") or Decimal("0"),
			str(row.get("latest_detected_at") or ""),
		),
		reverse=True,
	)[:limit]


def _active_filters(filters):
	labels = {
		"symbol": "Symbol",
		"severity": "Severity",
		"event_type": "Event type",
		"reason": "Reason",
		"review_status": "Review",
	}
	return [
		{"label": labels[key], "value": value}
		for key, value in filters.items()
		if value
	]


def _group_key_expressions():
	output_field = CharField()
	return {
		"symbol_key": Coalesce("symbol", Value(""), output_field=output_field),
		"asset_key": Coalesce("asset", Value(""), output_field=output_field),
		"severity_key": Coalesce("severity", Value(""), output_field=output_field),
		"event_type_key": Coalesce("event_type", Value(""), output_field=output_field),
		"reason_key": Coalesce("reason", Value(""), output_field=output_field),
	}


def _clean_grouped_row(row):
	for key in GROUP_INTERNAL_FIELDS:
		row.pop(key, None)
	row["detail_querystring"] = _group_querystring(row)
	return row


def _with_review_state(rows):
	reviews = _reviews_for_rows(rows)
	for row in rows:
		review = reviews.get(_review_key_from_row(row))
		row["review_status"] = review.status if review else DustSignalReview.STATUS_PENDING
		row["review_note"] = review.note if review else ""
		row["reviewed_by"] = review.reviewed_by if review else None
		row["reviewed_at"] = review.reviewed_at if review else None
	return rows


def _reviews_for_rows(rows):
	if not rows:
		return {}
	review_filter = Q()
	for row in rows:
		review_filter |= _review_filter_q(row)
	try:
		reviews = list(
			DustSignalReview.objects
			.filter(review_filter)
			.select_related("reviewed_by")
		)
	except DatabaseError:
		return {}
	return {
		_review_key_from_obj(review): review
		for review in reviews
	}


def _filter_by_review_status(rows, status):
	if not status:
		return rows
	return [
		row for row in rows
		if row.get("review_status", DustSignalReview.STATUS_PENDING) == status
	]


def _review_for_identity(filters):
	try:
		return (
			DustSignalReview.objects
			.filter(_review_filter_q(filters))
			.select_related("reviewed_by")
			.first()
		)
	except DatabaseError:
		return None


def _review_identity(values):
	return {
		field_name: _review_identity_value(values.get(field_name))
		for field_name in GROUP_FIELDS
	}


def _review_identity_value(value):
	if value is None:
		return ""
	return value


def _review_filter_q(values):
	return Q(**_review_identity(values))


def _review_key_from_row(row):
	return tuple(_review_identity_value(row.get(field_name)) for field_name in GROUP_FIELDS)


def _review_key_from_obj(row):
	return tuple(
		_review_identity_value(getattr(row, field_name))
		for field_name in GROUP_FIELDS
	)


def _group_querystring(values):
	return urlencode({
		"symbol": _encode_group_value(values.get("symbol")),
		"asset": _encode_group_value(values.get("asset")),
		"reason": _encode_group_value(values.get("reason")),
		"event_type": _encode_group_value(values.get("event_type")),
		"severity": _encode_group_value(values.get("severity")),
	})


def _encode_group_value(value):
	if value is None:
		return NULL_GROUP_VALUE
	return value


def _group_identity(filters):
	return [
		{"label": "Symbol", "value": filters.get("symbol")},
		{"label": "Asset", "value": filters.get("asset")},
		{"label": "Reason", "value": filters.get("reason")},
		{"label": "Event type", "value": filters.get("event_type")},
		{"label": "Severity", "value": filters.get("severity")},
	]


def _latest_raw_detections(queryset, limit=DETAIL_ROWS_LIMIT):
	rows = (
		queryset
		.only(
			"id",
			"detected_at",
			"run_id",
			"spot_quantity",
			"open_lot_quantity",
			"quantity_delta",
			"price_usdt",
			"estimated_value_usdt",
			"estimated_delta_value_usdt",
			"suggested_action",
			"source",
			"payload",
		)
		.order_by("-detected_at", "-id")[:limit]
	)
	return [
		{
			"row": row,
			"payload_text": _format_payload(row.payload),
			"has_payload": row.payload is not None,
		}
		for row in rows
	]


def _format_payload(payload):
	if payload is None:
		return "No payload"
	try:
		if isinstance(payload, str):
			try:
				payload = json.loads(payload)
			except (TypeError, ValueError):
				return payload
		return json.dumps(payload, indent=2, sort_keys=True, default=str)
	except (TypeError, ValueError):
		return str(payload)


def _build_summary(queryset=None, grouped_rows=None):
	if queryset is None:
		queryset = DustDetection.objects.all()
	if grouped_rows is None:
		grouped_rows = _grouped_detections(queryset)
	counts = {"critical": 0, "warning": 0, "info": 0}
	total_estimated_value_usdt = Decimal("0")
	for row in grouped_rows:
		severity = row.get("severity")
		if severity in counts:
			counts[severity] += 1
		total_estimated_value_usdt += row.get("latest_estimated_value_usdt") or Decimal("0")

	latest = _latest_detection_row(queryset)

	return {
		"total_detections": queryset.count(),
		"critical_count": counts["critical"],
		"warning_count": counts["warning"],
		"info_count": counts["info"],
		"total_estimated_value_usdt": total_estimated_value_usdt,
		"latest_run_id": latest.run_id if latest else None,
		"latest_detected_at": latest.detected_at if latest else None,
	}


def _empty_summary():
	return {
		"critical_count": 0,
		"warning_count": 0,
		"info_count": 0,
		"total_detections": 0,
		"total_estimated_value_usdt": Decimal("0"),
		"latest_run_id": None,
		"latest_detected_at": None,
	}


def _build_filter_options(queryset=None):
	if queryset is None:
		queryset = DustDetection.objects.none()
	return {
		"symbols": _distinct_values(queryset, "symbol"),
		"severities": _distinct_values(queryset, "severity"),
		"event_types": _distinct_values(queryset, "event_type"),
		"reasons": _distinct_values(queryset, "reason"),
		"review_statuses": DustSignalReview.STATUS_CHOICES,
	}


def _distinct_values(queryset, field_name):
	return list(
		queryset
		.exclude(**{f"{field_name}__isnull": True})
		.exclude(**{field_name: ""})
		.order_by(field_name)
		.values_list(field_name, flat=True)
		.distinct()
	)


def _important_queries():
	return [
		"bot.dust_detections: latest run_id ordered by detected_at desc, id desc",
		"bot.dust_detections: default dashboard scope filters to latest run_id when no filters are active",
		"bot.dust_detections: grouped row counts by severity for critical, warning, and info",
		"bot.dust_detections: Sum of latest grouped estimated_value_usdt values as approximate exposure, not PnL; not historical cumulative exposure",
		"bot.dust_detections: grouped by symbol, asset, reason, event_type, severity with COUNT and MAX(detected_at)",
		"bot.dust_detections: latest values fetched in one latest-row lookup for bounded groups",
		"Recommended production index, not managed by Django: CREATE INDEX idx_dust_run_detected ON bot.dust_detections (run_id, detected_at DESC);",
	]


def _detail_queries():
	return [
		"bot.dust_detections: exact group filter by symbol, asset, reason, event_type, severity",
		"bot.dust_detections: grouped summary for the selected group using latest row values",
		"bot.dust_detections: latest 100 raw detections for the selected group ordered by detected_at desc, id desc",
	]


def _assumptions():
	return [
		"Dashboard reads bot.dust_detections only; it never mutates bot-owned tables.",
		"estimated_value_usdt is approximate and is not interpreted as PnL.",
		"severity ordering treats critical, warning, info, then unknown as the display priority.",
	]
