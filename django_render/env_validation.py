from django.core.exceptions import ImproperlyConfigured


def required_env_vars(debug):
	required = [
		"CC_DEBUG",
		"SECRET_KEY",
		"TUTORIAL_BOT_TOKEN",
		"TELEGRAM_WEBHOOK_TOKEN",
	]
	if not debug:
		required.append("DATABASE_URL")
	return required


def validate_required_env_vars(env_getter, debug):
	missing = [
		name
		for name in required_env_vars(debug)
		if not str(env_getter(name, "")).strip()
	]
	if missing:
		raise ImproperlyConfigured(
			"Missing required environment variables: " + ", ".join(sorted(missing))
		)
