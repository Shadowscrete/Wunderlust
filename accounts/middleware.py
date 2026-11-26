import zoneinfo

from django.utils import timezone

from .context_processors import get_user_prefs


class UserTimezoneMiddleware:
    """Activate the signed-in user's own time zone, so "today" (inbox, trip status, reminders) matches
    their clock instead of the server's UTC. The value comes from the cached preferences: no extra query."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        name = ''
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            name = get_user_prefs(user).get('timezone', '')
        try:
            timezone.activate(zoneinfo.ZoneInfo(name)) if name else timezone.deactivate()
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            timezone.deactivate()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
