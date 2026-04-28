from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from django_render.env_validation import required_env_vars, validate_required_env_vars


class EnvironmentValidationTests(SimpleTestCase):
	def test_required_env_vars_include_database_url_in_production(self):
		self.assertIn("DATABASE_URL", required_env_vars(debug=False))
		self.assertNotIn("DATABASE_URL", required_env_vars(debug=True))

	def test_validate_required_env_vars_accepts_complete_debug_config(self):
		values = {
			"CC_DEBUG": "True",
			"SECRET_KEY": "secret",
			"TUTORIAL_BOT_TOKEN": "bot-token",
			"TELEGRAM_WEBHOOK_TOKEN": "webhook-token",
		}

		validate_required_env_vars(values.get, debug=True)

	def test_validate_required_env_vars_raises_for_missing_telegram_tokens(self):
		values = {
			"CC_DEBUG": "True",
			"SECRET_KEY": "secret",
		}

		with self.assertRaisesMessage(
			ImproperlyConfigured,
			"TELEGRAM_WEBHOOK_TOKEN, TUTORIAL_BOT_TOKEN",
		):
			validate_required_env_vars(values.get, debug=True)

	def test_validate_required_env_vars_raises_for_missing_database_url_in_production(self):
		values = {
			"CC_DEBUG": "False",
			"SECRET_KEY": "secret",
			"TUTORIAL_BOT_TOKEN": "bot-token",
			"TELEGRAM_WEBHOOK_TOKEN": "webhook-token",
		}

		with self.assertRaisesMessage(ImproperlyConfigured, "DATABASE_URL"):
			validate_required_env_vars(values.get, debug=False)
