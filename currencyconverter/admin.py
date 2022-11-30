from django.contrib import admin
from currencyconverter import models

# Register your models here.
admin.site.register(models.Currency)
admin.site.register(models.ExchangeRate)