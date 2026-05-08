from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from dashboard.dashboard_read_model import get_dashboard_context, get_demo_dashboard_context
from dashboard.dust_read_model import (
	get_dust_dashboard_context,
	get_dust_detail_context,
	update_dust_signal_review,
)
from dashboard.forms import ManualCorrectionRequestForm
from core.models import ManualCorrection


@login_required
def dashboard(request):
	read_model = get_dashboard_context()
	return render(request, "dashboard/dashboard.html", read_model.context)


def dashboard_demo(request):
	read_model = get_demo_dashboard_context()
	return render(request, "dashboard/dashboard.html", read_model.context)


@login_required
def dust_dashboard(request):
	read_model = get_dust_dashboard_context(request.GET)
	return render(request, "dashboard/dust_dashboard.html", read_model.context)


@login_required
def dust_detail(request):
	if request.method == "POST":
		update_dust_signal_review(
			request.POST,
			request.POST.get("status", ""),
			request.POST.get("note", ""),
			request.user,
		)
		querystring = request.POST.get("group_querystring", "")
		redirect_url = reverse("dust_detail")
		if querystring:
			redirect_url = f"{redirect_url}?{querystring}"
		return redirect(redirect_url)

	read_model = get_dust_detail_context(request.GET)
	return render(request, "dashboard/dust_detail.html", read_model.context)


def staff_or_superuser_required(view_func):
	@login_required
	def wrapped(request, *args, **kwargs):
		if not (request.user.is_staff or request.user.is_superuser):
			return HttpResponseForbidden("Staff access required.")
		return view_func(request, *args, **kwargs)
	return wrapped


@staff_or_superuser_required
def manual_correction_new(request):
	initial = _manual_correction_initial(request)
	if request.method == "POST":
		form = ManualCorrectionRequestForm(request.POST)
		if form.is_valid():
			correction = form.save(commit=False)
			correction.status = ManualCorrection.STATUS_PENDING
			correction.requested_by = _requested_by(request.user)
			correction.estimated_value_usdt = correction.quantity * correction.price_usdt
			correction.payload = {
				"source": "django_dashboard",
				"source_querystring": request.GET.urlencode(),
			}
			try:
				correction.save()
			except DatabaseError:
				form.add_error(
					None,
					"The correction request could not be saved. The bot remains the source of truth for duplicate correction validation.",
				)
			else:
				return redirect("manual_correction_detail", correction_id=correction.id)
	else:
		form = ManualCorrectionRequestForm(initial=initial)

	return render(request, "dashboard/manual_correction_form.html", {
		"form": form,
		"source_querystring": request.GET.urlencode(),
	})


@login_required
def manual_corrections(request, status):
	status = status.upper()
	if status not in dict(ManualCorrection.STATUS_CHOICES):
		status = ManualCorrection.STATUS_PENDING
	corrections = ManualCorrection.objects.filter(status=status).order_by("-created_at", "-id")[:100]
	return render(request, "dashboard/manual_corrections.html", {
		"corrections": corrections,
		"status": status,
		"status_choices": ManualCorrection.STATUS_CHOICES,
	})


@login_required
def manual_correction_detail(request, correction_id):
	correction = get_object_or_404(ManualCorrection, pk=correction_id)
	return render(request, "dashboard/manual_correction_detail.html", {"correction": correction})


def _manual_correction_initial(request):
	read_model = get_dust_detail_context(request.GET)
	group_summary = read_model.context.get("group_summary") or {}
	filters = read_model.context.get("filters") or {}
	return {
		"correction_type": ManualCorrection.TYPE_CLOSE_LOTS_EXTERNAL_SELL,
		"symbol": filters.get("symbol") or group_summary.get("symbol") or "",
		"asset": filters.get("asset") or group_summary.get("asset") or "",
		"quantity": _manual_correction_quantity(group_summary),
		"price_usdt": group_summary.get("latest_price_usdt") or "",
		"reason": group_summary.get("reason") or filters.get("reason") or "",
		"source_detection_id": group_summary.get("latest_detection_id") or "",
		"review_note": "",
	}


def _manual_correction_quantity(group_summary):
	open_lot_quantity = group_summary.get("latest_open_lot_quantity")
	spot_quantity = group_summary.get("latest_spot_quantity")
	if open_lot_quantity is not None and spot_quantity is not None:
		if open_lot_quantity > spot_quantity:
			return open_lot_quantity - spot_quantity
		return ""

	quantity_delta = group_summary.get("latest_quantity_delta")
	if quantity_delta is not None and quantity_delta < 0:
		return abs(quantity_delta)
	return ""


def _requested_by(user):
	for attr in ("email", "username"):
		value = getattr(user, attr, "")
		if value:
			return value
	return str(user)
