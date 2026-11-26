from django.core.cache import cache

from .models import Profile

DEFAULT_PREFS = {'avatar_url': '', 'theme': Profile.Theme.SYSTEM, 'notify_system': True, 'timezone': ''}


def _prefs_key(user_id):
    return f'user-prefs:{user_id}'


def get_user_prefs(user):
    """Header avatar, theme and notice preference for a user.
    Cached so every page doesn't pay a round-trip to the remote database."""
    key = _prefs_key(user.pk)
    prefs = cache.get(key)
    if prefs is None or 'timezone' not in prefs:
        profile = Profile.objects.filter(user=user).only('avatar', 'theme', 'notify_system', 'timezone').first()
        prefs = dict(DEFAULT_PREFS)
        if profile:
            prefs = {
                'avatar_url': profile.avatar.url if profile.avatar else '',
                'theme': profile.theme,
                'notify_system': profile.notify_system,
                'timezone': profile.timezone,
            }
        cache.set(key, prefs, 60 * 60)
    return prefs


def clear_user_prefs(user_id):
    cache.delete(_prefs_key(user_id))


def user_prefs(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    prefs = get_user_prefs(user)
    context = {'avatar_url': prefs['avatar_url'], 'user_theme': prefs['theme'], 'user_timezone': prefs['timezone']}
    if user.role == user.Role.ADMINISTRATOR:
        context['admin_open_reports'] = open_report_count()
    return context


def open_report_count():
    """Sidebar badge for administrators. One shared number (no personal data), cached for a minute."""
    count = cache.get('admin-open-reports')
    if count is None:
        from .models import Report
        count = Report.objects.filter(status=Report.Status.OPEN).count()
        cache.set('admin-open-reports', count, 60)
    return count
