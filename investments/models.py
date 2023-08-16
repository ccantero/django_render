from django.db import models
from django.utils import timezone

from django.contrib.auth import get_user_model
User = get_user_model()

# Create your models here.
class Invest(models.Model):
	name = models.CharField(max_length=100)
	amount = models.FloatField()
	initial_rate = models.FloatField()
	create_date = models.DateTimeField(default=timezone.now)
	user = models.ForeignKey(User,related_name='investments',on_delete=models.PROTECT)