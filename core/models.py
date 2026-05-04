from django.conf import settings
from django.db import models
from django.utils import timezone


def bot_table_name(table_name):
	if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
		return table_name
	return f'"bot"."{table_name}"'


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


class DustSignalReview(models.Model):
	STATUS_PENDING = "pending"
	STATUS_REVIEWED = "reviewed"
	STATUS_IGNORED = "ignored"
	STATUS_REVIEW_LATER = "review_later"
	STATUS_NEEDS_MANUAL_CORRECTION = "needs_manual_correction"
	STATUS_EXTERNAL_OR_EARN = "external_or_earn"

	STATUS_CHOICES = [
		(STATUS_PENDING, "Pending"),
		(STATUS_REVIEWED, "Reviewed"),
		(STATUS_IGNORED, "Ignored"),
		(STATUS_REVIEW_LATER, "Review later"),
		(STATUS_NEEDS_MANUAL_CORRECTION, "Needs manual correction"),
		(STATUS_EXTERNAL_OR_EARN, "External or Earn"),
	]

	symbol = models.CharField(max_length=32, blank=True, default="")
	asset = models.CharField(max_length=32, blank=True, default="")
	reason = models.TextField(blank=True, default="")
	event_type = models.CharField(max_length=64, blank=True, default="")
	severity = models.CharField(max_length=32, blank=True, default="")
	status = models.CharField(
		max_length=32,
		choices=STATUS_CHOICES,
		default=STATUS_PENDING,
	)
	note = models.TextField(blank=True)
	reviewed_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		null=True,
		blank=True,
		on_delete=models.SET_NULL,
	)
	reviewed_at = models.DateTimeField(blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		managed = False
		db_table = bot_table_name("dust_signal_reviews")
		constraints = [
			models.UniqueConstraint(
				fields=["symbol", "asset", "reason", "event_type", "severity"],
				name="unique_dust_signal_review_identity",
			),
		]

	def __str__(self):
		return f"{self.symbol or '-'} {self.reason or '-'} ({self.status})"


class ManualCorrection(models.Model):
	STATUS_PENDING = "PENDING"
	STATUS_APPLIED = "APPLIED"
	STATUS_REJECTED = "REJECTED"
	STATUS_FAILED = "FAILED"

	STATUS_CHOICES = [
		(STATUS_PENDING, "Pending"),
		(STATUS_APPLIED, "Applied"),
		(STATUS_REJECTED, "Rejected"),
		(STATUS_FAILED, "Failed"),
	]

	TYPE_CLOSE_LOTS_EXTERNAL_SELL = "CLOSE_LOTS_EXTERNAL_SELL"
	TYPE_REDUCE_LOTS_EXTERNAL_MOVEMENT = "REDUCE_LOTS_EXTERNAL_MOVEMENT"
	TYPE_CREATE_EXTERNAL_LOT = "CREATE_EXTERNAL_LOT"
	TYPE_MARK_DUST_IGNORED = "MARK_DUST_IGNORED"

	CORRECTION_TYPE_CHOICES = [
		(TYPE_CLOSE_LOTS_EXTERNAL_SELL, "Close lots external sell"),
		(TYPE_REDUCE_LOTS_EXTERNAL_MOVEMENT, "Reduce lots external movement"),
		(TYPE_CREATE_EXTERNAL_LOT, "Create external lot"),
		(TYPE_MARK_DUST_IGNORED, "Mark dust ignored"),
	]

	created_at = models.DateTimeField(default=timezone.now)
	applied_at = models.DateTimeField(blank=True, null=True)
	status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
	correction_type = models.CharField(max_length=64, choices=CORRECTION_TYPE_CHOICES)
	symbol = models.CharField(max_length=32)
	asset = models.CharField(max_length=32)
	quantity = models.DecimalField(max_digits=38, decimal_places=18)
	price_usdt = models.DecimalField(max_digits=38, decimal_places=18)
	estimated_value_usdt = models.DecimalField(max_digits=38, decimal_places=18, blank=True, null=True)
	reason = models.TextField()
	requested_by = models.CharField(max_length=255, blank=True)
	reviewed_by = models.CharField(max_length=255, blank=True)
	review_note = models.TextField(blank=True)
	source_detection_id = models.BigIntegerField(blank=True, null=True)
	payload = models.JSONField(blank=True, null=True)
	error_message = models.TextField(blank=True)

	class Meta:
		managed = False
		db_table = bot_table_name("manual_corrections")
		ordering = ["-created_at", "-id"]

	def __str__(self):
		return f"{self.correction_type} {self.symbol} ({self.status})"
