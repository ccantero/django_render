from django.contrib import admin
from core import models

# Register your models here.
class TelegramMessageAdmin(admin.ModelAdmin):
    list_display = ('message_id', 'chat_id', 'from_username', 'message', 'create_date')

admin.site.register(models.TelegramMessage, TelegramMessageAdmin)