from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import UserSession
from .sessions import track_session


@receiver(user_logged_in)
def remember_device(sender, request, user, **kwargs):
    track_session(request, user)


@receiver(user_logged_out)
def forget_device(sender, request, user, **kwargs):
    key = request.session.session_key
    if key:
        UserSession.objects.filter(session_key=key).delete()
