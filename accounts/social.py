"""Follow / friend helpers shared by the social views."""
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Follow, Profile

User = get_user_model()


def discoverable_users():
    """Travelers others can find and follow (administrators and deactivated accounts are excluded)."""
    return User.objects.filter(is_active=True, role=User.Role.TRAVELER)


def avatar_url_for(user):
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        return ''
    return profile.avatar.url if profile.avatar else ''


def initials_for(user):
    if user.first_name:
        return (user.first_name[:1] + user.last_name[:1]).upper()
    return user.get_username()[:1].upper()


def relationship(viewer, other):
    """How `viewer` and `other` are connected, from two indexed lookups."""
    i_follow = Follow.objects.filter(follower=viewer, following=other).exists()
    follows_me = Follow.objects.filter(follower=other, following=viewer).exists()
    return {'i_follow': i_follow, 'follows_me': follows_me, 'is_friend': i_follow and follows_me}


def connection_sets(user):
    """(ids I follow, ids following me) in two queries."""
    following = set(Follow.objects.filter(follower=user).values_list('following_id', flat=True))
    followers = set(Follow.objects.filter(following=user).values_list('follower_id', flat=True))
    return following, followers


def notify_follow(actor, target, became_friends):
    """Tell `target` about a new follow, unless they turned it off or were already told today
    (stops follow/unfollow spam from flooding their inbox)."""
    from trips.models import Notification
    if Profile.objects.filter(user=target, notify_new_followers=False).exists():
        return
    name = actor.get_full_name() or actor.get_username()
    if became_friends:
        title, message = 'New friend', f'You and {name} (@{actor.get_username()}) are now friends.'
    else:
        title, message = 'New follower', f'{name} (@{actor.get_username()}) started following you.'
    already = Notification.objects.filter(user=target, title=title, message=message,
                                          created_at__date=timezone.localdate()).exists()
    if not already:
        Notification.objects.create(user=target, title=title, message=message)
