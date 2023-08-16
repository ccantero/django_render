from django.db import models

# Create your models here.
from django.utils import timezone

class TelegramMessage(models.Model):
	message_id = models.PositiveIntegerField()
	chat_id = models.CharField(max_length=255)
	from_username = models.CharField(max_length=255)
	message = models.TextField()
	create_date = models.DateTimeField(default=timezone.now)