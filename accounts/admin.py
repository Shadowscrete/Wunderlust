from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class WunderlustUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Wunderlust access', {'fields': ('role',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('Wunderlust access', {'fields': ('role',)}),)
    list_display = ('username', 'email', 'role', 'is_active', 'is_staff')
    list_filter = ('role', 'is_active', 'is_staff')


from django.utils import timezone  # noqa: E402

from .models import Follow, Report  # noqa: E402


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('reported_user', 'reason', 'reporter', 'status', 'created_at')
    list_filter = ('status', 'reason')
    search_fields = ('reported_user__username', 'reporter__username', 'details')
    readonly_fields = ('reporter', 'reported_user', 'reason', 'details', 'created_at')
    actions = ('mark_reviewed', 'mark_dismissed')

    @admin.action(description='Mark selected reports as reviewed')
    def mark_reviewed(self, request, queryset):
        queryset.update(status=Report.Status.REVIEWED, reviewed_at=timezone.now())

    @admin.action(description='Dismiss selected reports')
    def mark_dismissed(self, request, queryset):
        queryset.update(status=Report.Status.DISMISSED, reviewed_at=timezone.now())


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ('follower', 'following', 'created_at')
    search_fields = ('follower__username', 'following__username')
