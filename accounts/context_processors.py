from django.core.cache import cache

from .models import Profile

DEFAULT_PREFS = {'avatar_url': '', 'theme': Profile.Theme.SYSTEM, 'notify_system': True}


def _prefs_key(user_id):
    return f'user-prefs:{user_id}'


def get_user_prefs(user):
    """Header avatar, theme and notice preference for a user.
    Cached so every page doesn't pay a round-trip to the remote database."""
    key = _prefs_key(user.pk)
    prefs = cache.get(key)
    if prefs is None:
        profile = Profile.objects.filter(user=user).only('avatar', 'theme', 'notify_system').first()
        prefs = dict(DEFAULT_PREFS)
        if profile:
            prefs = {
                'avatar_url': profile.avatar.url if profile.avatar else '',
                'theme': profile.theme,
                'notify_system': profile.notify_system,
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
    return {'avatar_url': prefs['avatar_url'], 'user_theme': prefs['theme']}
