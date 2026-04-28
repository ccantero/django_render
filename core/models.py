from django.conf import settings
from django.db import models
from django.utils import timezone


class TelegramMessage(models.Model):
	message_id = models.PositiveIntegerField()
	chat_id = models.CharField(max_length=255)
	from_username = models.CharField(max_length=255)
	message = models.TextField()
	create_date = models.DateTimeField(default=timezone.now)


class BotControl(models.Model):
	is_paused = models.BooleanField(default=False)
	updated_at = models.DateTimeField(auto_now=True)
	updated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		null=True,
		blank=True,
		on_delete=models.SET_NULL,
	)
	reason = models.TextField(blank=True)

	@classmethod
	def get_solo(cls):
		control, _ = cls.objects.get_or_create(pk=1)
		return control

	def __str__(self):
		return "Paused" if self.is_paused else "Running"


class AppSetting(models.Model):
	key = models.CharField(max_length=128, unique=True)
	value = models.CharField(max_length=255)
	description = models.TextField(blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = "app_settings"

	def __str__(self):
		return self.key

