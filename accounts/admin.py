from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'whatsapp', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('الدور والاتصال', {'fields': ('role', 'whatsapp')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('الدور والاتصال', {'fields': ('role', 'whatsapp')}),
    )
