from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(role):
    """Require login and one explicit account role for a dashboard view."""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.user.role != role:
                if request.user.role == request.user.Role.ADMINISTRATOR and role == request.user.Role.TRAVELER:
                    from django.shortcuts import redirect
                    return redirect('admin_dashboard')
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
