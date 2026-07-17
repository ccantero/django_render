from django.shortcuts import render
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db import DatabaseError

import json
import logging
import requests
from core.models import BotControl, TelegramMessage

TELEGRAM_WEBHOOK_TOKEN = settings.TELEGRAM_WEBHOOK_TOKEN
logger = logging.getLogger(__name__)

HELP_RESPONSE = "\n".join([
    "<b>🤖 Bot commands</b>",
    "",
    "<b>General</b>",
    "• /start — greet the user",
    "• /help — show this guide",
    "• /health — bot heartbeat and position counts",
    "• /buy_status — BUY capacity and blockers",
    "• /portfolio_status — portfolio performance summary",
    "• /position SYMBOL — quantity, value, and drift",
    "• /last_sell SYMBOL — latest SELL diagnostic",
    "• /why_not_sell SYMBOL — latest skipped/rejected SELL reason",
    "",
    "<b>Legacy</b>",
    "• /getmyinvest — placeholder, not implemented yet",
    "",
    "Example: <code>/position XRPUSDT</code>",
])

class ThanksPage(TemplateView):
    template_name = 'thanks.html'

class HomePage(TemplateView):
    template_name = 'index.html'
    
class AboutMePage(TemplateView):
    template_name = 'aboutme.html'

# Create your views here.
def index(request):
    return render(request, 'core/index.html', {})


@require_GET
def health(request):
	return JsonResponse({"status": "ok"})


def bot_control_payload(control):
	return {
		"is_paused": control.is_paused,
		"status": "paused" if control.is_paused else "running",
		"updated_at": control.updated_at.isoformat() if control.updated_at else None,
		"updated_by": str(control.updated_by) if control.updated_by else None,
		"reason": control.reason,
	}


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


def diagnostic_response(*args, **kwargs):
    """Import database-backed diagnostics only when a non-static command needs them."""
    from core.telegram_diagnostics import diagnostic_response as dispatch
    return dispatch(*args, **kwargs)


def _is_authorized_telegram_actor(chat_id, user_id):
    allowed_chat_ids = {value.strip() for value in settings.TELEGRAM_ALLOWED_CHAT_IDS.split(',') if value.strip()}
    allowed_user_ids = {value.strip() for value in settings.TELEGRAM_ALLOWED_USER_IDS.split(',') if value.strip()}
    return str(chat_id) in allowed_chat_ids or (user_id is not None and str(user_id) in allowed_user_ids)


def _record_telegram_message(*, message_text, message_id, chat_id, username, context):
    try:
        if TelegramMessage.objects.filter(chat_id=str(chat_id), message_id=message_id).exists():
            logger.info("Telegram webhook duplicate ignored", extra={**context, "stage": "deduplicate"})
            return False
        TelegramMessage.objects.create(
            message=message_text,
            message_id=message_id,
            from_username=username,
            chat_id=str(chat_id),
        )
        return True
    except DatabaseError as exc:
        logger.warning(
            "Telegram message persistence unavailable; continuing command dispatch",
            extra={**context, "stage": "persistence", "exception_class": type(exc).__name__},
        )
        return None


def _send_message_with_context(message, chat_id, context):
    delivered = send_message(message, chat_id)
    logger.info("Telegram outbound delivery completed", extra={**context, "stage": "outbound_result", "delivered": delivered})
    return delivered


def _send_photo_with_context(photo, chat_id, caption, context):
    delivered = send_photo(photo, chat_id, caption=caption)
    logger.info("Telegram outbound delivery completed", extra={**context, "stage": "outbound_result", "delivered": delivered})
    return delivered

