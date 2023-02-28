from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from profile import models

# Register your models here.
#admin.site.register(models.UserProfile)

class UserAdmin(BaseUserAdmin):
    ordering = ['id']
    list_display = ['name', 'email']
    # Change User
    fieldsets = (
        (
            None, {
                'fields': ('email', 'password')
            }
        ),
        (
            _('Permissions'), {
                'fields': ('is_active', 'is_staff', 'is_superuser')
            }
        ),
        (
            _('Important dates'), {
                'fields': ('last_login', )
            }
        )
    )
    readonly_fields = ['last_login']
    # Create User
    add_fieldsets = (
        (
            None, {
                'classes':('wide', ),
                'fields': (
                    'email', 
                    'password1',
                    'password2',
                    'is_active',
                    'is_staff',
                    'is_superuser'
                 )
            }
        ),
    )

admin.site.register(models.UserProfile, UserAdmin)
admin.site.unregister(Group)