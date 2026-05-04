from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST

import json
import requests
from core.forms import ManualCorrectionRequestForm
from core.dashboard_read_model import get_dashboard_context, get_demo_dashboard_context
from core.dust_read_model import (
	get_dust_dashboard_context,
	get_dust_detail_context,
	update_dust_signal_review,
)
from core.models import BotControl, ManualCorrection, TelegramMessage

TELEGRAM_WEBHOOK_TOKEN = settings.TELEGRAM_WEBHOOK_TOKEN

class ThanksPage(TemplateView):
    template_name = 'thanks.html'

class HomePage(TemplateView):
    template_name = 'index.html'
    
class AboutMePage(TemplateView):
    template_name = 'aboutme.html'

# Create your views here.
def index(request):
    return render(request, 'core/index.html', {})


def bot_control_payload(control):
	return {
		"is_paused": control.is_paused,
		"status": "paused" if control.is_paused else "running",
		"updated_at": control.updated_at.isoformat() if control.updated_at else None,
		"updated_by": str(control.updated_by) if control.updated_by else None,
		"reason": control.reason,
	}


@login_required
def dashboard(request):
	read_model = get_dashboard_context()
	return render(request, "dashboard.html", read_model.context)


def dashboard_demo(request):
	read_model = get_demo_dashboard_context()
	return render(request, "dashboard.html", read_model.context)


@login_required
def dust_dashboard(request):
	read_model = get_dust_dashboard_context(request.GET)
	return render(request, "dust_dashboard.html", read_model.context)


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
	return render(request, "dust_detail.html", read_model.context)


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
			correction.save()
			return redirect("manual_correction_detail", correction_id=correction.id)
	else:
		form = ManualCorrectionRequestForm(initial=initial)

	return render(request, "manual_correction_form.html", {
		"form": form,
		"source_querystring": request.GET.urlencode(),
	})


@login_required
def manual_corrections(request, status):
	status = status.upper()
	if status not in dict(ManualCorrection.STATUS_CHOICES):
		status = ManualCorrection.STATUS_PENDING
	corrections = ManualCorrection.objects.filter(status=status).order_by("-created_at", "-id")[:100]
	return render(request, "manual_corrections.html", {
		"corrections": corrections,
		"status": status,
		"status_choices": ManualCorrection.STATUS_CHOICES,
	})


@login_required
def manual_correction_detail(request, correction_id):
	correction = get_object_or_404(ManualCorrection, pk=correction_id)
	return render(request, "manual_correction_detail.html", {"correction": correction})


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


@login_required
@require_GET
def bot_status(request):
	control = BotControl.get_solo()
	return JsonResponse(bot_control_payload(control))


@login_required
@require_POST
def bot_stop(request):
	control = BotControl.get_solo()
	control.is_paused = True
	control.reason = request.POST.get("reason", "")
	control.updated_by = request.user
	control.save(update_fields=["is_paused", "reason", "updated_by", "updated_at"])
	return JsonResponse(bot_control_payload(control))


@login_required
@require_POST
def bot_resume(request):
	control = BotControl.get_solo()
	control.is_paused = False
	control.reason = request.POST.get("reason", "")
	control.updated_by = request.user
	control.save(update_fields=["is_paused", "reason", "updated_by", "updated_at"])
	return JsonResponse(bot_control_payload(control))

TELEGRAM_URL = "https://api.telegram.org/bot"
TUTORIAL_BOT_TOKEN = settings.TUTORIAL_BOT_TOKEN

@csrf_exempt
def listener(request):
	token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
	if token != TELEGRAM_WEBHOOK_TOKEN:
		return HttpResponseForbidden("Invalid or missing token")

	if request.method == 'GET':
		return HttpResponse("You are listening!")

	if request.method == 'POST':
		t_data = json.loads(request.body)
		t_message = t_data["message"]
		
		t_message_text = t_message["text"]
		message_id = t_message["message_id"]
		
		t_chat = t_message["chat"]
		t_from = t_message["from"]

		chat_id = t_chat['id']
		username = t_from['username']

		myTelegramMessage = TelegramMessage()
		myTelegramMessage.message = t_message_text
		myTelegramMessage.message_id = message_id
		myTelegramMessage.from_username = username
		myTelegramMessage.chat_id = chat_id
		myTelegramMessage.save()
		
		if t_message_text == "/start":
			send_message("Hi " + str(username), chat_id)
		elif t_message_text == "/getmyinvest":
			send_message("Sorry " + str(username) + "!", chat_id)
			send_message("<b>This functionality is not yet implemented</b>", chat_id)
		else:
			send_message("Sorry " + str(username) + "!", chat_id)
			send_message("My answer are limited. Please ask the right questions.", chat_id)

		return JsonResponse({"ok": "POST request processed"}) 
@staff_member_required
def test_speaker(request, chat_id):
	if request.method == 'GET':
		send_message("This is a test message", chat_id)
	
	return HttpResponse("You are testing speaker!")


def send_message(message, chat_id):
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    response = requests.post(
        f"{TELEGRAM_URL}{TUTORIAL_BOT_TOKEN}/sendMessage", data=data
    )
