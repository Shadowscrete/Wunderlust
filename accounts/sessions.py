from importlib import import_module

from django.conf import settings
from django.contrib.sessions.models import Session
from django.utils import timezone

from .models import UserSession

SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


def describe_device(user_agent):
    """A friendly label like "Chrome on Windows" from a User-Agent string."""
    ua = user_agent or ''
    if 'Edg/' in ua:
        browser = 'Edge'
    elif 'OPR/' in ua or 'Opera' in ua:
        browser = 'Opera'
    elif 'Firefox/' in ua:
        browser = 'Firefox'
    elif 'Chrome/' in ua or 'CriOS/' in ua:
        browser = 'Chrome'
    elif 'Safari/' in ua:
        browser = 'Safari'
    else:
        browser = 'Browser'
    if 'iPhone' in ua or 'iPad' in ua:
        system = 'iOS'
    elif 'Android' in ua:
        system = 'Android'
    elif 'Windows' in ua:
        system = 'Windows'
    elif 'Mac OS X' in ua or 'Macintosh' in ua:
        system = 'macOS'
    elif 'Linux' in ua:
        system = 'Linux'
    else:
        system = 'unknown device'
    return f'{browser} on {system}'


def track_session(request, user):
    key = request.session.session_key
    if not key:
        return
    UserSession.objects.update_or_create(
        session_key=key,
        defaults={'user': user, 'user_agent': request.headers.get('User-Agent', '')[:300]},
    )


def active_devices(request):
    """The user's signed-in devices, newest first. Stale rows (expired sessions) are cleaned up."""
    user = request.user
    current_key = request.session.session_key
    if current_key and not UserSession.objects.filter(session_key=current_key).exists():
        track_session(request, user)  # sessions from before device tracking existed
    rows = list(UserSession.objects.filter(user=user))
    live = set(Session.objects.filter(
        session_key__in=[row.session_key for row in rows], expire_date__gt=timezone.now(),
    ).values_list('session_key', flat=True))
    stale = [row.pk for row in rows if row.session_key not in live]
    if stale:
        UserSession.objects.filter(pk__in=stale).delete()
    return [{
        'id': row.pk,
        'label': describe_device(row.user_agent),
        'signed_in': row.created_at,
        'is_current': row.session_key == current_key,
    } for row in rows if row.session_key in live]


def end_session(session_key):
    SessionStore(session_key=session_key).delete()  # also clears the cached copy
    UserSession.objects.filter(session_key=session_key).delete()


def sign_out_other_sessions(request):
    """Ends every other session for this user, including ones started before device tracking."""
    user, current = request.user, request.session.session_key
    keys = set(UserSession.objects.filter(user=user).exclude(session_key=current).values_list('session_key', flat=True))
    for session in Session.objects.filter(expire_date__gt=timezone.now()).exclude(session_key=current):
        if session.get_decoded().get('_auth_user_id') == str(user.pk):
            keys.add(session.session_key)
    for key in keys:
        end_session(key)
    return len(keys)
