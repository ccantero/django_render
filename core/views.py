from django.shortcuts import render
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse

import os
import json
import requests
from core.models import TelegramMessage

class ThanksPage(TemplateView):
    template_name = 'thanks.html'

class HomePage(TemplateView):
    template_name = 'index.html'

# Create your views here.
def index(request):
    return render(request, 'core/index.html', {})

TELEGRAM_URL = "https://api.telegram.org/bot"
TUTORIAL_BOT_TOKEN = os.getenv("TUTORIAL_BOT_TOKEN", "error_token")

@csrf_exempt
def listener(request):

	if TUTORIAL_BOT_TOKEN == 'error_token':
		return HttpResponse("<h1>Unable to find TUTORIAL_BOT_TOKEN</h1>")

	if request.method == 'GET':
		return HttpResponse(f"You are listening!<br>{TELEGRAM_URL}{TUTORIAL_BOT_TOKEN}/")

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
			#list_of_profiles = Profile.objects.filter(telegram_user__iexact=username)
			#if len(list_of_profiles) == 0:
			#	send_message("Seems you have not yet associated your misgastos account with this Telegram profile", chat_id)
			#else:
			#	send_message("What do you want to do my friend?", chat_id)
		elif t_message_text == "/getmyinvest":
			send_message("Sorry " + str(username) + "!", chat_id)
			send_message("<b>This functionality is not yet implemented</b>", chat_id)
		else:
			send_message("Sorry " + str(username) + "!", chat_id)
			send_message("My answer are limited. Please ask the right questions.", chat_id)

		return JsonResponse({"ok": "POST request processed"}) 
@csrf_exempt
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