@csrf_exempt
def listener(request):
	token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
	if token != TELEGRAM_WEBHOOK_TOKEN:
		logger.warning("Telegram webhook rejected invalid secret token", extra={"stage": "secret_validation"})
		return HttpResponseForbidden("Invalid or missing token")

	if request.method == 'GET':
		return HttpResponse("You are listening!")

	if request.method == 'POST':
		try:
			t_data = json.loads(request.body)
		except (TypeError, ValueError) as exc:
			logger.warning("Telegram webhook received malformed JSON", extra={"stage": "json_parse", "exception_class": type(exc).__name__})
			return JsonResponse({"ok": False, "error": "invalid_update"}, status=400)

		t_message = t_data.get("message") if isinstance(t_data, dict) else None
		if not isinstance(t_message, dict) or not isinstance(t_message.get("text"), str):
			logger.info("Telegram webhook ignored update without text message", extra={"stage": "update_parse", "update_id": t_data.get("update_id") if isinstance(t_data, dict) else None})
			return JsonResponse({"ok": True, "ignored": "no_text_message"})

		t_message_text = t_message["text"].strip()
		t_chat = t_message.get("chat") or {}
		t_from = t_message.get("from") or {}
		chat_id = t_chat.get('id')
		message_id = t_message.get("message_id")
		if chat_id is None or message_id is None:
			logger.warning("Telegram webhook ignored incomplete text message", extra={"stage": "update_parse", "update_id": t_data.get("update_id")})
			return JsonResponse({"ok": True, "ignored": "incomplete_message"})
		user_id = t_from.get('id')
		username = t_from.get('username', '')
		context = {"stage": "dispatch", "command": t_message_text.split(maxsplit=1)[0].lower(), "update_id": t_data.get("update_id"), "chat_id": chat_id}

		if _record_telegram_message(message_text=t_message_text, message_id=message_id, chat_id=chat_id, username=username, context=context) is False:
			return JsonResponse({"ok": True, "ignored": "duplicate"})

		if t_message_text.lower().split(maxsplit=1)[0] == "/help":
			logger.info("Telegram outbound delivery attempt", extra={**context, "stage": "outbound_attempt"})
			if _is_authorized_telegram_actor(chat_id, user_id):
				_send_message_with_context(HELP_RESPONSE, chat_id, context)
			else:
				_send_message_with_context("Unauthorized diagnostics request.", chat_id, context)
			return JsonResponse({"ok": "POST request processed"})

		try:
			diagnostic_message = diagnostic_response(t_message_text, chat_id, user_id=user_id)
		except Exception as exc:
			logger.exception("Telegram diagnostic command failed", extra={**context, "stage": "diagnostic", "exception_class": type(exc).__name__})
			diagnostic_message = "Diagnostic temporarily unavailable. Please try again shortly."
		if diagnostic_message is not None:
			logger.info("Telegram outbound delivery attempt", extra={**context, "stage": "outbound_attempt"})
			if isinstance(diagnostic_message, dict):
				message_text = diagnostic_message.get("text") or ""
				photo = diagnostic_message.get("photo")
				if photo:
					try:
						_send_photo_with_context(photo, chat_id, message_text, context)
					except Exception:
						logger.warning("Telegram diagnostic photo delivery failed; sending text fallback", exc_info=True, extra={**context, "stage": "send_photo"})
						_send_message_with_context(message_text, chat_id, context)
				else:
					_send_message_with_context(message_text, chat_id, context)
			else:
				_send_message_with_context(diagnostic_message, chat_id, context)
			return JsonResponse({"ok": "POST request processed"})
		
		if t_message_text == "/start":
			_send_message_with_context("Hi " + str(username), chat_id, context)
		elif t_message_text == "/getmyinvest":
			_send_message_with_context("Sorry " + str(username) + "!", chat_id, context)
			_send_message_with_context("<b>This functionality is not yet implemented</b>", chat_id, context)
		else:
			_send_message_with_context("Sorry " + str(username) + "!", chat_id, context)
			_send_message_with_context("My answer are limited. Please ask the right questions.", chat_id, context)

		return JsonResponse({"ok": "POST request processed"}) 
@staff_member_required
def test_speaker(request, chat_id):
	if request.method == 'GET':
		send_message("This is a test message", chat_id)
	
	return HttpResponse("You are testing speaker!")


def send_message(message, chat_id, context=None):
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    return _deliver_telegram("sendMessage", data=data, context=context)


def send_photo(photo_bytes, chat_id, caption=None, context=None):
    data = {
        "chat_id": chat_id,
        "parse_mode": "HTML",
    }
    if caption:
        data["caption"] = caption
    files = {
        "photo": ("portfolio_equity_7d.png", photo_bytes, "image/png"),
    }
    return _deliver_telegram("sendPhoto", data=data, files=files, context=context)


def _deliver_telegram(method, *, data, files=None, context=None):
    safe_context = {**(context or {}), "stage": "outbound", "telegram_method": method}
    try:
        response = requests.post(
            f"{TELEGRAM_URL}{TUTORIAL_BOT_TOKEN}/{method}",
            data=data,
            files=files,
            timeout=getattr(settings, "TELEGRAM_DELIVERY_TIMEOUT_SECONDS", 10),
        )
        if not response.ok:
            logger.warning("Telegram delivery HTTP failure", extra={**safe_context, "telegram_http_status": response.status_code})
            return False
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("Telegram delivery response parse failure", extra={**safe_context, "exception_class": type(exc).__name__})
            return False
        if not payload.get("ok"):
            logger.warning("Telegram API rejected delivery", extra={**safe_context, "telegram_error_code": payload.get("error_code"), "telegram_description": payload.get("description")})
            return False
        logger.info("Telegram delivery succeeded", extra=safe_context)
        return True
    except requests.Timeout as exc:
        logger.warning("Telegram delivery timed out", extra={**safe_context, "exception_class": type(exc).__name__})
    except requests.RequestException as exc:
        logger.warning("Telegram delivery transport failure", extra={**safe_context, "exception_class": type(exc).__name__})
    return False
