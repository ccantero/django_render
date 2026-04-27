from django.shortcuts import render
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST

import os
import json
import requests
from core.models import BotControl, TelegramMessage

TELEGRAM_WEBHOOK_TOKEN = os.getenv("TELEGRAM_WEBHOOK_TOKEN")

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
	control = BotControl.get_solo()
	context = {
		"bot_control": control,
		"bot_status": bot_control_payload(control),
		"pnl": None,
		"trades": [],
		"positions": [],
	}
	return render(request, "dashboard.html", context)


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
TUTORIAL_BOT_TOKEN = os.getenv("TUTORIAL_BOT_TOKEN", "error_token")

@csrf_exempt
def listener(request):
	token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
	if TELEGRAM_WEBHOOK_TOKEN and token != TELEGRAM_WEBHOOK_TOKEN:
		return HttpResponseForbidden("Invalid or missing token")

	if TUTORIAL_BOT_TOKEN == 'error_token':
		return HttpResponse("<h1>Unable to find TUTORIAL_BOT_TOKEN</h1>")

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
	if TUTORIAL_BOT_TOKEN == 'error_token':
		return HttpResponse("There is not TUTORIAL_BOT_TOKEN")

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
