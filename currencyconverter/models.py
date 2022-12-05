from django.db import models
from django.utils import timezone

# Create your models here.
class Currency(models.Model):
    class Meta:
        verbose_name_plural = "currencies"

    key = models.SlugField(allow_unicode=True, primary_key=True, unique=True)
    description = models.CharField(blank=True,default='',max_length=255)

    def __str__(self):
        return self.key

class ExchangeRate(models.Model):
    name = models.CharField(blank=True,default='',max_length=255, unique=True)
    numerator = models.ForeignKey(	Currency, 
                                to_field='key',
                                related_name='numerator', 
                                on_delete=models.PROTECT)
    denominator = models.ForeignKey(	Currency, 
                            to_field='key',
                            related_name='denominator', 
                            on_delete=models.PROTECT)
    last_update = models.DateTimeField(default=timezone.now)
    last_quote = models.FloatField(default=0.0)

    def __str__(self):
        return self.name