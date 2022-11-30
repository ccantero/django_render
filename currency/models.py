from django.db import models

# Create your models here.
class Currency(models.Model):
    key = models.SlugField(allow_unicode=True)
    description = models.CharField(blank=True,default='',max_length=255)