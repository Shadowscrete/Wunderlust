from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.utils import timezone


def role_required(role):
    """Require login and one explicit account role for a dashboard view."""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            # cache.add succeeds only once per day, so trip statuses are refreshed daily without a per-request cost.
            if cache.add(f'trip-status-sync-{timezone.localdate()}', True, 60 * 60 * 24):
                from .models import sync_trip_statuses
                sync_trip_statuses()
            if request.user.role != role:
                if request.user.role == request.user.Role.ADMINISTRATOR and role == request.user.Role.TRAVELER:
                    from django.shortcuts import redirect
                    return redirect('admin_dashboard')
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
