"""Small, dependency-free abuse protection backed by the shared cache.

Keys are SHA-256 hashes, so no usernames or IP addresses are stored in the cache in plain text,
and every counter expires on its own (nothing grows without bound).
"""
import hashlib

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    # On Vercel the platform proxy sets X-Forwarded-For; its first entry is the real client.
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')) or 'unknown'


def _key(scope, *parts):
    digest = hashlib.sha256('|'.join(str(p).lower() for p in parts).encode()).hexdigest()[:32]
    return f'rl:{scope}:{digest}'


def _increment(key, window):
    if cache.add(key, 1, window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, window)
        return 1


# ---- Login lockout -------------------------------------------------------------------------------

def login_locked(request, username):
    limit = getattr(settings, 'LOGIN_MAX_ATTEMPTS', 5)
    return (cache.get(_key('login', username, client_ip(request)), 0) >= limit
            or cache.get(_key('login-ip', client_ip(request)), 0) >= limit * 6)


def record_login_failure(request, username):
    window = getattr(settings, 'LOGIN_LOCKOUT_SECONDS', 900)
    _increment(_key('login', username, client_ip(request)), window)
    # Also cap one address trying many different usernames.
    _increment(_key('login-ip', client_ip(request)), window)


def clear_login_failures(request, username):
    cache.delete(_key('login', username, client_ip(request)))


# ---- Generic per-user / per-address rate limit ---------------------------------------------------

def rate_limited(request, scope, limit, window):
    """True once this user (or address, when signed out) has made more than `limit` calls in `window` seconds."""
    who = request.user.pk if getattr(request, 'user', None) and request.user.is_authenticated else client_ip(request)
    return _increment(_key(scope, who), window) > limit
