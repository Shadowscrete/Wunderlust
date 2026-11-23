from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class WunderlustUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Wunderlust access', {'fields': ('role',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('Wunderlust access', {'fields': ('role',)}),)
    list_display = ('username', 'email', 'role', 'is_active', 'is_staff')
    list_filter = ('role', 'is_active', 'is_staff')
